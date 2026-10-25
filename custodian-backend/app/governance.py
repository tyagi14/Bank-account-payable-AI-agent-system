"""Calls into the governance services: policy decisions, heartbeats, audit events, kill-switch state."""
import logging

import httpx

from app import config, identity, manifests

log = logging.getLogger("governance")
_http = httpx.AsyncClient(timeout=10)


class Denied(PermissionError):
    def __init__(self, action: str, reasons: list[str]):
        super().__init__(f"{action} denied: {reasons}")
        self.action, self.reasons = action, reasons


async def authorize(agent: str, action: str, resource: dict, context: dict | None = None, thread_id: str | None = None,
                    principal: dict | None = None) -> dict:
    """Both checks must pass: the agent's capability manifest (in-process) and the policy service (Cedar,
    temporal rules, kill switch). A human principal skips the manifest; its authority is its Keycloak role."""
    identity.current()  # an expired workload identity stops all consequential actions
    if principal is None:
        try:
            manifests.require(agent, action)
        except manifests.CapabilityError as exc:
            return {"decision": "deny", "reasons": [f"manifest: {exc}"], "checks": {"manifest": "deny"}}
        principal = {"type": "Agent", "id": agent}
    try:
        resp = await _http.post(f"{config.POLICY_SERVICE_URL}/authorize", json={
            "principal": principal, "action": action, "resource": resource, "context": context or {}, "thread_id": thread_id})
        resp.raise_for_status()
        result = resp.json()
    except httpx.HTTPError as exc:
        return {"decision": "deny", "reasons": [f"policy service unavailable ({exc.__class__.__name__}); default deny"], "checks": {}}
    result["checks"] = {"manifest": "allow" if principal["type"] == "Agent" else "n/a", **result.get("checks", {})}
    return result


async def kill_switch(agent: str, thread_id: str, tool: str) -> list[str]:
    try:
        resp = await _http.get(f"{config.CONTROL_PLANE_URL}/check", params={"agent": agent, "thread": thread_id, "tool": tool})
        resp.raise_for_status()
        return resp.json()["blocked_by"]
    except httpx.HTTPError as exc:
        return [f"control plane unavailable ({exc.__class__.__name__}); failing closed"]


async def heartbeat(thread_id: str, agent: str, phase: str = "active") -> None:
    try:
        await _http.post(f"{config.CONTROL_PLANE_URL}/heartbeats", json={"thread_id": thread_id, "agent": agent, "phase": phase})
    except httpx.HTTPError as exc:
        log.warning("heartbeat failed for %s/%s: %s", thread_id, agent, exc)


async def audit(event_type: str, actor: str, payload: dict, thread_id: str | None = None) -> None:
    try:
        (await _http.post(f"{config.AUDIT_LOG_URL}/events",
                          json={"event_type": event_type, "actor": actor, "thread_id": thread_id, "payload": payload})).raise_for_status()
    except httpx.HTTPError as exc:
        log.error("audit append failed for %s: %s", event_type, exc)
        raise


async def proxy_get(url: str, params: dict | None = None) -> httpx.Response:
    return await _http.get(url, params=params)
