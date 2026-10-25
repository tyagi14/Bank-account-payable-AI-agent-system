# 24. Object lock holds against the storage root account, and the one thing root could do is closed off

**What this proves:** the audit log's WORM copies cannot be deleted, shortened or downgraded even with MinIO's root credentials. The run found that root **could** remove the bucket's default lock rule, which would have left every later entry unlocked. The audit service now locks each object itself and `/verify` checks it.

## Background
`infra/minio-init/init.py` creates the `audit-log` bucket with object lock enabled and a default retention of COMPLIANCE for `AUDIT_RETENTION_DAYS=1` (one day keeps a laptop demo manageable; production would use years). In COMPLIANCE mode, no user (root included) can delete a locked version or shorten its retention before it expires. The audit service writes as `audit-writer`, whose policy allows put, get and set-retention, and no delete.

## Steps
1. As MinIO root, try to break an existing entry's lock (the script, run in the `minio-init` image, which has the MinIO client library and the root credentials):
```python
import os
from datetime import datetime, timedelta, timezone
from minio import Minio
from minio.commonconfig import COMPLIANCE, GOVERNANCE
from minio.error import S3Error
from minio.retention import Retention

root = Minio("minio:9000", os.environ["MINIO_ROOT_USER"], os.environ["MINIO_ROOT_PASSWORD"], secure=False)
bucket, key = "audit-log", "entries/000000000004.json"
stat = root.stat_object(bucket, key)
ret = root.get_object_retention(bucket, key, version_id=stat.version_id)
print(f"as {os.environ['MINIO_ROOT_USER']} (MinIO root): {key} version {stat.version_id}")
print(f"retention mode={ret.mode} retain_until={ret.retain_until_date.isoformat()}")

def attempt(label, fn):
    try:
        fn()
        print(f"{label}: SUCCEEDED")
    except S3Error as e:
        print(f"{label}: refused ({e.code}: {e.message})")

attempt("1. delete the locked version", lambda: root.remove_object(bucket, key, version_id=stat.version_id))
attempt("2. shorten retention to now", lambda: root.set_object_retention(bucket, key, Retention(COMPLIANCE, datetime.now(timezone.utc) + timedelta(seconds=5)), version_id=stat.version_id))
attempt("3. downgrade to GOVERNANCE mode", lambda: root.set_object_retention(bucket, key, Retention(GOVERNANCE, ret.retain_until_date), version_id=stat.version_id))
attempt("4. disable object lock on the bucket", lambda: root.delete_object_lock_config(bucket))
print("object still readable, bytes:", len(root.get_object(bucket, key, version_id=stat.version_id).read()))
```
   `infra/scripts/compose.sh run --rm --no-deps -v "$PWD/worm.py:/worm.py:ro" --entrypoint python minio-init /worm.py`
2. Restore the bucket default: `infra/scripts/compose.sh up -d --force-recreate minio-init`
3. After the fix: remove the bucket default again as root (`root.delete_object_lock_config("audit-log")`), append an event (`infra/scripts/call.sh custodian-audit-log POST /events '{"event_type":"diagnostic","actor":"operator","payload":{"note":"append after bucket default lock removed"}}'`), read the new object's retention as root, run `/verify`, then repeat step 2.

## What you'll see
Step 1:
```
as custodian-root (MinIO root): entries/000000000004.json version 2e6c3cc0-5ac4-4fde-acd3-809ee5665bd6
retention mode=COMPLIANCE retain_until=2026-10-25T15:57:04.411000+00:00
1. delete the locked version: refused (InvalidRequest: Object is WORM protected and cannot be overwritten)
2. shorten retention to now: refused (InvalidRequest: Object is WORM protected and cannot be overwritten)
3. downgrade to GOVERNANCE mode: refused (InvalidRequest: Object is WORM protected and cannot be overwritten)
4. disable object lock on the bucket: SUCCEEDED
object still readable, bytes: 591
```
Attempts 1 to 3 were refused, as COMPLIANCE mode promises. Attempt 4 succeeded. It did not unlock any existing object (the last line shows entry 4 intact and still locked), but it removed the rule that locks **new** objects. From then on, every audit entry would have been written unlocked, and `/verify` at the time did not check retention. The newest entry was seq 67 (18:52), from before the attack, so nothing was written unlocked before step 2 restored the rule.

Step 3, after the fix (each object is written with its own COMPLIANCE retention, and `/verify` checks every entry's retention mode):
```
bucket default retention removed with root credentials; current config: None
HTTP 200
{
  "seq": 68,
  "entry_hash": "46f7ebc19798f741d1354bf1154431cdcdf2b92c5fa22ba5dc325974d317f79f"
}
entries/000000000068.json: retention mode=COMPLIANCE retain_until=2026-10-25T18:58:25.281000+00:00
HTTP 200
{
  "valid": true,
  "entries_checked": 68,
  "stage1_chain": [],
  "stage2_worm": []
}
audit-log default retention: COMPLIANCE 1 day(s)
```

## What this actually teaches
"Even root cannot delete it" was true and still not enough. The attack that worked did not touch the past. It changed the configuration that protects the future, and a test that only tried to delete things would never have found it. The fix moves the guarantee from bucket configuration, which an administrator can change, to every individual write, which is checked on every verification. Honest limits:
- **Retention is one day**, chosen for a laptop. Production would use the legal retention period.
- **Root controls the server.** Root on the MinIO host, or anyone holding the disks, is outside what object lock can defend; real WORM guarantees come from the storage provider's own controls.
