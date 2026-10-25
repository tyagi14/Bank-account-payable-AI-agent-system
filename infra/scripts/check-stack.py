#!/usr/bin/env python3
"""Confirms the whole stack is up and every layer is actually working, not just running.

Usage: python3 infra/scripts/check-stack.py
Prints PASS/FAIL per check with the evidence; exit code 1 if anything failed.
The LiteLLM check makes one tiny real call per route (a few hundred tokens in total).
"""
import base64
import json
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from _envfile import read_env

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ["sh", str(ROOT / "infra/scripts/compose.sh")]
ONE_SHOT = {"minio-init", "openmetadata-migrate", "spire-server-volume-init"}
EXPECTED_TABLES = 5
env = read_env()
results: list[bool] = []


def http(method: str, url: str, body: dict | bytes | None = None, headers: dict | None = None, timeout: int = 60) -> tuple[int, dict | str]:
    data = body if isinstance(body, bytes) else json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            status = resp.status
    except urllib.error.HTTPError as err:
        raw, status = err.read(), err.code
    except (urllib.error.URLError, TimeoutError) as err:
        return 0, str(err)
    try:
        return status, json.loads(raw)
    except ValueError:
        return status, raw.decode(errors="replace")


def report(name: str, ok: bool, evidence: str) -> None:
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name:<34} {evidence}")


def psql(database: str, sql: str) -> str:
    out = subprocess.run([*COMPOSE, "exec", "-T", "postgres", "psql", "-U", "postgres", "-d", database, "-tA", "-c", sql],
                         capture_output=True, text=True, timeout=60)
    return out.stdout.strip()


def check_containers() -> None:
    out = subprocess.run([*COMPOSE, "ps", "-a", "--format", "json"], capture_output=True, text=True, timeout=60).stdout
    rows = [json.loads(line) for line in out.splitlines() if line.strip()]
    bad = []
    for r in rows:
        if r["Service"] in ONE_SHOT:
            if r["State"] != "exited" or "Exited (0)" not in r["Status"]:
                bad.append(f"{r['Service']}: {r['Status']}")
        elif r["State"] != "running" or "unhealthy" in r["Status"] or "starting" in r["Status"]:
            bad.append(f"{r['Service']}: {r['Status']}")
    running = sum(1 for r in rows if r["State"] == "running")
    report("containers running and healthy", not bad and running > 0, f"{running} running" + (f"; problems: {bad}" if bad else ""))


def check_keycloak() -> None:
    status, realm = http("GET", "http://127.0.0.1:18081/realms/custodian")
    form = urllib.parse.urlencode({"grant_type": "password", "client_id": "custodian-cli", "username": "controller",
                                   "password": env.get("KC_CONTROLLER_PASSWORD", "")}).encode()
    tstatus, token = http("POST", "http://127.0.0.1:18081/realms/custodian/protocol/openid-connect/token", form,
                          {"Content-Type": "application/x-www-form-urlencoded"})
    roles = []
    if tstatus == 200:
        payload = token["access_token"].split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        roles = [r for r in claims.get("realm_access", {}).get("roles", []) if r in ("ap_clerk", "finance_controller", "cfo")]
    report("Keycloak realm and operator login", status == 200 and tstatus == 200 and roles == ["finance_controller"],
           f"realm={realm.get('realm') if isinstance(realm, dict) else status}, controller token roles={roles}")


def check_identity_and_prompts() -> None:
    status, health = http("GET", "http://127.0.0.1:18000/health")
    if status != 200:
        report("backend SVID (SPIRE)", False, f"backend /health -> {status} {str(health)[:120]}")
        report("prompts loaded from MLflow", False, "backend not up")
        return
    ident = health["identity"]
    report("backend SVID (SPIRE)", ident["seconds_remaining"] > 0, f"{ident['spiffe_id']}, {ident['seconds_remaining']}s remaining")
    sources = health["prompts"]
    fallbacks = [k for k, v in sources.items() if not v.startswith("mlflow:")]
    report("prompts loaded from MLflow", not fallbacks, f"extraction={sources.get('extraction')}" + (f"; bundled fallback for {fallbacks}" if fallbacks else ""))


