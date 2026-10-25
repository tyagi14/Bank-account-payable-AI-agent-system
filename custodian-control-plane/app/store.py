"""Kill-switch state and heartbeats, persisted in Postgres."""
from psycopg import AsyncConnection

SCHEMA = """
CREATE TABLE IF NOT EXISTS kill_switches (
    id bigserial PRIMARY KEY,
    scope text NOT NULL CHECK (scope IN ('agent', 'thread', 'tool', 'global')),
    target text NOT NULL DEFAULT '*',
    reason text NOT NULL,
    trigger text NOT NULL,
    tripped_by text NOT NULL,
    tripped_at timestamptz NOT NULL DEFAULT now(),
    reset_by text,
    reset_at timestamptz
);
CREATE UNIQUE INDEX IF NOT EXISTS kill_switches_one_active ON kill_switches (scope, target) WHERE reset_at IS NULL;
CREATE TABLE IF NOT EXISTS heartbeats (
    id bigserial PRIMARY KEY,
    thread_id text NOT NULL,
    agent text NOT NULL,
    phase text NOT NULL CHECK (phase IN ('active', 'waiting_human', 'finished')),
    ts timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS heartbeats_thread_idx ON heartbeats (thread_id, ts DESC);
"""


async def trip(conn: AsyncConnection, scope: str, target: str, reason: str, trigger: str, by: str) -> dict | None:
    """Returns the new switch, or None if one is already active for this scope/target."""
    cur = await conn.execute(
        """INSERT INTO kill_switches (scope, target, reason, trigger, tripped_by) VALUES (%s, %s, %s, %s, %s)
           ON CONFLICT (scope, target) WHERE reset_at IS NULL DO NOTHING
           RETURNING id, scope, target, reason, trigger, tripped_by, tripped_at""", (scope, target, reason, trigger, by))
    row = await cur.fetchone()
    return _switch(row) if row else None


async def reset(conn: AsyncConnection, scope: str, target: str, by: str) -> dict | None:
    cur = await conn.execute(
        """UPDATE kill_switches SET reset_by = %s, reset_at = now() WHERE scope = %s AND target = %s AND reset_at IS NULL
           RETURNING id, scope, target, reason, trigger, tripped_by, tripped_at""", (by, scope, target))
    row = await cur.fetchone()
    return _switch(row) if row else None


async def blocking(conn: AsyncConnection, agent: str | None, thread: str | None, tool: str | None) -> list[str]:
    cur = await conn.execute(
        """SELECT scope, target, reason FROM kill_switches WHERE reset_at IS NULL AND (
             scope = 'global' OR (scope = 'agent' AND target = %s) OR (scope = 'thread' AND target = %s) OR (scope = 'tool' AND target = %s))""",
        (agent, thread, tool))
    return [f"{scope} {target}: {reason}" for scope, target, reason in await cur.fetchall()]


async def history(conn: AsyncConnection, limit: int) -> list[dict]:
    cur = await conn.execute(
        """SELECT id, scope, target, reason, trigger, tripped_by, tripped_at, reset_by, reset_at FROM kill_switches
           ORDER BY tripped_at DESC LIMIT %s""", (limit,))
    cols = ["id", "scope", "target", "reason", "trigger", "tripped_by", "tripped_at", "reset_by", "reset_at"]
    return [dict(zip(cols, row)) for row in await cur.fetchall()]


def _switch(row) -> dict:
    return dict(zip(["id", "scope", "target", "reason", "trigger", "tripped_by", "tripped_at"], row))
