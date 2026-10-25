#!/usr/bin/env python3
"""Creates the Infisical projects, their secrets, and one narrowly-scoped machine identity per service.

Scoping is done with one project per secret scope (custom per-folder roles need Infisical's
Enterprise plan): each identity is a read-only "viewer" of exactly the projects it needs, so e.g.
the vendor-lookup identity can never read the ledger write key. Re-runnable: existing objects are
reused and each identity receives a fresh client secret. Writes the resulting values into .env and
prints them.
"""
import json
import secrets
import sys
import urllib.error
import urllib.request

from _envfile import read_env, write_env

URL = "http://localhost:18082"
ENVIRONMENT = "prod"

# project -> secrets stored there ("generate" = random value, None = value copied from .env)
PROJECTS = {
    "custodian-ledger-write": {"LEDGER_API_KEY": "generate"},
    "custodian-vendor-lookup": {"VENDOR_LOOKUP_API_KEY": "generate"},
    "custodian-llm-providers": {"OPENAI_API_KEY": None, "GROQ_API_KEY": None},
}
# identity name -> (projects it may read, .env prefix)
IDENTITIES = {
    "custodian-payment-execution": (["custodian-ledger-write"], "PAYMENT_EXEC"),
    "custodian-vendor-lookup": (["custodian-vendor-lookup"], "VENDOR_LOOKUP"),
    "custodian-ledger-service": (["custodian-ledger-write", "custodian-vendor-lookup"], "LEDGER_SERVICE"),
    "custodian-litellm": (["custodian-llm-providers"], "LITELLM"),
}
ANY_IP = [{"ipAddress": "0.0.0.0/0"}, {"ipAddress": "::/0"}]
TOKEN_TTL_SECONDS = 300  # machine sessions are short-lived on purpose


def api(method: str, path: str, body: dict | None = None, token: str | None = None) -> dict:
    req = urllib.request.Request(URL + path, method=method, data=json.dumps(body).encode() if body is not None else None)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as err:
        raise RuntimeError(f"{method} {path} -> {err.code}: {err.read().decode()[:400]}") from None


def main() -> None:
    env = read_env()
    if not env.get("INFISICAL_ADMIN_CLIENT_ID"):
        sys.exit("INFISICAL_ADMIN_CLIENT_ID is empty - run infra/scripts/bootstrap-infisical.sh first")
    token = api("POST", "/api/v1/auth/universal-auth/login",
                {"clientId": env["INFISICAL_ADMIN_CLIENT_ID"], "clientSecret": env["INFISICAL_ADMIN_CLIENT_SECRET"]})["accessToken"]

    existing = {p["name"]: p for p in api("GET", "/api/v1/projects?type=secret-manager", token=token)["projects"]}
    project_ids, org_id = {}, None
    for name, secret_specs in PROJECTS.items():
        project = existing.get(name) or api("POST", "/api/v1/projects", {"projectName": name, "type": "secret-manager"}, token)["project"]
        project_ids[name], org_id = project["id"], project["orgId"]
        for secret_name, source in secret_specs.items():
            value = secrets.token_hex(32) if source == "generate" else env.get(secret_name, "")
            if not value:
                print(f"warning: {secret_name} is empty in .env - set it and re-run this script", file=sys.stderr)
                continue
            body = {"projectId": project["id"], "environment": ENVIRONMENT, "secretPath": "/", "secretValue": value, "type": "shared"}
            try:
                api("POST", f"/api/v4/secrets/{secret_name}", body, token)
                print(f"stored secret {name}/{secret_name}")
            except RuntimeError as err:
                if "already exist" not in str(err):
                    raise
                if source is None:  # provider keys follow .env; generated keys are left alone on re-run
                    api("PATCH", f"/api/v4/secrets/{secret_name}", body, token)
                    print(f"updated secret {name}/{secret_name}")

    identities = {i["identity"]["name"]: i["identity"]["id"]
                  for i in api("GET", f"/api/v2/organizations/{org_id}/identity-memberships?limit=100", token=token)["identityMemberships"]}
    updates = {f"INFISICAL_PROJECT_{n.removeprefix('custodian-').upper().replace('-', '_')}": pid for n, pid in project_ids.items()}
    for name, (projects, prefix) in IDENTITIES.items():
        identity_id = identities.get(name)
        if identity_id is None:
            identity_id = api("POST", "/api/v1/identities", {"name": name, "organizationId": org_id, "role": "no-access"}, token)["identity"]["id"]
            api("POST", f"/api/v1/auth/universal-auth/identities/{identity_id}",
                {"accessTokenTTL": TOKEN_TTL_SECONDS, "accessTokenMaxTTL": TOKEN_TTL_SECONDS,
                 "accessTokenTrustedIps": ANY_IP, "clientSecretTrustedIps": ANY_IP}, token)
            for project in projects:
                api("POST", f"/api/v1/projects/{project_ids[project]}/identity-memberships/{identity_id}",
                    {"roles": [{"role": "viewer", "isTemporary": False}]}, token)
            print(f"created identity {name} -> {projects}")
        client_id = api("GET", f"/api/v1/auth/universal-auth/identities/{identity_id}", token=token)["identityUniversalAuth"]["clientId"]
        client_secret = api("POST", f"/api/v1/auth/universal-auth/identities/{identity_id}/client-secrets",
                            {"description": "custodian", "ttl": 0}, token)["clientSecret"]
        updates[f"{prefix}_CLIENT_ID"] = client_id
        updates[f"{prefix}_CLIENT_SECRET"] = client_secret

    write_env(updates)
    print("\nWrote these values into .env:")
    for key, value in updates.items():
        print(f"{key}={value}")


if __name__ == "__main__":
    main()
