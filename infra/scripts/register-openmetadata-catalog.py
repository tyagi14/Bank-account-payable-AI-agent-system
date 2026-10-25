#!/usr/bin/env python3
"""Registers the loaded tables in OpenMetadata and tags each with its sensitivity classification.

Classifications come from policies/entities.json, the same file the Cedar policy service reads
for DataAsset attributes, so the catalog and the access-control engine cannot disagree.
Run after the data loader. Re-runnable (PUT = create or update). Stdlib only.
"""
import base64
import json
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OM = "http://localhost:18585/api/v1"
SERVICE = "custodian-postgres"
CLASSIFICATION = "CustodianSensitivity"
TYPE_MAP = {"text": "TEXT", "bigint": "BIGINT", "integer": "INT", "numeric": "NUMERIC", "boolean": "BOOLEAN", "jsonb": "JSON",
            "timestamp with time zone": "TIMESTAMP", "date": "DATE", "uuid": "UUID"}
TAG_DESCRIPTIONS = {
    "public": "Derived from public sources; no access restriction beyond authentication",
    "internal": "Internal business data; may contain personal data from inbound documents",
    "RestrictedFinancial": "Payment and ledger data; readable only by agents cleared for financial records",
}


def api(method: str, path: str, body: dict | None = None, token: str | None = None) -> dict:
    req = urllib.request.Request(OM + path, method=method, data=json.dumps(body).encode() if body is not None else None)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as err:
        raise RuntimeError(f"{method} {path} -> {err.code}: {err.read().decode()[:400]}") from None


def columns(database: str, table: str) -> list[dict]:
    sql = f"SELECT column_name, data_type FROM information_schema.columns WHERE table_name = '{table}' ORDER BY ordinal_position"
    out = subprocess.run([str(ROOT / "infra/scripts/layer.sh"), "base", "exec", "-T", "postgres", "psql", "-U", "postgres", "-d", database, "-At", "-F", "|", "-c", sql],
                         check=True, capture_output=True, text=True).stdout
    cols = []
    for line in out.strip().splitlines():
        name, data_type = line.split("|")
        cols.append({"name": name, "dataType": TYPE_MAP.get(data_type, "UNKNOWN"), "dataTypeDisplay": data_type})
    if not cols:
        raise RuntimeError(f"{database}.{table} has no columns - has the data loader run?")
    return cols


def main() -> None:
    entities = json.loads((ROOT / "policies/entities.json").read_text())
    token = api("POST", "/users/login", {"email": "admin@open-metadata.org", "password": base64.b64encode(b"admin").decode()})["accessToken"]

    api("PUT", "/classifications", {"name": CLASSIFICATION, "description": "Custodian data sensitivity levels (mirrors policies/entities.json)"}, token)
    for tag, description in TAG_DESCRIPTIONS.items():
        api("PUT", "/tags", {"classification": CLASSIFICATION, "name": tag, "description": description}, token)

    api("PUT", "/services/databaseServices", {
        "name": SERVICE, "serviceType": "Postgres", "description": "Custodian's shared Postgres instance",
        "connection": {"config": {"type": "Postgres", "username": "postgres", "hostPort": "postgres:5432", "database": "custodian"}}}, token)
    for database in sorted({a["database"] for a in entities["dataAssets"].values()}):
        api("PUT", "/databases", {"name": database, "service": SERVICE}, token)
        api("PUT", "/databaseSchemas", {"name": "public", "database": f"{SERVICE}.{database}"}, token)

    for table, asset in entities["dataAssets"].items():
        tag = {"tagFQN": f"{CLASSIFICATION}.{asset['classification']}", "source": "Classification", "labelType": "Manual", "state": "Confirmed"}
        created = api("PUT", "/tables", {
            "name": table, "description": asset["description"], "tableType": "Regular",
            "databaseSchema": f"{SERVICE}.{asset['database']}.public", "columns": columns(asset["database"], table), "tags": [tag]}, token)
        print(f"registered {created['fullyQualifiedName']} -> {tag['tagFQN']}")


if __name__ == "__main__":
    main()
