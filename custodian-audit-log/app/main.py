"""custodian-audit-log: append-only, hash-chained, WORM-anchored audit trail with a continuous integrity watchdog."""
import logging
import os
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import PlainTextResponse
from minio import Minio
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, generate_latest
from psycopg_pool import ConnectionPool
from pydantic import BaseModel, Field

from app import chain

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("audit-log")

WATCHDOG_INTERVAL = int(os.environ.get("AUDIT_WATCHDOG_INTERVAL_SECONDS", "30"))
APPENDS = Counter("audit_entries_appended_total", "Audit entries appended", ["event_type"])
INTACT = Gauge("audit_chain_intact", "1 if the last integrity check passed, else 0")

pool = ConnectionPool(os.environ["AUDIT_DB_URL"], min_size=1, max_size=10, open=False)
minio = Minio(os.environ.get("MINIO_ENDPOINT", "minio:9000"), os.environ["AUDIT_MINIO_USER"], os.environ["AUDIT_MINIO_PASSWORD"], secure=False)


def append(event_type: str, actor: str, thread_id: str | None, payload: dict) -> dict:
    with pool.connection() as conn:
        entry = chain.append(conn, minio, event_type, actor, thread_id, payload)
    APPENDS.labels(event_type).inc()
    return entry


def run_verify() -> dict:
    with pool.connection() as conn:
        result = chain.verify(conn, minio)
    INTACT.set(1 if result["valid"] else 0)
    return result


def watchdog() -> None:
    """Turns a point-in-time check into a permanent record: a break is written into the chain itself,
    so reverting the tampered data afterwards cannot erase the fact that it was caught. The in-memory
    flag only avoids re-logging the same break every tick; the durable memory is the chain."""
    broken = False
    while True:
        time.sleep(WATCHDOG_INTERVAL)
        try:
            result = run_verify()
            if not result["valid"] and not broken:
                broken = True
                findings = result["stage1_chain"] + result["stage2_worm"]
                log.error("TAMPER DETECTED: %s", findings)
                append("audit_log_tamper_detected", "audit-log-watchdog", None, {"findings": findings, "entries_checked": result["entries_checked"]})
            elif result["valid"] and broken:
                broken = False
                log.warning("audit chain intact again")
                append("audit_log_tamper_resolved", "audit-log-watchdog", None, {"entries_checked": result["entries_checked"]})
        except Exception:
            log.exception("integrity watchdog iteration failed")


@asynccontextmanager
async def lifespan(_: FastAPI):
    pool.open(wait=True)
    with pool.connection() as conn:
        conn.execute(chain.SCHEMA)
    if not minio.bucket_exists(chain.BUCKET):
        raise RuntimeError("audit-log bucket missing; run minio-init")
    threading.Thread(target=watchdog, name="integrity-watchdog", daemon=True).start()
    yield
    pool.close()


app = FastAPI(title="custodian-audit-log", lifespan=lifespan)


class Event(BaseModel):
    event_type: str = Field(min_length=1, max_length=100)
    actor: str = Field(min_length=1, max_length=200)
    thread_id: str | None = Field(default=None, max_length=200)
    payload: dict = Field(default_factory=dict)


@app.post("/events")
def post_event(event: Event) -> dict:
    entry = append(event.event_type, event.actor, event.thread_id, event.payload)
    return {"seq": entry["seq"], "entry_hash": entry["entry_hash"]}


@app.get("/verify")
def verify() -> dict:
    return run_verify()


@app.get("/entries")
def entries(limit: int = Query(100, ge=1, le=1000), before: int | None = None, thread_id: str | None = None) -> list[dict]:
    clauses, params = [], []
    if before is not None:
        clauses.append("seq < %s")
        params.append(before)
    if thread_id:
        clauses.append("thread_id = %s")
        params.append(thread_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with pool.connection() as conn:
        rows = conn.execute(f"SELECT seq, ts, event_type, actor, thread_id, payload, prev_hash, entry_hash, object_version FROM audit_entries {where} "
                            "ORDER BY seq DESC LIMIT %s", (*params, limit)).fetchall()
    cols = ["seq", "ts", "event_type", "actor", "thread_id", "payload", "prev_hash", "entry_hash", "object_version"]
    return [dict(zip(cols, r)) for r in rows]


@app.get("/entries/{seq}")
def entry(seq: int) -> dict:
    found = entries(limit=1, before=seq + 1)
    if not found or found[0]["seq"] != seq:
        raise HTTPException(404, "no such entry")
    return found[0]


@app.get("/health")
def health() -> dict:
    with pool.connection() as conn:
        conn.execute("SELECT 1")
    return {"status": "ok"}


@app.get("/metrics")
def metrics() -> PlainTextResponse:
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)