def check_infisical() -> None:
    status, login = http("POST", "http://127.0.0.1:18082/api/v1/auth/universal-auth/login",
                         {"clientId": env.get("PAYMENT_EXEC_CLIENT_ID", ""), "clientSecret": env.get("PAYMENT_EXEC_CLIENT_SECRET", "")})
    if status != 200:
        report("Infisical secret brokering", False, f"payment identity login -> {status}")
        return
    query = urllib.parse.urlencode({"projectId": env.get("INFISICAL_PROJECT_LEDGER_WRITE", ""), "environment": "prod", "secretPath": "/"})
    rstatus, _ = http("GET", f"http://127.0.0.1:18082/api/v4/secrets/LEDGER_API_KEY?{query}", headers={"Authorization": f"Bearer {login['accessToken']}"})
    report("Infisical secret brokering", rstatus == 200, f"payment identity reads LEDGER_API_KEY -> {rstatus}, token TTL {login['expiresIn']}s")


def check_catalog() -> None:
    om = "http://127.0.0.1:18585/api/v1"
    status, login = http("POST", f"{om}/users/login", {"email": "admin@open-metadata.org", "password": base64.b64encode(b"admin").decode()}, timeout=120)
    if status != 200:
        report("OpenMetadata catalog", False, f"login -> {status}")
        return
    status, tables = http("GET", f"{om}/tables?fields=tags&limit=50&service=custodian-postgres", headers={"Authorization": f"Bearer {login['accessToken']}"}, timeout=120)
    tagged = [t["name"] for t in tables.get("data", []) if any(x["tagFQN"].startswith("CustodianSensitivity.") for x in t.get("tags", []))] if status == 200 else []
    report("OpenMetadata catalog", len(tagged) == EXPECTED_TABLES, f"{len(tagged)}/{EXPECTED_TABLES} tables tagged: {sorted(tagged)}")


def check_cedar() -> None:
    out = subprocess.run([sys.executable, str(ROOT / "infra/scripts/validate-cedar-policies.py")], capture_output=True, text=True, timeout=300)
    cases = next((line.split()[1] for line in out.stdout.splitlines() if line.startswith("[matrix]")), "?")
    report("Cedar policies validate", out.returncode == 0, f"{out.stdout.strip().splitlines()[-1] if out.stdout.strip() else out.stderr[-200:]} ({cases} matrix cases)")


def check_litellm() -> None:
    for route in ("custodian-reasoning", "custodian-routine", "custodian-guardrail"):
        status, body = http("POST", "http://127.0.0.1:14000/v1/chat/completions",
                            {"model": route, "messages": [{"role": "user", "content": "Reply with the single word OK."}]},
                            {"Authorization": f"Bearer {env.get('LITELLM_MASTER_KEY', '')}"}, timeout=180)
        if status == 200:
            report(f"LiteLLM {route}", True, f"{body['model']} answered, {body['usage']['total_tokens']} tokens")
        else:
            message = body.get("error", {}).get("message", "") if isinstance(body, dict) else str(body)
            report(f"LiteLLM {route}", False, f"HTTP {status}: {message[:160]}")


def check_data() -> None:
    invoices = psql("custodian", "SELECT string_agg(source || '/' || split || '=' || n, ' ' ORDER BY source, split) FROM "
                    "(SELECT source, split, count(*) n FROM invoice_inbox GROUP BY 1, 2) t").replace("\n", "")
    report("invoices loaded (SROIE, CORD)", bool(invoices) and "sroie" in invoices and "cord" in invoices, invoices or "none")
    ledger = psql("ledger", "SELECT (SELECT count(*) FROM vendors) || ' vendors, ' || (SELECT count(*) FROM historical_payments) || ' historical payments'")
    report("vendor master (USAspending)", bool(ledger) and not ledger.startswith("0 "), ledger or "none")


def check_audit() -> None:
    out = subprocess.run([*COMPOSE, "exec", "-T", "custodian-audit-log", "python", "-c",
                          "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/verify', timeout=120).read().decode())"],
                         capture_output=True, text=True, timeout=180)
    try:
        result = json.loads(out.stdout)
        report("audit chain verifies", result["valid"], f"{result['entries_checked']} entries, findings: {result['stage1_chain'] + result['stage2_worm']}")
    except ValueError:
        report("audit chain verifies", False, (out.stderr or out.stdout)[-200:])


def main() -> int:
    for check in (check_containers, check_keycloak, check_identity_and_prompts, check_infisical, check_catalog,
                  check_cedar, check_litellm, check_data, check_audit):
        try:
            check()
        except Exception as exc:  # one broken layer must not hide the others
            report(check.__name__.removeprefix("check_"), False, f"{exc.__class__.__name__}: {exc}")
    failed = results.count(False)
    print(f"\n{len(results) - failed}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
