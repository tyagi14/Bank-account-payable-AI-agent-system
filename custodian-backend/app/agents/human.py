"""Human-in-the-loop gate: pauses the graph with LangGraph's interrupt() until an approver decides."""
from langgraph.types import interrupt

from app import governance
from app.agents.common import RunState, check, emit, finish, invoice, store

AGENT = "human-review"


async def human_node(state: RunState) -> dict:
    thread_id = state["thread_id"]
    await store().update(thread_id, "input-required", "pending_human", {"escalation_reasons": state.get("escalation_reasons", []),
                                                                         "amount_cents": state.get("amount_cents")})
    await governance.heartbeat(thread_id, AGENT, "waiting_human")
    # Execution stops here until /runs/{id}/decision resumes it with Command(resume=...).
    review = interrupt({"thread_id": thread_id, "escalation_reasons": state.get("escalation_reasons", [])})

    await governance.heartbeat(thread_id, AGENT)
    await emit(state, AGENT, "human_decision", review)
    if not review["approved"]:
        await governance.audit("human_denial", review["approver"], review, thread_id)
        return await finish(state, AGENT, "rejected", "denied_by_human", review.get("comment") or "denied by approver")

    principal = {"type": "Human", "id": review["approver"], "role": review["role"]}
    context = {"amountCents": state.get("amount_cents", 0), "vendor": state["vendor"]["normalized_name"], "vendorKnown": state["vendor"]["known"]}
    allowed = await check(state, AGENT, "HumanApproveInvoice", invoice(state), context, principal=principal)
    await governance.audit("human_approval", review["approver"], {**review, "authorized": allowed}, thread_id)
    if not allowed:
        return await finish(state, AGENT, "rejected", "blocked_policy", f"{review['role']} {review['approver']} may not approve this invoice")
    return {"human": review, "stage": "approved"}
