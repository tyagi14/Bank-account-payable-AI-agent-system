"""Approval agent: typed decision with its own confidence, a confidence gate, a cross-provider critic,
then Cedar (+ temporal rules) decides whether auto-approval is actually permitted."""
import json

from app import config, governance, llm
from app.agents.common import RunState, check, emit, finish, invoice, store
from app.prompts import PROMPTS
from app.schemas import ApprovalDecision, CriticVerdict

AGENT = "approval"
OTHER_PROVIDER = {"custodian-routine": "custodian-reasoning", "custodian-reasoning": "custodian-routine"}


def _cents(amount: float | None) -> int:
    return round(amount * 100) if amount and amount > 0 else 0


async def approval_node(state: RunState) -> dict:
    thread_id, fields, vendor, risk = state["thread_id"], state["fields"], state["vendor"], state["risk"]
    key = config.LITELLM_KEYS[AGENT]
    await governance.heartbeat(thread_id, AGENT)
    await store().update(thread_id, "working", "deciding")

    amount_cents = _cents(fields.get("total_amount"))
    route = "custodian-routine" if 0 < amount_cents <= config.ROUTINE_AMOUNT_CENTS else "custodian-reasoning"
    evidence = json.dumps({"invoice": fields, "amount_cents": amount_cents, "vendor_known": vendor["known"],
                           "vendor_history": {k: vendor.get(k) for k in ("first_seen", "award_count", "average_amount_cents", "recent_amounts_cents")},
                           "risk": risk}, default=str)
    decision, usage = await llm.structured(base_url=config.LITELLM_URL, key=key, agent=AGENT, route=route,
                                           response_model=ApprovalDecision, system=PROMPTS["approval"]["text"], user=evidence)
    await emit(state, AGENT, "decision", {**decision.model_dump(), "llm": usage})

    if decision.decision == "reject":
        await governance.audit("approval_decision", AGENT, {**decision.model_dump(), "route": "rejected"}, thread_id)
        return await finish(state, AGENT, "rejected", "rejected_by_agent", decision.rationale)

    reasons, critic, final_route = [], None, "human"
    if decision.decision == "escalate":
        reasons.append("approval agent escalated")
    elif decision.confidence < config.DECISION_CONFIDENCE_MIN:
        reasons.append(f"decision confidence {decision.confidence:.2f} is below {config.DECISION_CONFIDENCE_MIN}")
    else:
        await governance.heartbeat(thread_id, AGENT)
        critic_route = OTHER_PROVIDER[route]
        critic, usage = await llm.structured(base_url=config.LITELLM_URL, key=key, agent=f"{AGENT}-critic", route=critic_route,
                                             response_model=CriticVerdict, system=PROMPTS["critic"]["text"],
                                             user=json.dumps({"evidence": json.loads(evidence), "proposed_decision": decision.model_dump()}))
        await emit(state, AGENT, "critic", {**critic.model_dump(), "llm": usage})
        if not critic.agrees:
            reasons.append(f"critic ({critic_route}) disagreed: {'; '.join(critic.concerns)}")
        else:
            context = {"amountCents": amount_cents, "vendor": vendor["normalized_name"], "vendorKnown": vendor["known"],
                       "riskScoreBp": round(risk["risk_score"] * 10000), "decisionConfidenceBp": round(decision.confidence * 10000)}
            if await check(state, AGENT, "AutoApproveInvoice", invoice(state), context):
                final_route = "auto"
            else:
                reasons.append("policy did not permit auto-approval")

    await governance.audit("approval_decision", AGENT, {**decision.model_dump(), "critic": critic.model_dump() if critic else None,
                                                        "route": final_route, "escalation_reasons": reasons, "amount_cents": amount_cents}, thread_id)
    return {"decision": decision.model_dump(), "critic": critic.model_dump() if critic else None, "route": final_route,
            "escalation_reasons": reasons, "amount_cents": amount_cents, "stage": "approved" if final_route == "auto" else "escalated"}
