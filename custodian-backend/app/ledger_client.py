"""Ledger access for the Payment-Execution agent only. The write key is fetched from Infisical fresh,
immediately before each use, as the custodian-payment-execution identity."""
import httpx

from app import config, infisical, manifests

AGENT = "payment-execution"


async def _post(path: str, body: dict, agent: str) -> httpx.Response:
    manifests.require(agent, manifests.LEDGER_WRITE)
    key = await infisical.fetch("ledger-write")
    async with httpx.AsyncClient(timeout=15) as client:
        return await client.post(f"{config.LEDGER_URL}{path}", json=body, headers={"X-API-Key": key})


async def dry_run(entry: dict, agent: str = AGENT) -> dict:
    resp = await _post("/entries/dry-run", entry, agent)
    resp.raise_for_status()
    return resp.json()


async def commit(entry: dict, agent: str = AGENT) -> dict:
    resp = await _post("/entries", entry, agent)
    if resp.status_code == 422:
        return resp.json()["detail"]
    resp.raise_for_status()
    return resp.json()


async def record_payment(record: dict, agent: str = AGENT) -> dict:
    resp = await _post("/vendors/record-payment", record, agent)
    resp.raise_for_status()
    return resp.json()


async def read(path: str, params: dict | None = None) -> list | dict:
    """Read-only views for the console use the narrower vendor-lookup key."""
    key = await infisical.fetch("vendor-lookup")
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(f"{config.LEDGER_URL}{path}", params=params, headers={"X-API-Key": key})
    resp.raise_for_status()
    return resp.json()


async def vendor_lookup(name: str, agent: str = "risk-scoring") -> dict:
    manifests.require(agent, "vendor.lookup")
    return await read("/vendors/lookup", {"name": name})
