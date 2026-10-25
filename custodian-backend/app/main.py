"""custodian-backend: hosts the LangGraph agent pipeline behind a REST + WebSocket API."""
from app import identity  # noqa: I001 - must stay first: no workload identity, no process

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel, Field

from app import auth, config, governance, graph, ledger_client, prompts, telemetry
from app.agents.common import RAW_IMAGES, RAW_TEXT, STORE
from app.runs import RunStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("backend")
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_TEXT_CHARS = 50_000

app_pool = AsyncConnectionPool(config.CUSTODIAN_DB_URL, min_size=1, max_size=10, open=False)
checkpoint_pool = AsyncConnectionPool(config.CUSTODIAN_DB_URL, min_size=1, max_size=5, open=False,
                                      kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row})
state: dict = {"tasks": set()}


@asynccontextmanager
async def lifespan(_: FastAPI):
    log.info("workload identity %s", identity.SPIFFE_ID)
    telemetry.setup("custodian-backend", config.LANGFUSE_URL, config.LANGFUSE_PUBLIC_KEY, config.LANGFUSE_SECRET_KEY)
    prompts.load_all()
    await app_pool.open(wait=True)
    await checkpoint_pool.open(wait=True)
    STORE["runs"] = RunStore(app_pool)
    await STORE["runs"].setup()
    checkpointer = AsyncPostgresSaver(checkpoint_pool)
    await checkpointer.setup()
    state["graph"] = graph.build(checkpointer)
    yield
    await checkpoint_pool.close()
    await app_pool.close()


app = FastAPI(title="custodian-backend", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"])


async def _drive(thread_id: str, payload) -> None:
    try:
        await state["graph"].ainvoke(payload, {"configurable": {"thread_id": thread_id}})
    except Exception as exc:
        log.exception("run %s failed", thread_id)
        await STORE["runs"].update(thread_id, "failed", "failed", {"error": f"{exc.__class__.__name__}: {str(exc)[:500]}"})
        await STORE["runs"].event(thread_id, "pipeline", "error", {"error": f"{exc.__class__.__name__}: {str(exc)[:1000]}"})
        await governance.heartbeat(thread_id, "pipeline", "finished")


def _spawn(thread_id: str, payload) -> None:
    task = asyncio.create_task(_drive(thread_id, payload))
    state["tasks"].add(task)
    task.add_done_callback(state["tasks"].discard)


class TextSubmission(BaseModel):
    ocr_text: str = Field(min_length=1, max_length=MAX_TEXT_CHARS)


class Decision(BaseModel):
    approved: bool
    comment: str = Field(default="", max_length=1000)


@app.post("/runs")
async def submit_text(body: TextSubmission) -> dict:
    thread_id = str(uuid.uuid4())
    RAW_TEXT[thread_id] = body.ocr_text
    await STORE["runs"].create(thread_id, "text")
    await governance.audit("run_submitted", "custodian-backend", {"source": "text", "chars": len(body.ocr_text)}, thread_id)
    _spawn(thread_id, {"thread_id": thread_id, "source": "text"})
    return {"thread_id": thread_id}


@app.post("/runs/image")
async def submit_image(file: UploadFile) -> dict:
    data = await file.read(MAX_IMAGE_BYTES + 1)
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(413, "image must be between 1 byte and 10MB")
    thread_id = str(uuid.uuid4())
    RAW_IMAGES[thread_id] = data
    await STORE["runs"].create(thread_id, "image")
    await governance.audit("run_submitted", "custodian-backend", {"source": "image", "bytes": len(data), "filename": file.filename}, thread_id)
    _spawn(thread_id, {"thread_id": thread_id, "source": "image"})
    return {"thread_id": thread_id}


@app.get("/runs")
async def list_runs(limit: int = Query(50, ge=1, le=500), task_state: str | None = None) -> list[dict]:
    return await STORE["runs"].list(limit, task_state)


@app.get("/approvals")
async def approvals() -> list[dict]:
    return await STORE["runs"].list(200, "input-required")


@app.get("/runs/{thread_id}")
async def get_run(thread_id: str) -> dict:
    run = await STORE["runs"].get(thread_id)
    if run is None:
        raise HTTPException(404, "no such run")
    return {**run, "events": await STORE["runs"].events(thread_id)}


@app.websocket("/runs/{thread_id}/ws")
async def run_stream(ws: WebSocket, thread_id: str) -> None:
    await ws.accept()
    last = 0
    try:
        while True:
            for event in await STORE["runs"].events(thread_id, last):
                last = event["id"]
                await ws.send_json({**event, "ts": event["ts"].isoformat()})
            run = await STORE["runs"].get(thread_id)
            if run:
                await ws.send_json({"kind": "run", "task_state": run["task_state"], "stage": run["stage"]})
            await asyncio.sleep(0.5)
    except WebSocketDisconnect:
        return


@app.post("/runs/{thread_id}/decision")
async def decide(thread_id: str, body: Decision, approver: dict = Depends(auth.user)) -> dict:
    run = await STORE["runs"].get(thread_id)
    if run is None:
        raise HTTPException(404, "no such run")
    if run["task_state"] != "input-required":
        raise HTTPException(409, f"run is {run['task_state']}, not awaiting a human decision")
    review = {"approved": body.approved, "approver": approver["username"], "role": approver["role"], "comment": body.comment}
    await STORE["runs"].update(thread_id, "working", "resuming")
    _spawn(thread_id, Command(resume=review))
    return {"thread_id": thread_id, "resumed_with": review}


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "identity": identity.current(), "prompts": {k: v["source"] for k, v in prompts.PROMPTS.items()}}


