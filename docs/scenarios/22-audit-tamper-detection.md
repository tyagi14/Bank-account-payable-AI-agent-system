# 22. Rewriting the audit history is detected, at both layers

**What this proves:** changing a recorded decision in the audit database, as a database administrator could, is caught by recomputing the hash chain and by comparing against the immutable copy in object storage, and the detection is written into the chain itself.

## Background
`custodian-audit-log` (`app/chain.py`) appends every event as a hash-chained entry. Each entry's `entry_hash` covers its content and the previous entry's hash. Under one Postgres advisory lock, an append:
1. writes the entry as a JSON object to the MinIO bucket `audit-log`, which has object lock in COMPLIANCE mode and per-object COMPLIANCE retention (scenario 24), and
2. inserts it into the Postgres mirror `audit_entries`, used for queries.

`GET /verify` runs two stages:
- **Stage 1** recomputes every hash and link from Postgres.
- **Stage 2** fetches every entry's object and checks it byte for byte against what the chain says, along with its version history and its retention mode.

A watchdog thread runs the same check every `AUDIT_WATCHDOG_INTERVAL_SECONDS=30` and appends `audit_log_tamper_detected` (and later `audit_log_tamper_resolved`) entries to the chain.

## Steps
1. Turn a denied decision into an allow in the database:
   `infra/scripts/compose.sh exec -T postgres psql -U postgres -d audit -c "UPDATE audit_entries SET payload = jsonb_set(payload, '{decision}', '\"allow\"') WHERE seq = 4"`
2. `infra/scripts/call.sh custodian-audit-log GET /verify`
3. Wait for the watchdog (up to 30 s)
4. Put the row back (`... '\"deny\"' ... WHERE seq = 4`) and verify again
5. `infra/scripts/compose.sh exec -T postgres psql -U postgres -d audit -c "SELECT seq, ts, event_type, actor, left(payload::text, 140) FROM audit_entries WHERE event_type LIKE 'audit_log_tamper%' ORDER BY seq"`

## What you'll see
Step 2:
```json
{
  "valid": false,
  "entries_checked": 51,
  "stage1_chain": [
    "seq 4: content does not match its entry_hash (row modified)"
  ],
  "stage2_worm": [
    "seq 4: WORM object content differs from the chain"
  ]
}
```
Step 4:
```json
{
  "valid": true,
  "entries_checked": 52,
  "stage1_chain": [],
  "stage2_worm": []
}
```
(52, not 51: the watchdog's finding is now part of the chain.)

Step 5:
```
 seq |                ts                |        event_type         |       actor        | payload
-----+----------------------------------+---------------------------+--------------------+----------------------------------------------
  52 | 2026-10-24T16:05:41.692639+00:00 | audit_log_tamper_detected | audit-log-watchdog | {"findings": ["seq 4: content does not match its entry_hash (row modified)", "seq 4: WORM object content differs from the chain"], "entries_
  53 | 2026-10-24T16:07:12.277616+00:00 | audit_log_tamper_resolved | audit-log-watchdog | {"entries_checked": 52}
```

## What this actually teaches
A hash chain alone proves the history is self-consistent, not that it is the original: someone with write access could recompute every hash after an edit. The second stage anchors the chain to objects that even the storage administrator cannot change (scenario 24), so a rewrite has to beat both. Writing the detection into the chain makes it permanent: putting the row back fixes the data, not the record that it was changed. Scenario 23 shows what that buys, and where it stops.
