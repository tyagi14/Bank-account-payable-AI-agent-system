"""Risk-Scoring agent: server-side vendor history (never client-supplied) + a reasoning-model risk judgment."""
import json

from app import config, governance, ledger_client, llm
from app.agents.common import RunState, check, emit, finish, invoice, store
from app.prompts import PROMPTS
from app.schemas import RiskAssessment

AGENT = "risk-scoring"


def _history_view(profile: dict, amount: float | None) -> dict:
    view = {"known_vendor": profile["known"], "vendor_master_name": profile.get("display_name"), "first_seen": profile.get("first_seen"),
            "historical_payment_count": profile.get("award_count", 0)}
    if profile.get("average_amount_cents"):
        average = profile["average_amount_cents"] / 100
        view["historical_average_amount"] = round(average, 2)
        view["recent_amounts"] = [a / 100 for a in profile.get("recent_amounts_cents", [])]
        if amount:
            view["invoice_amount_to_average_ratio"] = round(amount / average, 2)
    return view


async def risk_node(state: RunState) -> dict:
    thread_id, fields = state["thread_id"], state["fields"]
    await governance.heartbeat(thread_id, AGENT)
    await store().update(thread_id, "working", "scoring")
    if not await check(state, AGENT, "ScoreRisk", invoice(state)):
        return await finish(state, AGENT, "rejected", "blocked_policy", "risk scoring not authorized")
    for asset in ("vendors", "historical_payments"):
        if not await check(state, AGENT, "ReadData", {"type": "DataAsset", "id": asset}):
            return await finish(state, AGENT, "rejected", "blocked_policy", f"read of {asset} not authorized")

    profile = await ledger_client.vendor_lookup(fields.get("vendor_name") or "UNKNOWN VENDOR", agent=AGENT)
    history = _history_view(profile, fields.get("total_amount"))
    await emit(state, AGENT, "vendor_history", history)

    await governance.heartbeat(thread_id, AGENT)
    evidence = json.dumps({"invoice": fields, "vendor_history": history}, default=str)
    risk, usage = await llm.structured(base_url=config.LITELLM_URL, key=config.LITELLM_KEYS[AGENT], agent=AGENT, route="custodian-reasoning",
                                       response_model=RiskAssessment, system=PROMPTS["risk"]["text"], user=evidence)
    record = {**risk.model_dump(), "vendor_history": history, "llm": usage}
    await governance.audit("risk_score", AGENT, record, thread_id)
    await emit(state, AGENT, "risk", record)
    await store().update(thread_id, "working", "scored", {"risk_score": risk.risk_score})
    return {"vendor": profile, "risk": risk.model_dump(), "stage": "scored"}
