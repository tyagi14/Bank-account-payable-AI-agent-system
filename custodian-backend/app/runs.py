"""Run records and the live event stream the console watches."""
from typing import Literal

from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

# Mirrors the A2A TaskState vocabulary (a2a.types.TaskState TASK_STATE_*), in its wire spelling.
TaskState = Literal["submitted", "working", "input-required", "completed", "failed", "canceled", "rejected"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    thread_id text PRIMARY KEY,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    source text NOT NULL,
    task_state text NOT NULL,
    stage text NOT NULL,
    summary jsonb NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS run_events (
    id bigserial PRIMARY KEY,
    thread_id text NOT NULL REFERENCES runs (thread_id),
    ts timestamptz NOT NULL DEFAULT now(),
    agent text NOT NULL,
    kind text NOT NULL,
    detail jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS run_events_thread_idx ON run_events (thread_id, id);
"""


class RunStore:
    def __init__(self, pool: AsyncConnectionPool):
        self.pool = pool

    async def setup(self) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(SCHEMA)

    async def create(self, thread_id: str, source: str) -> None:
        async with self.pool.connection() as conn:
            await conn.execute("INSERT INTO runs (thread_id, source, task_state, stage) VALUES (%s, %s, 'submitted', 'submitted')", (thread_id, source))

    async def update(self, thread_id: str, task_state: TaskState, stage: str, summary: dict | None = None) -> None:
        async with self.pool.connection() as conn:
            await conn.execute("UPDATE runs SET task_state = %s, stage = %s, summary = summary || %s, updated_at = now() WHERE thread_id = %s",
                               (task_state, stage, Jsonb(summary or {}), thread_id))

    async def event(self, thread_id: str, agent: str, kind: str, detail: dict) -> None:
        async with self.pool.connection() as conn:
            await conn.execute("INSERT INTO run_events (thread_id, agent, kind, detail) VALUES (%s, %s, %s, %s)",
                               (thread_id, agent, kind, Jsonb(detail)))

    async def list(self, limit: int, task_state: str | None = None) -> list[dict]:
        where = "WHERE task_state = %s" if task_state else ""
        params = (task_state, limit) if task_state else (limit,)
        async with self.pool.connection() as conn:
            cur = await conn.execute(f"SELECT thread_id, created_at, updated_at, source, task_state, stage, summary FROM runs {where} "
                                     "ORDER BY created_at DESC LIMIT %s", params)
            cols = ["thread_id", "created_at", "updated_at", "source", "task_state", "stage", "summary"]
            return [dict(zip(cols, r)) for r in await cur.fetchall()]

    async def get(self, thread_id: str) -> dict | None:
        async with self.pool.connection() as conn:
            cur = await conn.execute("SELECT thread_id, created_at, updated_at, source, task_state, stage, summary FROM runs WHERE thread_id = %s", (thread_id,))
            row = await cur.fetchone()
        return dict(zip(["thread_id", "created_at", "updated_at", "source", "task_state", "stage", "summary"], row)) if row else None

    async def events(self, thread_id: str, after_id: int = 0) -> list[dict]:
        async with self.pool.connection() as conn:
            cur = await conn.execute("SELECT id, ts, agent, kind, detail FROM run_events WHERE thread_id = %s AND id > %s ORDER BY id",
                                     (thread_id, after_id))
            return [dict(zip(["id", "ts", "agent", "kind", "detail"], r)) for r in await cur.fetchall()]
