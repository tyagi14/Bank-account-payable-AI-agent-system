"""Enforces the rolling-window rule specified in policies/temporal/*.dw against the decision log.

Supports exactly the rule shape used there: a forbid over a set of approval actions whose prior
`response` events for the same vendor, counted within an N-hour window, reach a limit. Anything
else in the spec file fails loudly at load time, so the Python enforcement cannot silently drift
from the authoritative .dw text.
"""
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from psycopg import AsyncConnection


@dataclass(frozen=True)
class RateRule:
    rule_id: str
    actions: tuple[str, ...]
    window_hours: int
    limit: int
    source_file: str


def load_rules(temporal_dir: Path) -> list[RateRule]:
    rules = []
    for path in sorted(temporal_dir.glob("*.dw")):
        text = path.read_text()
        rule_id = re.search(r'@id\("([^"]+)"\)', text)
        actions = re.search(r"action in \[([^\]]+)\]", text)
        window = re.search(r"formerly within (\d+)h", text)
        limit = re.search(r"n >= (\d+)", text)
        if not (rule_id and actions and window and limit and "input.vendor: context.input.vendor" in text):
            raise ValueError(f"{path.name}: unsupported temporal rule shape")
        names = tuple(re.findall(r'Action::"(\w+)"', actions.group(1)))
        rules.append(RateRule(rule_id.group(1), names, int(window.group(1)), int(limit.group(1)), path.name))
    return rules


async def check(conn: AsyncConnection, rules: list[RateRule], action: str, vendor: str | None) -> tuple[bool, list[str]]:
    """Must run inside the transaction that records the decision: the advisory lock serializes
    concurrent approvals for one vendor, so N parallel requests cannot all see count < limit."""
    if vendor is None:
        return True, []
    violations = []
    for rule in rules:
        if action not in rule.actions:
            continue
        lock_key = int.from_bytes(hashlib.sha256(f"{rule.rule_id}:{vendor}".encode()).digest()[:8], "big", signed=True)
        await conn.execute("SELECT pg_advisory_xact_lock(%s)", (lock_key,))
        cur = await conn.execute(
            """SELECT count(*) FROM policy_decisions
               WHERE decision = 'allow' AND action = ANY(%s) AND vendor = %s AND ts > now() - make_interval(hours => %s)""",
            (list(rule.actions), vendor, rule.window_hours))
        count = (await cur.fetchone())[0]
        if count >= rule.limit:
            violations.append(f"{rule.rule_id}: {count} approvals for this vendor in the last {rule.window_hours}h (limit {rule.limit})")
    return not violations, violations