# ---- read-only views for the console (proxied so internal services stay off the host network) ----

@app.get("/ledger/accounts")
async def ledger_accounts() -> list:
    return await ledger_client.read("/accounts")


@app.get("/ledger/entries")
async def ledger_entries(limit: int = Query(50, ge=1, le=500)) -> list:
    return await ledger_client.read("/entries", {"limit": limit})


@app.get("/audit/entries")
async def audit_entries(limit: int = Query(100, ge=1, le=1000), before: int | None = None, thread_id: str | None = None) -> list:
    params = {"limit": limit, **({"before": before} if before else {}), **({"thread_id": thread_id} if thread_id else {})}
    return (await governance.proxy_get(f"{config.AUDIT_LOG_URL}/entries", params)).json()


@app.get("/audit/verify")
async def audit_verify() -> dict:
    async with httpx.AsyncClient(timeout=120) as client:
        return (await client.get(f"{config.AUDIT_LOG_URL}/verify")).json()


@app.get("/policies")
async def policies() -> dict:
    return (await governance.proxy_get(f"{config.POLICY_SERVICE_URL}/policies")).json()


@app.get("/killswitch")
async def kill_switches() -> list:
    return (await governance.proxy_get(f"{config.CONTROL_PLANE_URL}/switches")).json()


@app.post("/killswitch/{operation}")
async def kill_switch_operation(operation: str, body: dict, operator: dict = Depends(auth.user)) -> dict:
    if operation not in ("trip", "reset"):
        raise HTTPException(404, "unknown operation")
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(f"{config.CONTROL_PLANE_URL}/{operation}", json=body, headers={"Authorization": f"Bearer {operator['token']}"})
    if resp.status_code >= 400:
        raise HTTPException(resp.status_code, resp.json().get("detail", resp.text))
    return resp.json()


@app.get("/costs")
async def costs() -> list[dict]:
    """Spend vs. the gateway-enforced daily cap, read with each agent's own key."""
    out = []
    async with httpx.AsyncClient(timeout=10) as client:
        for agent, key in config.LITELLM_KEYS.items():
            if not key:
                out.append({"agent": agent, "error": "no key configured"})
                continue
            resp = await client.get(f"{config.LITELLM_URL}/key/info", headers={"Authorization": f"Bearer {key}"})
            info = resp.json().get("info", {}) if resp.status_code == 200 else {}
            out.append({"agent": agent, "spend_usd": info.get("spend"), "max_budget_usd": info.get("max_budget"),
                        "budget_reset_at": info.get("budget_reset_at"), "models": info.get("models")})
    return out
