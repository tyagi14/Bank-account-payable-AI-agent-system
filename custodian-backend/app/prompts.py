"""Prompt templates, loaded once at process startup from the MLflow Prompt Registry (@production alias).

Falls back to the bundled default if no version has been promoted yet or MLflow is unreachable.
Refresh is by process restart, by design (no background polling)."""
import logging
import os
from pathlib import Path

# The MLflow client reads these once, at import/first use. They must be set before `import mlflow`,
# or an unreachable server turns into a multi-minute hang instead of a fast fall-back.
os.environ.setdefault("MLFLOW_HTTP_REQUEST_TIMEOUT", "5")
os.environ.setdefault("MLFLOW_HTTP_REQUEST_MAX_RETRIES", "0")

import mlflow  # noqa: E402

log = logging.getLogger("prompts")

TEXT_DIR = Path(__file__).parent / "prompt_texts"
REGISTRY = {
    "extraction": ("custodian-extraction", "extraction_structured.txt"),
    "guardrail": ("custodian-guardrail-policy", "guardrail_policy.txt"),
    "risk": ("custodian-risk", "risk.txt"),
    "approval": ("custodian-approval", "approval.txt"),
    "critic": ("custodian-critic", "critic.txt"),
}
PROMPTS: dict[str, dict] = {}


def bundled(key: str) -> str:
    return (TEXT_DIR / REGISTRY[key][1]).read_text()


def load_all() -> dict[str, dict]:
    for key, (name, _) in REGISTRY.items():
        try:
            prompt = mlflow.genai.load_prompt(f"prompts:/{name}@production")
            PROMPTS[key] = {"text": prompt.template, "source": f"mlflow:{name}@production (v{prompt.version})"}
        except Exception as exc:  # fail open: a missing prompt version must not stop the pipeline
            PROMPTS[key] = {"text": bundled(key), "source": f"bundled default ({exc.__class__.__name__})"}
        log.info("prompt %s <- %s", key, PROMPTS[key]["source"])
    return PROMPTS
