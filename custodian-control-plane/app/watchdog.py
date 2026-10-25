"""Automatic kill-switch triggers, evaluated on a timer independently of the agent runtime.

- canary: any authorization request naming a canary vendor trips a global stop
- repeated denials: an agent denied too often in a rolling window is paused
- missed heartbeat: a run whose latest heartbeat (across all of its agents) is active but stale is halted
"""
import logging
import re

from psycopg import AsyncConnection

log = logging.getLogger("control-plane.watchdog")

# AutoApproveInvoice denials are the normal "route to a human" signal, not misbehaviour.
ROUTING_ACTIONS = ["AutoApproveInvoice"]


def normalize_vendor(name: str) -> str:
    # Must match custodian-ledger/app/vendors.py normalize_vendor.
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9 ]", " ", name.upper())).strip()


async def _last_reset(conn: AsyncConnection, scope: str, target: str):
    cur = await conn.execute("SELECT max(reset_at) FROM kill_switches WHERE scope = %s AND target = %s", (scope, target))
    return (await cur.fetchone())[0]


async def canary_hits(conn: AsyncConnection, canaries: list[str]) -> list[str]:
    since = await _last_reset(conn, "global", "*")
    cur = await conn.execute(
        """SELECT DISTINCT principal || ' requested ' || action || ' for canary vendor ' || vendor FROM policy_decisions
           WHERE vendor = ANY(%s) AND ts > COALESCE(%s, '-infinity'::timestamptz)""",
        ([normalize_vendor(c) for c in canaries], since))
    return [r[0] for r in await cur.fetchall()]


async def denial_offenders(conn: AsyncConnection, threshold: int, window_seconds: int) -> list[tuple[str, int]]:
    """Only refusals by policy count; a denial caused by a kill switch or an unreachable dependency is not the agent's doing."""
    cur = await conn.execute(
        """SELECT d.principal, count(*) FROM policy_decisions d
           WHERE d.decision = 'deny' AND d.principal LIKE 'Agent::%%' AND NOT (d.action = ANY(%s))
             AND (d.checks->>'cedar' = 'deny' OR d.checks->>'temporal' = 'deny')
             AND d.ts > now() - make_interval(secs => %s)
             AND d.ts > COALESCE((SELECT max(reset_at) FROM kill_switches k WHERE k.scope = 'agent' AND k.target = substr(d.principal, 8)), '-infinity')
           GROUP BY d.principal HAVING count(*) >= %s""", (ROUTING_ACTIONS, window_seconds, threshold))
    return [(principal.removeprefix("Agent::"), count) for principal, count in await cur.fetchall()]


async def stale_threads(conn: AsyncConnection, stale_seconds: int) -> list[tuple[str, str, float]]:
    """Per run, not per agent: an earlier agent going quiet after handing off is normal."""
    cur = await conn.execute(
        """SELECT thread_id, agent, extract(epoch FROM now() - ts) FROM (
             SELECT DISTINCT ON (thread_id) thread_id, agent, phase, ts FROM heartbeats ORDER BY thread_id, ts DESC, id DESC) latest
           WHERE phase = 'active' AND ts < now() - make_interval(secs => %s)
             AND NOT EXISTS (SELECT 1 FROM kill_switches k WHERE k.scope = 'thread' AND k.target = latest.thread_id AND k.trigger = 'missed_heartbeat')""",
        (stale_seconds,))
    return [(t, a, float(age)) for t, a, age in await cur.fetchall()]
