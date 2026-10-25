"""Fetches a secret through a narrow Infisical machine identity: a fresh Universal Auth login and
secret read on every call. Nothing is cached or written to disk/env; the access token itself is
short-lived (5 minutes) on the Infisical side."""
import httpx

from app import config


async def fetch(scope: str) -> str:
    client_id, client_secret, project_id, name = config.INFISICAL_IDENTITIES[scope]
    if not client_id:
        raise RuntimeError(f"no Infisical identity configured for {scope}")
    async with httpx.AsyncClient(timeout=10) as client:
        login = await client.post(f"{config.INFISICAL_URL}/api/v1/auth/universal-auth/login",
                                  json={"clientId": client_id, "clientSecret": client_secret})
        login.raise_for_status()
        resp = await client.get(f"{config.INFISICAL_URL}/api/v4/secrets/{name}",
                                params={"projectId": project_id, "environment": "prod", "secretPath": "/"},
                                headers={"Authorization": f"Bearer {login.json()['accessToken']}"})
        resp.raise_for_status()
        return resp.json()["secret"]["secretValue"]
