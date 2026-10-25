"""Fetches this service's expected API keys from Infisical at startup (custodian-ledger-service identity)."""
import os

import httpx

INFISICAL_URL = os.environ["INFISICAL_URL"]


def fetch_secret(client: httpx.Client, token: str, project_id: str, name: str) -> str:
    resp = client.get(f"{INFISICAL_URL}/api/v4/secrets/{name}", params={"projectId": project_id, "environment": "prod", "secretPath": "/"},
                      headers={"Authorization": f"Bearer {token}"})
    resp.raise_for_status()
    return resp.json()["secret"]["secretValue"]


def load_api_keys() -> tuple[str, str]:
    with httpx.Client(timeout=10) as client:
        login = client.post(f"{INFISICAL_URL}/api/v1/auth/universal-auth/login",
                            json={"clientId": os.environ["INFISICAL_CLIENT_ID"], "clientSecret": os.environ["INFISICAL_CLIENT_SECRET"]})
        login.raise_for_status()
        token = login.json()["accessToken"]
        write_key = fetch_secret(client, token, os.environ["INFISICAL_PROJECT_LEDGER_WRITE"], "LEDGER_API_KEY")
        lookup_key = fetch_secret(client, token, os.environ["INFISICAL_PROJECT_VENDOR_LOOKUP"], "VENDOR_LOOKUP_API_KEY")
    return write_key, lookup_key
