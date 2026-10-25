"""Rejects Cedar permits that are overly permissive. Shared by /reload and validate-cedar-policies.py."""
import json

import cedarpy

MONEY_ACTIONS = {"AutoApproveInvoice", "HumanApproveInvoice", "ExecutePayment"}


def _mentions(node, needle: str) -> bool:
    return needle in json.dumps(node)


def lint(policy_text: str, ids: dict[str, str] | None = None) -> list[str]:
    problems = []
    for pid, policy in json.loads(cedarpy.policies_to_json_str(policy_text))["staticPolicies"].items():
        if policy["effect"] != "permit":
            continue
        name = (policy.get("annotations") or {}).get("id", pid)
        conditions = policy.get("conditions", [])
        action = policy["action"]
        principal_constrained = policy["principal"]["op"] != "All" or _mentions(conditions, '"Var": "principal"') or _mentions(conditions, '"Var":"principal"')
        if action["op"] == "All":
            problems.append(f"{name}: permit applies to every action")
        if policy["principal"]["op"] == "All" and policy["resource"]["op"] == "All" and not conditions:
            problems.append(f"{name}: unconstrained permit (no principal, resource or condition)")
        actions = {action["entity"]["id"]} if action["op"] == "==" else {e["id"] for e in action.get("entities", [])}
        if action["op"] == "All" or actions & MONEY_ACTIONS:
            if not principal_constrained:
                problems.append(f"{name}: money-moving permit without a principal constraint")
            if not _mentions(conditions, "amountCents"):
                problems.append(f"{name}: money-moving permit without an amount constraint")
    return problems
