"""Shared plumbing for the agent nodes: run events, policy checks and terminal outcomes."""
from typing import TypedDict

from app import governance
from app.runs import RunStore, TaskState


class RunState(TypedDict, total=False):
    thread_id: str
    source: str
    fields: dict
    vendor: dict
    risk: dict
    decision: dict
    critic: dict
    route: str
    escalation_reasons: list[str]
    amount_cents: int
    human: dict
    payment: dict
    stage: str
    task_state: str


# Raw document content stays in process memory only: graph checkpoints are durable storage,
# so they hold the redacted text and extracted fields, never the raw OCR text or image.
RAW_TEXT: dict[str, str] = {}
RAW_IMAGES: dict[str, bytes] = {}
STORE: dict[str, RunStore] = {}


def store() -> RunStore:
    return STORE["runs"]


def invoice(state: RunState) -> dict:
    return {"type": "Invoice", "id": state["thread_id"]}


async def emit(state: RunState, agent: str, kind: str, detail: dict) -> None:
    await store().event(state["thread_id"], agent, kind, detail)


async def check(state: RunState, agent: str, action: str, resource: dict, context: dict | None = None, principal: dict | None = None) -> bool:
    """Re-authorizes at every step instead of trusting the previous node's outcome."""
    result = await governance.authorize(agent, action, resource, context, state["thread_id"], principal)
    await emit(state, agent, "policy", {"action": action, "resource": resource, "decision": result["decision"],
                                        "reasons": result.get("reasons", []), "checks": result.get("checks", {})})
    return result["decision"] == "allow"


async def finish(state: RunState, agent: str, task_state: TaskState, stage: str, reason: str, **extra) -> dict:
    await store().update(state["thread_id"], task_state, stage, {"outcome": reason, **extra})
    await emit(state, agent, "outcome", {"task_state": task_state, "stage": stage, "reason": reason})
    await governance.heartbeat(state["thread_id"], agent, "finished")
    return {"task_state": task_state, "stage": stage}
