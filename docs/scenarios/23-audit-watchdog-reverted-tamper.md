# 23. A tamper reverted before anyone checks is still on record, unless it is faster than the watchdog

**What this proves:** the continuous watchdog catches a tamper that the attacker undoes before any auditor runs `/verify`. The second half shows honestly that a change reverted inside the watchdog's 30-second polling gap is not caught.

## Background
See scenario 22. `/verify` is a point-in-time check: on its own it only says whether the history is intact now. The watchdog turns it into a continuous one by appending its findings to the chain, which a later revert cannot remove.

## Steps
A. Slow tamper, nobody checking:
1. `UPDATE audit_entries SET actor = 'Human::nobody' WHERE seq = 10` (as in scenario 22)
2. Do not call `/verify`. Wait 45 s.
3. Restore the original actor. The original value can be read back from the locked object `entries/000000000010.json` in MinIO, which is what an investigator would do.
4. Now an auditor runs `infra/scripts/call.sh custodian-audit-log GET /verify`, and then looks for watchdog entries.

B. Fast tamper:
1. The same update, then restore it 2 s later.
2. Count `audit_log_tamper_detected` entries before and 70 s after.

## What you'll see
A:
```
tamper_detected entries before: 2
UPDATE 1
(no one calls /verify; wait 45s)
(original actor read back from the WORM object entries/000000000010.json: Agent::approval)
UPDATE 1
(later, an auditor checks)
HTTP 200
{
  "valid": true,
  "entries_checked": 69,
  "stage1_chain": [],
  "stage2_worm": []
}
 seq |                ts                |        event_type         | payload
-----+----------------------------------+---------------------------+--------------------------------------------------------------------
  70 | 2026-10-24T18:59:44.897346+00:00 | audit_log_tamper_resolved | {"entries_checked": 69}
  69 | 2026-10-24T18:58:44.569015+00:00 | audit_log_tamper_detected | {"findings": ["seq 10: content does not match its entry_hash (row modified)", "seq 10: WORM object content differs from the chain"], "entries_checked": 68}
```
The auditor's `/verify` says everything is fine, which is true of the data now. The chain still says that seq 10 was altered between 18:58:44 and 18:59:44.

B:
```
tamper_detected entries before: 3
19:00:23.556
UPDATE 1
UPDATE 1
19:00:25.924
tamper_detected entries 70s later: 3
```
Not caught.

## What this actually teaches
Continuous verification changes the question from "is the history intact now?" to "was it ever not intact?", and that is the question an auditor actually needs answered. Part A is exactly the case the watchdog exists for. Part B is the honest limit of polling: a change and its revert that both land between two checks leave identical data behind, and nothing records them. What limits the damage:
- **The locked object never changed.** The authoritative history was never altered, only its query copy, for two seconds.
- **The exposure is privileged write access to Postgres.** The real fix for B is to remove `UPDATE`/`DELETE` on `audit_entries` from every role that is not the audit service and to log superuser sessions, or to stream the database's change log into the chain. Neither is built here.

Shortening the interval narrows the gap but never closes it.
