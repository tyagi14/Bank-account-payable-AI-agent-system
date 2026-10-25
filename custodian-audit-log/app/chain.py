"""Hash-chained audit entries: Postgres mirror for queries, MinIO object-locked WORM copy as the anchor."""
import hashlib
import io
import json
import os
from datetime import UTC, datetime, timedelta

from minio import Minio
from minio.commonconfig import COMPLIANCE
from minio.retention import Retention
from psycopg import Connection
from psycopg.types.json import Jsonb

BUCKET = "audit-log"
GENESIS = "0" * 64
CHAIN_LOCK = 7_310_000_001  # pg advisory lock id serializing appends
# Each object carries its own lock: MinIO root can remove a bucket's default retention rule
# (verified live), which would silently leave every later entry unlocked.
RETENTION_DAYS = int(os.environ.get("AUDIT_RETENTION_DAYS", "1"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_entries (
    seq bigint PRIMARY KEY,
    ts text NOT NULL,
    event_type text NOT NULL,
    actor text NOT NULL,
    thread_id text,
    payload jsonb NOT NULL,
    prev_hash text NOT NULL,
    entry_hash text NOT NULL,
    object_key text NOT NULL,
    object_version text NOT NULL
);
CREATE INDEX IF NOT EXISTS audit_entries_thread_idx ON audit_entries (thread_id);
"""
FIELDS = ("seq", "ts", "event_type", "actor", "thread_id", "payload", "prev_hash")


def canonical(entry: dict) -> bytes:
    return json.dumps({k: entry[k] for k in FIELDS}, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def entry_hash(entry: dict) -> str:
    return hashlib.sha256(canonical(entry)).hexdigest()


def object_bytes(entry: dict) -> bytes:
    """Exactly what is written to (and later compared against) the locked object."""
    return json.dumps({**{k: entry[k] for k in FIELDS}, "entry_hash": entry["entry_hash"]}, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode()


def object_key(seq: int) -> str:
    return f"entries/{seq:012d}.json"


def append(conn: Connection, minio: Minio, event_type: str, actor: str, thread_id: str | None, payload: dict) -> dict:
    """Write order: WORM object first, then the Postgres mirror, all under one chain lock."""
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (CHAIN_LOCK,))
        last = conn.execute("SELECT seq, entry_hash FROM audit_entries ORDER BY seq DESC LIMIT 1").fetchone()
        entry = {
            "seq": (last[0] + 1) if last else 1,
            "ts": datetime.now(UTC).isoformat(),
            "event_type": event_type, "actor": actor, "thread_id": thread_id,
            # round-trip through JSON so what we hash is exactly what jsonb will hand back
            "payload": json.loads(json.dumps(payload, default=str)),
            "prev_hash": last[1] if last else GENESIS,
        }
        entry["entry_hash"] = entry_hash(entry)
        data = object_bytes(entry)
        retention = Retention(COMPLIANCE, datetime.now(UTC) + timedelta(days=RETENTION_DAYS))
        written = minio.put_object(BUCKET, object_key(entry["seq"]), io.BytesIO(data), len(data), content_type="application/json",
                                   retention=retention)
        conn.execute(
            """INSERT INTO audit_entries (seq, ts, event_type, actor, thread_id, payload, prev_hash, entry_hash, object_key, object_version)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (entry["seq"], entry["ts"], event_type, actor, thread_id, Jsonb(entry["payload"]), entry["prev_hash"], entry["entry_hash"],
             object_key(entry["seq"]), written.version_id))
    return entry


def verify(conn: Connection, minio: Minio) -> dict:
    """Stage 1: recompute every hash and prev_hash link from the Postgres mirror.
    Stage 2: fetch each entry's actual WORM object, compare it byte-for-byte with what the chain
    says it must be, and confirm it is still under COMPLIANCE retention. A locked version can never change, but a new version can be stacked on the same
    key; a key merely resolving proves nothing, so content and version history are both checked."""
    rows = conn.execute(f"SELECT {', '.join(FIELDS)}, entry_hash, object_key, object_version FROM audit_entries ORDER BY seq").fetchall()
    stage1, stage2 = [], []
    prev = GENESIS
    for i, row in enumerate(rows, start=1):
        entry = dict(zip((*FIELDS, "entry_hash", "object_key", "object_version"), row))
        if entry["seq"] != i:
            stage1.append(f"seq {entry['seq']}: expected seq {i} (gap or reorder)")
        if entry["prev_hash"] != prev:
            stage1.append(f"seq {entry['seq']}: prev_hash does not link to the previous entry")
        if entry_hash(entry) != entry["entry_hash"]:
            stage1.append(f"seq {entry['seq']}: content does not match its entry_hash (row modified)")
        prev = entry["entry_hash"]

        versions = [o for o in minio.list_objects(BUCKET, prefix=entry["object_key"], include_version=True) if not o.is_delete_marker]
        if not versions:
            stage2.append(f"seq {entry['seq']}: WORM object missing")
            continue
        if len(versions) > 1:
            stage2.append(f"seq {entry['seq']}: {len(versions)} versions stacked on {entry['object_key']} (only one may exist)")
        latest = minio.get_object(BUCKET, entry["object_key"])
        try:
            stored = latest.read()
        finally:
            latest.close()
            latest.release_conn()
        if stored != object_bytes(entry):
            stage2.append(f"seq {entry['seq']}: WORM object content differs from the chain")
        if latest.headers.get("x-amz-version-id") != entry["object_version"]:
            stage2.append(f"seq {entry['seq']}: current object version is not the one originally written")
        retention = minio.get_object_retention(BUCKET, entry["object_key"], version_id=entry["object_version"])
        if retention is None or retention.mode != COMPLIANCE:
            stage2.append(f"seq {entry['seq']}: WORM object is not under COMPLIANCE retention")
    return {"valid": not stage1 and not stage2, "entries_checked": len(rows), "stage1_chain": stage1, "stage2_worm": stage2}
