"""Workload identity, fetched at import time: no valid SPIFFE identity, no process.

SPIRE attests one identity per connecting OS process. The four agents are function calls inside
this one process, so only spiffe://<td>/service/custodian-backend is genuinely fetched here; the
per-agent SPIRE entries are registered but cannot be attested separately without splitting the
agents into four containers. Per-agent separation is instead enforced by Cedar (policy-service)
and the capability manifests (app/manifests.py), neither of which shares this limitation.
"""
import logging
import os
import sys
from datetime import UTC, datetime

from spiffe import X509Source

from app.config import SPIFFE_EXPECTED_ID

log = logging.getLogger("identity")

try:
    _source = X509Source(socket_path=os.environ.get("SPIFFE_ENDPOINT_SOCKET"), timeout_in_seconds=15)
    _svid = _source.svid
except Exception as exc:
    print(f"FATAL: could not obtain an X.509-SVID from the SPIRE Workload API: {exc}", file=sys.stderr, flush=True)
    sys.exit(70)

if str(_svid.spiffe_id) != SPIFFE_EXPECTED_ID:
    print(f"FATAL: attested as {_svid.spiffe_id}, expected {SPIFFE_EXPECTED_ID}", file=sys.stderr, flush=True)
    sys.exit(70)

SPIFFE_ID = str(_svid.spiffe_id)


def current() -> dict:
    """The live SVID (the source rotates it in the background). An expired identity is fatal."""
    svid = _source.svid
    expires = svid.leaf.not_valid_after_utc
    remaining = (expires - datetime.now(UTC)).total_seconds()
    if remaining <= 0:
        log.critical("X.509-SVID expired at %s and was not renewed; exiting", expires.isoformat())
        os._exit(70)
    return {"spiffe_id": str(svid.spiffe_id), "expires_at": expires.isoformat(), "seconds_remaining": int(remaining),
            "issued_at": svid.leaf.not_valid_before_utc.isoformat()}
