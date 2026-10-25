"""Capability manifests: a second authorization check, independent of Cedar, enforced in code.
A Cedar misconfiguration alone can never grant an agent an action its manifest lacks."""
import json
from pathlib import Path

MANIFEST_DIR = Path(__file__).resolve().parent.parent / "manifests"
LEDGER_WRITE = "ledger.write"


class CapabilityError(PermissionError):
    pass


def _load() -> dict[str, dict]:
    manifests = {}
    for path in sorted(MANIFEST_DIR.glob("*.json")):
        manifest = json.loads(path.read_text())
        manifests[manifest["agent"]] = manifest
    holders = [a for a, m in manifests.items() if LEDGER_WRITE in m["allowedActions"]]
    if holders != ["payment-execution"]:
        raise RuntimeError(f"only payment-execution may hold {LEDGER_WRITE}; manifests grant it to {holders}")
    return manifests


MANIFESTS = _load()


def require(agent: str, action: str) -> None:
    manifest = MANIFESTS.get(agent)
    if manifest is None or action not in manifest["allowedActions"]:
        raise CapabilityError(f"capability manifest for {agent!r} does not allow {action!r}")
