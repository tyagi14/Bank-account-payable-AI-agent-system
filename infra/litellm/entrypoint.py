"""Pulls provider API keys from Infisical (as the custodian-litellm machine identity), renders the
gateway config, then execs the real LiteLLM entrypoint. Keys live only in this process's env."""
import json
import os
import string
import sys
import time
import urllib.request

INFISICAL = os.environ["INFISICAL_URL"]


def post(path: str, body: dict) -> dict:
    req = urllib.request.Request(INFISICAL + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.load(resp)


def get(path: str, token: str) -> dict:
    req = urllib.request.Request(INFISICAL + path, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.load(resp)


def fetch_provider_keys() -> None:
    token = post("/api/v1/auth/universal-auth/login",
                 {"clientId": os.environ["INFISICAL_CLIENT_ID"], "clientSecret": os.environ["INFISICAL_CLIENT_SECRET"]})["accessToken"]
    project = os.environ["INFISICAL_PROJECT_ID"]
    for name in ("OPENAI_API_KEY", "GROQ_API_KEY"):
        secret = get(f"/api/v4/secrets/{name}?projectId={project}&environment=prod&secretPath=/", token)["secret"]
        os.environ[name] = secret["secretValue"]
    print("entrypoint: provider keys loaded from Infisical", flush=True)


for attempt in range(10):
    try:
        fetch_provider_keys()
        break
    except Exception as exc:  # Infisical may still be starting; no keys means no gateway
        print(f"entrypoint: Infisical fetch failed ({exc}), retry {attempt + 1}/10", flush=True)
        time.sleep(5)
else:
    sys.exit("entrypoint: could not load provider keys from Infisical")

for var in ("INFISICAL_CLIENT_ID", "INFISICAL_CLIENT_SECRET"):
    os.environ.pop(var)
with open("/app/config.template.yaml") as src, open("/tmp/config.yaml", "w") as dst:
    dst.write(string.Template(src.read()).substitute(os.environ))
os.execvp("docker/prod_entrypoint.sh", ["docker/prod_entrypoint.sh", "--config", "/tmp/config.yaml", "--port", "4000"])
