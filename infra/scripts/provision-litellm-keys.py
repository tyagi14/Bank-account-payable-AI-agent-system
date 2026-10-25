#!/usr/bin/env python3
"""Creates one LiteLLM virtual key per LLM-using agent, each limited to the routes that agent needs
and capped with a daily budget the gateway enforces before forwarding a call. Re-runnable: old keys
with the same alias are deleted first. Writes the keys into .env and prints them. Stdlib only.

The Payment-Execution agent makes no LLM calls, so it gets no key at all.
"""
import json
import sys
import urllib.error
import urllib.request

from _envfile import read_env, write_env

URL = "http://localhost:14000"
KEYS = {
    # env var: (alias, routes, budget env var)
    "LITELLM_KEY_EXTRACTION": ("agent-extraction", ["custodian-routine", "custodian-guardrail"], "BUDGET_EXTRACTION_USD"),
    "LITELLM_KEY_RISK": ("agent-risk-scoring", ["custodian-reasoning"], "BUDGET_RISK_USD"),
    "LITELLM_KEY_APPROVAL": ("agent-approval", ["custodian-routine", "custodian-reasoning"], "BUDGET_APPROVAL_USD"),
    "LITELLM_KEY_EVAL": ("prompt-eval", ["custodian-routine"], "BUDGET_EVAL_USD"),
}


def api(method: str, path: str, master: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(URL + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {master}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as err:
        raise RuntimeError(f"{method} {path} -> {err.code}: {err.read().decode()[:400]}") from None


def main() -> None:
    env = read_env()
    master = env.get("LITELLM_MASTER_KEY")
    if not master:
        sys.exit("LITELLM_MASTER_KEY is empty in .env")
    aliases = [alias for alias, _, _ in KEYS.values()]
    try:
        api("POST", "/key/delete", master, {"key_aliases": aliases})
    except RuntimeError as exc:
        if "404" not in str(exc) and "not found" not in str(exc).lower():
            raise
    updates = {}
    for var, (alias, routes, budget_var) in KEYS.items():
        budget = float(env.get(budget_var, "1.0"))
        key = api("POST", "/key/generate", master, {"key_alias": alias, "models": routes, "max_budget": budget, "budget_duration": "1d",
                                                     "metadata": {"agent": alias}})["key"]
        updates[var] = key
        print(f"{alias}: routes={routes} daily budget=${budget:.2f}")
    write_env(updates)
    print("\nWrote these values into .env:")
    for var, key in updates.items():
        print(f"{var}={key}")


if __name__ == "__main__":
    main()
