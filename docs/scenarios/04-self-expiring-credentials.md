# 04. Self-expiring credentials, measured live

**What this proves:** the credentials the agents use stop working on their own, on schedule, without anyone revoking them: Infisical access tokens after 300 s, SPIRE SVIDs after one hour.

## Background
Every machine identity's Universal Auth configuration sets `accessTokenTTL` and `accessTokenMaxTTL` to 300 s (`TOKEN_TTL_SECONDS` in `provision-infisical-identities.py`), so a token cannot be renewed past five minutes; the payment agent logs in afresh for every ledger call. SVIDs are registered with `-x509SVIDTTL 3600` (scenario 01), and the backend's `identity.current()` kills the process if it is ever asked for an SVID past its expiry rather than act on a stale identity.

## Steps
1. Log in once as the payment identity, then reuse that same access token to read `LEDGER_API_KEY` every 60 s, and every 10 s from the four-minute mark, until it is refused (a small script doing exactly what `infra/scripts/infisical-read.py` does, in a loop, with one token).
2. Compare an SVID's `issued_at` and `expires_at` (scenario 01, step 2).

## What you'll see
Step 1 (local time):
```
14:56:49 logged in as custodian-payment-execution, expiresIn=300s
14:56:49 t+    0s read LEDGER_API_KEY with the same token -> HTTP 200
14:57:49 t+   60s read LEDGER_API_KEY with the same token -> HTTP 200
14:58:49 t+  120s read LEDGER_API_KEY with the same token -> HTTP 200
14:59:49 t+  180s read LEDGER_API_KEY with the same token -> HTTP 200
15:00:49 t+  240s read LEDGER_API_KEY with the same token -> HTTP 200
15:00:59 t+  250s read LEDGER_API_KEY with the same token -> HTTP 200
15:01:09 t+  260s read LEDGER_API_KEY with the same token -> HTTP 200
15:01:19 t+  270s read LEDGER_API_KEY with the same token -> HTTP 200
15:01:29 t+  280s read LEDGER_API_KEY with the same token -> HTTP 200
15:01:39 t+  290s read LEDGER_API_KEY with the same token -> HTTP 200
15:01:49 t+  301s read LEDGER_API_KEY with the same token -> HTTP 403 Your token has expired. Please re-authenticate.
```
Step 2: `"issued_at": "2026-10-24T16:10:47+00:00"`, `"expires_at": "2026-10-24T17:10:57+00:00"`, `"ttl_seconds": 3610`.

## What this actually teaches
A leaked token is worth at most five minutes and a leaked SVID at most an hour, and neither depends on a human noticing the leak. The window is the whole defence, so it should be as short as the workload tolerates: the payment agent pays the price of one extra login per ledger call to keep it at 300 s. Honest limit: the long-lived thing is still the client secret in `.env` that mints those tokens (scenario 03); and the SVID's "kill on expiry" path was not provoked live here, because SPIRE always rotated well before expiry while the agent was up.
