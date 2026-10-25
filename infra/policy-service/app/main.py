"""policy-service: the Policy Decision Point. Default deny; Cedar + temporal rules + live kill-switch state.

Every decision, allow or deny, is recorded in policy_decisions, appended to the audit log, and
counted in policy_decisions_total.
"""
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel, Field

from app import cedar_engine, temporal

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("policy-service")

POLICY_DIR = Path(os.environ.get("POLICY_DIR", "/policies"))
CONTROL_PLANE_URL = os.environ["CONTROL_PLANE_URL"]
AUDIT_LOG_URL = os.environ["AUDIT_LOG_URL"]

DECISIONS = Counter("policy_decisions_total", "Authorization decisions", ["action", "decision", "principal"])
pool = AsyncConnectionPool(os.environ["CUSTODIAN_DB_URL"], min_size=1, max_size=10, open=False)
state: dict = {}

SCHEMA = """
CREATE TABLE IF NOT EXISTS policy_decisions (
    id bigserial PRIMARY KEY,
    ts timestamptz NOT NULL DEFAULT now(),
    principal text NOT NULL,
    action text NOT NULL,
    resource text NOT NULL,
    vendor text,
    thread_id text,
    decision text NOT NULL CHECK (decision IN ('allow', 'deny')),
    reasons jsonb NOT NULL,
    context jsonb NOT NULL
);
ALTER TABLE policy_decisions ADD COLUMN IF NOT EXISTS checks jsonb;
CREATE INDEX IF NOT EXISTS policy_decisions_vendor_idx ON policy_decisions (vendor, action, ts);
CREATE INDEX IF NOT EXISTS policy_decisions_principal_idx ON policy_decisions (principal, decision, ts);
"""


def load_policies() -> None:
    state["cedar"] = cedar_engine.load(POLICY_DIR)
    state["temporal"] = temporal.load_rules(POLICY_DIR / "temporal")
    log.info("loaded %d cedar policies and %d temporal rules", len(state["cedar"].ids), len(state["temporal"]))


@asynccontextmanager
async def lifespan(_: FastAPI):
    load_policies()
    await pool.open(wait=True)
    async with pool.connection() as conn:
        await conn.execute(SCHEMA)
    state["http"] = httpx.AsyncClient(timeout=5)
    yield
    await state["http"].aclose()
    await pool.close()


app = FastAPI(title="policy-service", lifespan=lifespan)


class Principal(BaseModel):
    type: Literal["Agent", "Human"]
    id: str = Field(min_length=1, max_length=200)
    role: str | None = None  # Human only; the backend sets it from a verified Keycloak token


class Resource(BaseModel):
    type: Literal["Invoice", "Tool", "DataAsset"]
    id: str = Field(min_length=1, max_length=200)


class AuthorizeRequest(BaseModel):
    principal: Principal
    action: str = Field(min_length=1, max_length=100)
    resource: Resource
    context: dict = Field(default_factory=dict)
    thread_id: str | None = None


class AuthorizeResponse(BaseModel):
    decision: Literal["allow", "deny"]
    reasons: list[str]
    checks: dict[str, str]


async def kill_switch_blocks(req: AuthorizeRequest) -> list[str]:
    params = {"tool": req.action}
    if req.principal.type == "Agent":
        params["agent"] = req.principal.id
    if req.thread_id:
        params["thread"] = req.thread_id
    try:
        resp = await state["http"].get(f"{CONTROL_PLANE_URL}/check", params=params)
        resp.raise_for_status()
        return [f"kill switch: {s}" for s in resp.json()["blocked_by"]]
    except httpx.HTTPError as exc:
        return [f"kill switch state unavailable ({exc.__class__.__name__}); failing closed"]


async def append_audit(event: dict) -> bool:
    try:
        resp = await state["http"].post(f"{AUDIT_LOG_URL}/events", json=event)
        resp.raise_for_status()
        return True
    except httpx.HTTPError as exc:
        log.error("audit append failed: %s", exc)
        return False


@app.post("/authorize")
async def authorize(req: AuthorizeRequest) -> AuthorizeResponse:
    principal = f"{req.principal.type}::{req.principal.id}"
    vendor = req.context.get("vendor")
    checks, reasons = {}, []

    blocked = await kill_switch_blocks(req)
    checks["kill_switch"] = "blocked" if blocked else "clear"
    reasons += blocked

    try:
        allowed, matched, errors = cedar_engine.authorize(state["cedar"], req.principal.model_dump(), req.action, req.resource.model_dump(), req.context)
    except Exception as exc:  # malformed request/context: deny, never 500 into an allow
        allowed, matched, errors = False, [], [f"cedar evaluation error: {exc}"]
    checks["cedar"] = "allow" if allowed else "deny"
    reasons += [f"cedar: {m}" for m in matched] + errors
    if not allowed and not matched and not errors:
        reasons.append("cedar: no permit policy matched (default deny)")

    async with pool.connection() as conn, conn.transaction():
        ok, violations = await temporal.check(conn, state["temporal"], req.action, vendor)
        checks["temporal"] = "allow" if ok else "deny"
        reasons += [f"temporal: {v}" for v in violations]
        decision = "allow" if (allowed and ok and not blocked) else "deny"

        audited = await append_audit({"event_type": "policy_decision", "actor": principal, "thread_id": req.thread_id, "payload": {
            "action": req.action, "resource": f"{req.resource.type}::{req.resource.id}", "decision": decision,
            "reasons": reasons, "checks": checks, "context": req.context}})
        if not audited and decision == "allow":
            decision = "deny"
            reasons.append("audit log unavailable; an unaudited allow is not permitted")
        await conn.execute(
            "INSERT INTO policy_decisions (principal, action, resource, vendor, thread_id, decision, reasons, checks, context) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (principal, req.action, f"{req.resource.type}::{req.resource.id}", vendor, req.thread_id, decision, Jsonb(reasons), Jsonb(checks), Jsonb(req.context)))

    DECISIONS.labels(req.action, decision, principal).inc()
    log.info("%s %s %s -> %s %s", principal, req.action, req.resource.id, decision, reasons)
    return AuthorizeResponse(decision=decision, reasons=reasons, checks=checks)


@app.post("/reload")
def reload() -> dict:
    try:
        load_policies()
    except Exception as exc:  # keep serving the last good policy set
        raise HTTPException(422, f"reload rejected, previous policies still active: {exc}") from exc
    return {"cedar_policies": list(state["cedar"].ids.values()), "temporal_rules": [r.rule_id for r in state["temporal"]]}


@app.get("/policies")
def policies() -> dict:
    temporal_dir = POLICY_DIR / "temporal"
    return {
        "cedar": state["cedar"].sources,
        "temporal": {p.name: p.read_text() for p in sorted(temporal_dir.glob("*.dw"))},
        "temporal_enforced": [r.__dict__ for r in state["temporal"]],
        "entities": state["cedar"].entities,
    }


@app.get("/health")
async def health() -> dict:
    async with pool.connection() as conn:
        await conn.execute("SELECT 1")
    return {"status": "ok", "policies": len(state["cedar"].ids)}


@app.get("/metrics")
def metrics() -> PlainTextResponse:
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)
