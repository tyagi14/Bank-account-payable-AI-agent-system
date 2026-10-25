"""Tiny .env reader/writer shared by the provisioning scripts (stdlib only)."""
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parents[2] / ".env"


def read_env() -> dict[str, str]:
    values = {}
    for line in ENV_PATH.read_text().splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            values[key.strip()] = value
    return values


def write_env(updates: dict[str, str]) -> None:
    lines = ENV_PATH.read_text().splitlines()
    out = [f"{line.partition('=')[0]}={updates[line.partition('=')[0]]}" if line.partition("=")[0] in updates else line for line in lines]
    ENV_PATH.write_text("\n".join(out) + "\n")
