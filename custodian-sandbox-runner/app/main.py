"""custodian-sandbox-runner: runs every OCR job in a fresh, locked-down, single-use container."""
import json
import logging
import os
import subprocess
import time
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("sandbox-runner")

IMAGE = os.environ.get("SANDBOX_IMAGE", "custodian/sandbox-ocr:local")
TIMEOUT_SECONDS = int(os.environ.get("SANDBOX_TIMEOUT_SECONDS", "60"))
MAX_BYTES = 10 * 1024 * 1024
RUNS = Counter("sandbox_runs_total", "Sandboxed OCR executions", ["result"])

SANDBOX_FLAGS = [
    "--rm", "-i",
    "--network", "none",
    "--read-only",
    "--tmpfs", "/scratch:rw,size=64m,uid=10001,gid=10001,mode=0700",
    "--user", "10001:10001",
    "--cap-drop", "ALL",
    "--security-opt", "no-new-privileges",
    "--cpus", "1", "--memory", "512m", "--memory-swap", "512m", "--pids-limit", "64",
]

app = FastAPI(title="custodian-sandbox-runner")


def run_sandbox(image_bytes: bytes, probe: bool) -> dict:
    name = f"sandbox-ocr-{uuid.uuid4().hex[:12]}"
    cmd = ["docker", "run", "--name", name, *SANDBOX_FLAGS, IMAGE, *(["--probe"] if probe else [])]
    started = time.monotonic()
    try:
        proc = subprocess.run(cmd, input=image_bytes, capture_output=True, timeout=TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        subprocess.run(["docker", "kill", name], capture_output=True)
        RUNS.labels("timeout").inc()
        raise HTTPException(504, f"sandbox exceeded {TIMEOUT_SECONDS}s and was killed")
    elapsed = int((time.monotonic() - started) * 1000)
    try:
        result = json.loads(proc.stdout.decode().strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        RUNS.labels("error").inc()
        raise HTTPException(502, f"sandbox failed (exit {proc.returncode}): {proc.stderr.decode()[-300:]}")
    if "error" in result or proc.returncode != 0:
        RUNS.labels("rejected").inc()
        raise HTTPException(422, result.get("error") or result.get("stderr", "ocr failed"))
    RUNS.labels("ok").inc()
    log.info("container %s finished in %dms (%d chars)", name, elapsed, len(result["text"]))
    return {**result, "container": name, "total_ms": elapsed, "isolation": {"flags": SANDBOX_FLAGS, "image": IMAGE}}


@app.post("/ocr")
async def ocr(request: Request, probe: bool = False) -> dict:
    body = await request.body()
    if not body or len(body) > MAX_BYTES:
        raise HTTPException(413, "image must be between 1 byte and 10MB")
    return await run_in_threadpool(run_sandbox, body, probe)


@app.get("/health")
def health() -> dict:
    if subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True).returncode != 0:
        raise HTTPException(503, f"sandbox image {IMAGE} not built (docker build -t {IMAGE} custodian-sandbox-ocr)")
    return {"status": "ok", "image": IMAGE}


@app.get("/metrics")
def metrics() -> PlainTextResponse:
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)
