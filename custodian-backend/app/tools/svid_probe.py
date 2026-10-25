"""Fetches an X.509-SVID via the test/verification SPIRE entry and prints its real lifetime."""
import json

from datetime import UTC, datetime

from spiffe import WorkloadApiClient

with WorkloadApiClient() as client:
    svid = client.fetch_x509_svid()
leaf = svid.leaf
now = datetime.now(UTC)
print(json.dumps({
    "spiffe_id": str(svid.spiffe_id),
    "issued_at": leaf.not_valid_before_utc.isoformat(),
    "expires_at": leaf.not_valid_after_utc.isoformat(),
    "ttl_seconds": int((leaf.not_valid_after_utc - leaf.not_valid_before_utc).total_seconds()),
    "seconds_remaining": int((leaf.not_valid_after_utc - now).total_seconds()),
    "serial": format(leaf.serial_number, "x"),
    "checked_at": now.isoformat(),
}, indent=2))
