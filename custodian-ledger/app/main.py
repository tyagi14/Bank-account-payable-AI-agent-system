"""custodian-ledger: an internal double-entry settlement ledger.

This is the sandboxed settlement layer a fintech runs before connecting to a real payment rail:
genuine bookkeeping and validation, with no external bank network behind it.
"""
import hmac
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest
from psycopg_pool import AsyncConnectionPool

from app import vendors
from app.ledger import EntryRequest, EntryResult, apply_entry
from app.infisical import load_api_keys

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("ledger")

ENTRIES = Counter("ledger_entries_total", "Ledger entry attempts", ["mode", "result"])
pool = AsyncConnectionPool(os.environ["LEDGER_DB_URL"], min_size=1, max_size=10, open=False)
keys: dict[str, str] = {}


@asynccontextmanager
async def lifespan(_: FastAPI):
    keys["write"], keys["lookup"] = load_api_keys()
    log.info("loaded ledger write key and vendor lookup key from Infisical")
    await pool.open(wait=True)
    async with pool.connection() as conn:
        await conn.execute(Path("schema.sql").read_text())
    yield
    await pool.close()


app = FastAPI(title="custodian-ledger", lifespan=lifespan)


def _matches(supplied: str | None, *expected: str) -> bool:
    return supplied is not None and any(hmac.compare_digest(supplied, e) for e in expected)


def require_write(x_api_key: str | None = Header(default=None)) -> None:
    if not _matches(x_api_key, keys["write"]):
        raise HTTPException(401, "ledger write key required")


def require_read(x_api_key: str | None = Header(default=None)) -> None:
    if not _matches(x_api_key, keys["write"], keys["lookup"]):
        raise HTTPException(401, "ledger read or vendor lookup key required")


@app.get("/health")
async def health() -> dict:
    async with pool.connection() as conn:
        await conn.execute("SELECT 1")
    return {"status": "ok"}


@app.get("/metrics")
def metrics() -> PlainTextResponse:
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


async def _post(entry: EntryRequest, commit: bool) -> EntryResult:
    async with pool.connection() as conn:
        result = await apply_entry(conn, entry, commit=commit)
    mode = "commit" if commit else "dry_run"
    ENTRIES.labels(mode, "valid" if result.valid else "invalid").inc()
    log.info("%s idempotency_key=%s valid=%s errors=%s", mode, entry.idempotency_key, result.valid, result.errors)
    return result


@app.post("/entries/dry-run", dependencies=[Depends(require_write)])
async def dry_run(entry: EntryRequest) -> EntryResult:
    return await _post(entry, commit=False)


@app.post("/entries", dependencies=[Depends(require_write)])
async def commit(entry: EntryRequest) -> EntryResult:
    result = await _post(entry, commit=True)
    if not result.valid:
        raise HTTPException(422, result.model_dump())
    return result


@app.get("/accounts", dependencies=[Depends(require_read)])
async def accounts() -> list[dict]:
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute("""SELECT a.id, a.kind, COALESCE(SUM(p.amount_cents), 0) FROM accounts a
                             LEFT JOIN postings p ON p.account_id = a.id GROUP BY a.id, a.kind ORDER BY a.id""")
        return [{"id": r[0], "kind": r[1], "balance_cents": int(r[2])} for r in await cur.fetchall()]


@app.get("/entries", dependencies=[Depends(require_read)])
async def entries(limit: int = Query(50, ge=1, le=500)) -> list[dict]:
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute("""SELECT e.id, e.idempotency_key, e.description, e.metadata, e.created_at,
                                    json_agg(json_build_object('account_id', p.account_id, 'amount_cents', p.amount_cents) ORDER BY p.id)
                             FROM journal_entries e JOIN postings p ON p.entry_id = e.id
                             GROUP BY e.id ORDER BY e.created_at DESC LIMIT %s""", (limit,))
        return [{"id": str(r[0]), "idempotency_key": r[1], "description": r[2], "metadata": r[3], "created_at": r[4].isoformat(), "postings": r[5]}
                for r in await cur.fetchall()]


@app.get("/vendors/lookup", dependencies=[Depends(require_read)])
async def vendor_lookup(name: str = Query(min_length=1, max_length=300)) -> vendors.VendorProfile:
    async with pool.connection() as conn:
        return await vendors.lookup(conn, name)


@app.post("/vendors/record-payment", dependencies=[Depends(require_write)])
async def record_payment(record: vendors.PaymentRecord) -> vendors.VendorProfile:
    async with pool.connection() as conn:
        profile = await vendors.record_payment(conn, record)
    log.info("recorded settled payment vendor=%s amount_cents=%s", profile.normalized_name, record.amount_cents)
    return profile
