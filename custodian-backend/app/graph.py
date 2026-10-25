"""Extraction -> Risk-Scoring -> Approval -> [human interrupt] -> Payment-Execution, checkpointed in Postgres."""
from langgraph.graph import END, START, StateGraph

from app.agents.approval import approval_node
from app.agents.common import RunState
from app.agents.extraction import extraction_node
from app.agents.human import human_node
from app.agents.payment import payment_node
from app.agents.risk import risk_node


def _after(stage: str, next_node: str):
    return lambda state: next_node if state.get("stage") == stage else END


def _after_approval(state: RunState) -> str:
    return {"approved": "payment_execution", "escalated": "human_review"}.get(state.get("stage"), END)


def build(checkpointer):
    graph = StateGraph(RunState)
    graph.add_node("extraction", extraction_node)
    graph.add_node("risk_scoring", risk_node)
    graph.add_node("approval", approval_node)
    graph.add_node("human_review", human_node)
    graph.add_node("payment_execution", payment_node)
    graph.add_edge(START, "extraction")
    graph.add_conditional_edges("extraction", _after("extracted", "risk_scoring"), ["risk_scoring", END])
    graph.add_conditional_edges("risk_scoring", _after("scored", "approval"), ["approval", END])
    graph.add_conditional_edges("approval", _after_approval, ["payment_execution", "human_review", END])
    graph.add_conditional_edges("human_review", _after("approved", "payment_execution"), ["payment_execution", END])
    graph.add_edge("payment_execution", END)
    return graph.compile(checkpointer=checkpointer)
