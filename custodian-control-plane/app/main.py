"""custodian-control-plane: the kill switch, run outside the agent runtime so a malfunctioning agent
can never be the one deciding whether it gets stopped."""
import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Literal

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel, Field

from app import store, watchdog
from app.auth import require_operator

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("control-plane")

AUDIT_LOG_URL = os.environ["AUDIT_LOG_URL"]
CANARY_VENDORS = [v.strip() for v in os.environ.get("CANARY_VENDORS", "").split(",") if v.strip()]
DENIAL_TRIP_COUNT = int(os.environ.get("DENIAL_TRIP_COUNT", "5"))
DENIAL_TRIP_WINDOW_SECONDS = int(os.environ.get("DENIAL_TRIP_WINDOW_SECONDS", "600"))
HEARTBEAT_STALE_SECONDS = int(os.environ.get("HEARTBEAT_STALE_SECONDS", "180"))
WATCHDOG_INTERVAL_SECONDS = int(os.environ.get("WATCHDOG_INTERVAL_SECONDS", "15"))

TRIPS = Counter("kill_switch_trips_total", "Kill-switch trips", ["scope", "trigger"])
RESETS = Counter("kill_switch_resets_total", "Kill-switch resets", ["scope"])
pool = AsyncConnectionPool(os.environ["CUSTODIAN_DB_URL"], min_size=1, max_size=5, open=False)
http = httpx.AsyncClient(timeout=5)


async def audit(event_type: str, actor: str, payload: dict, thread_id: str | None = None) -> None:
    try:
        (await http.post(f"{AUDIT_LOG_URL}/events", json={"event_type": event_type, "actor": actor, "thread_id": thread_id, "payload": payload})).raise_for_status()
    except httpx.HTTPError as exc:
        log.error("audit append failed for %s: %s", event_type, exc)


async def do_trip(scope: str, target: str, reason: str, trigger: str, by: str) -> dict | None:
    async with pool.connection() as conn:
        switch = await store.trip(conn, scope, target, reason, trigger, by)
    if switch:
        TRIPS.labels(scope, trigger).inc()
        log.warning("TRIPPED %s %s by %s (%s): %s", scope, target, by, trigger, reason)
        await audit("kill_switch_trip", by, {k: str(v) for k, v in switch.items()}, thread_id=target if scope == "thread" else None)
    return switch


async def watchdog_loop() -> None:
    while True:
        try:
            async with pool.connection() as conn:
                hits = await watchdog.canary_hits(conn, CANARY_VENDORS) if CANARY_VENDORS else []
                offenders = await watchdog.denial_offenders(conn, DENIAL_TRIP_COUNT, DENIAL_TRIP_WINDOW_SECONDS)
                stale = await watchdog.stale_threads(conn, HEARTBEAT_STALE_SECONDS)
            if hits:
                await do_trip("global", "*", "; ".join(hits), "canary", "control-plane-watchdog")
            for agent, count in offenders:
                await do_trip("agent", agent, f"{count} policy denials in {DENIAL_TRIP_WINDOW_SECONDS}s", "repeated_denials", "control-plane-watchdog")
            for thread_id, agent, age in stale:
                await do_trip("thread", thread_id, f"no heartbeat for {age:.0f}s (last from {agent})", "missed_heartbeat", "control-plane-watchdog")
        except Exception:
            log.exception("watchdog iteration failed")
        await asyncio.sleep(WATCHDOG_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await pool.open(wait=True)
    async with pool.connection() as conn:
        await conn.execute(store.SCHEMA)
    task = asyncio.create_task(watchdog_loop())
    yield
    task.cancel()
    await http.aclose()
    await pool.close()


app = FastAPI(title="custodian-control-plane", lifespan=lifespan)

Scope = Literal["agent", "thread", "tool", "global"]


class SwitchRequest(BaseModel):
    scope: Scope
    target: str = Field(default="*", max_length=200)
    reason: str = Field(default="manual", max_length=500)


class Heartbeat(BaseModel):
    thread_id: str = Field(min_length=1, max_length=200)
    agent: str = Field(min_length=1, max_length=100)
    phase: Literal["active", "waiting_human", "finished"] = "active"


def _target(req: SwitchRequest) -> str:
    if req.scope == "global":
        return "*"
    if req.target in ("", "*"):
        raise HTTPException(422, f"scope {req.scope} needs a target")
    return req.target


@app.get("/check")
async def check(agent: str | None = None, thread: str | None = None, tool: str | None = None) -> dict:
    async with pool.connection() as conn:
        return {"blocked_by": await store.blocking(conn, agent, thread, tool)}


@app.get("/switches")
async def switches(limit: int = Query(100, ge=1, le=1000)) -> list[dict]:
    async with pool.connection() as conn:
        return await store.history(conn, limit)


@app.post("/trip")
async def trip(req: SwitchRequest, operator: dict = Depends(require_operator)) -> dict:
    switch = await do_trip(req.scope, _target(req), req.reason, "manual", operator["username"])
    if switch is None:
        raise HTTPException(409, "already tripped")
    return switch


@app.post("/reset")
async def reset(req: SwitchRequest, operator: dict = Depends(require_operator)) -> dict:
    async with pool.connection() as conn:
        switch = await store.reset(conn, req.scope, _target(req), operator["username"])
    if switch is None:
        raise HTTPException(404, "no active switch for that scope/target")
    RESETS.labels(req.scope).inc()
    await audit("kill_switch_reset", operator["username"], {"scope": req.scope, "target": switch["target"], "tripped_reason": switch["reason"]})
    return switch


@app.post("/heartbeats", status_code=204)
async def heartbeat(hb: Heartbeat) -> None:
    async with pool.connection() as conn:
        await conn.execute("INSERT INTO heartbeats (thread_id, agent, phase) VALUES (%s, %s, %s)", (hb.thread_id, hb.agent, hb.phase))


@app.get("/health")
async def health() -> dict:
    async with pool.connection() as conn:
        await conn.execute("SELECT 1")
    return {"status": "ok"}


@app.get("/metrics")
def metrics() -> PlainTextResponse:
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)
