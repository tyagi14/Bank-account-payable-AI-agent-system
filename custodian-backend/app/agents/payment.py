"""Payment-Execution agent: authorize -> dry-run -> settlement hold -> fresh kill-switch check -> commit
-> record the settled payment into vendor history. Nothing after the final check re-checks anything."""
import asyncio
from datetime import UTC, datetime

from app import config, governance, ledger_client
from app.agents.common import RunState, check, emit, finish, invoice, store

AGENT = "payment-execution"
CASH, EXPENSE = "assets:operating-cash", "expense:vendor-payments"
HEARTBEAT_EVERY = 5


async def payment_node(state: RunState) -> dict:
    thread_id, vendor, amount = state["thread_id"], state["vendor"], state.get("amount_cents", 0)
    route = state.get("route", "human")
    await governance.heartbeat(thread_id, AGENT)
    await store().update(thread_id, "working", "paying")

    context = {"amountCents": amount, "vendor": vendor["normalized_name"], "approvalRoute": route}
    if not await check(state, AGENT, "ExecutePayment", invoice(state), context):
        return await finish(state, AGENT, "rejected", "blocked_policy", "payment not authorized")

    approver = state.get("human", {}).get("approver", "approval-agent")
    display = state["fields"].get("vendor_name") or vendor["normalized_name"]
    entry = {
        "idempotency_key": f"invoice:{thread_id}",
        "description": f"Payment to {display}",
        "postings": [{"account_id": EXPENSE, "amount_cents": amount}, {"account_id": CASH, "amount_cents": -amount}],
        "metadata": {"thread_id": thread_id, "vendor": vendor["normalized_name"], "route": route, "approver": approver},
    }
    dry = await ledger_client.dry_run(entry)
    await emit(state, AGENT, "dry_run", dry)
    if not dry["valid"]:
        await governance.audit("ledger_dry_run_rejected", AGENT, {"errors": dry["errors"], "amount_cents": amount}, thread_id)
        return await finish(state, AGENT, "rejected", "blocked_dry_run", "; ".join(dry["errors"]))

    hold = config.SETTLEMENT_HOLD_SECONDS
    await emit(state, AGENT, "hold", {"seconds": hold, "until": datetime.now(UTC).timestamp() + hold})
    for second in range(hold):
        if second % HEARTBEAT_EVERY == 0:
            await governance.heartbeat(thread_id, AGENT)
        await asyncio.sleep(1)

    blocked = await governance.kill_switch(AGENT, thread_id, "ExecutePayment")
    await emit(state, AGENT, "final_check", {"blocked_by": blocked})
    if blocked:
        await governance.audit("payment_blocked_after_hold", AGENT, {"blocked_by": blocked, "amount_cents": amount}, thread_id)
        return await finish(state, AGENT, "rejected", "blocked_kill_switch", "; ".join(blocked))

    result = await ledger_client.commit(entry)
    if not result["valid"]:
        await governance.audit("ledger_commit_rejected", AGENT, {"errors": result["errors"]}, thread_id)
        return await finish(state, AGENT, "rejected", "blocked_ledger", "; ".join(result["errors"]))
    await governance.audit("ledger_execution", AGENT, {"entry_id": result["entry_id"], "amount_cents": amount, "vendor": vendor["normalized_name"],
                                                       "balances": result["resulting_balances"]}, thread_id)

    profile = await ledger_client.record_payment({"vendor_name": display, "amount_cents": amount, "external_id": result["entry_id"],
                                                  "paid_on": datetime.now(UTC).date().isoformat()})
    await governance.audit("vendor_history_update", AGENT, {"vendor": profile["normalized_name"], "award_count": profile["award_count"],
                                                            "average_amount_cents": profile["average_amount_cents"]}, thread_id)
    await emit(state, AGENT, "settled", {"entry_id": result["entry_id"], "balances": result["resulting_balances"], "vendor_after": profile})
    outcome = await finish(state, AGENT, "completed", "settled", "payment settled", entry_id=result["entry_id"])
    return {**outcome, "payment": {"entry_id": result["entry_id"]}}
