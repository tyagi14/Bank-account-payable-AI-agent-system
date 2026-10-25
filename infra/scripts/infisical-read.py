#!/usr/bin/env python3
"""Log in to Infisical as one machine identity and try to read one secret, exactly as a service would.

Prints the outcome and the access token's lifetime, never the secret value (pass --show to print it,
e.g. to use the ledger key in a manual curl).
Usage: infra/scripts/infisical-read.py <identity> <secret>
  identity: payment-execution | vendor-lookup | ledger-service | litellm
  secret:   LEDGER_API_KEY | VENDOR_LOOKUP_API_KEY | OPENAI_API_KEY | GROQ_API_KEY
"""
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

from _envfile import read_env

URL = "http://localhost:18082"
ENVIRONMENT = "prod"
IDENTITY_PREFIX = {"payment-execution": "PAYMENT_EXEC", "vendor-lookup": "VENDOR_LOOKUP",
                   "ledger-service": "LEDGER_SERVICE", "litellm": "LITELLM"}
SECRET_PROJECT = {"LEDGER_API_KEY": "LEDGER_WRITE", "VENDOR_LOOKUP_API_KEY": "VENDOR_LOOKUP",
                  "OPENAI_API_KEY": "LLM_PROVIDERS", "GROQ_API_KEY": "LLM_PROVIDERS"}


def call(method: str, path: str, body: dict | None = None, token: str | None = None) -> tuple[int, dict]:
    req = urllib.request.Request(URL + path, method=method, data=json.dumps(body).encode() if body else None,
                                 headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read() or b"{}")


def main() -> int:
    show = "--show" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--show"]
    if len(args) != 2 or args[0] not in IDENTITY_PREFIX or args[1] not in SECRET_PROJECT:
        print(__doc__, file=sys.stderr)
        return 2
    identity, secret = args
    env = read_env()
    prefix = IDENTITY_PREFIX[identity]
    status, login = call("POST", "/api/v1/auth/universal-auth/login",
                         {"clientId": env[f"{prefix}_CLIENT_ID"], "clientSecret": env[f"{prefix}_CLIENT_SECRET"]})
    if status != 200:
        print(f"login as custodian-{identity}: HTTP {status} {login.get('message', '')}")
        return 1
    print(f"login as custodian-{identity}: ok, access token expires in {login['expiresIn']}s")
    query = urllib.parse.urlencode({"projectId": env[f"INFISICAL_PROJECT_{SECRET_PROJECT[secret]}"], "environment": ENVIRONMENT, "secretPath": "/"})
    status, body = call("GET", f"/api/v4/secrets/{secret}?{query}", token=login["accessToken"])
    if status != 200:
        print(f"read {secret}: HTTP {status} {body.get('message', '')}")
        return 1
    value = body["secret"]["secretValue"]
    print(f"read {secret}: ok ({len(value)} characters)" if not show else value)
    return 0


if __name__ == "__main__":
    sys.exit(main())
