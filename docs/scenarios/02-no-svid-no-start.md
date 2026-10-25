# 02. No identity, no backend: the process refuses to start without an SVID

**What this proves:** the backend fails closed when it cannot obtain a workload identity, and recovers by itself once the identity source returns.

## Background
`custodian-backend/app/identity.py` builds the `X509Source` when the module is imported. If the SPIRE Workload API socket is missing or does not answer, it prints a `FATAL` line and exits with code 70; Docker's restart policy keeps trying. There is no "degraded mode" in which the agents run anonymously.

## Steps
1. `infra/scripts/compose.sh stop spire-agent`
2. `infra/scripts/compose.sh restart custodian-backend`, wait 20 s
3. `infra/scripts/compose.sh ps -a custodian-backend` and `infra/scripts/compose.sh logs --tail 4 custodian-backend`
4. `curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:18000/health`
5. `infra/scripts/compose.sh up -d --wait spire-agent custodian-backend`, then `curl -s http://127.0.0.1:18000/health`

## What you'll see
```
custodian-custodian-backend-1 Restarting (70) 4 seconds ago
FATAL: could not obtain an X.509-SVID from the SPIRE Workload API: Invalid WorkloadApiClient configuration: SPIFFE socket file "/run/spire/sockets/agent.sock" does not exist.
FATAL: could not obtain an X.509-SVID from the SPIRE Workload API: Invalid WorkloadApiClient configuration: SPIFFE socket file "/run/spire/sockets/agent.sock" does not exist.
```
Step 4 prints `000`: nothing is listening. After step 5:
```
 Container custodian-spire-agent-1 Healthy
 Container custodian-custodian-backend-1 Healthy
{"status":"ok","identity":{"spiffe_id":"spiffe://custodian.local/service/custodian-backend","expires_at":"2026-10-24T17:12:07+00:00","seconds_remaining":3583,"issued_at":"2026-10-24T16:11:57+00:00"}, ...
```

## The same failure, found in the wild
During the build the Docker VM stalled for about ten hours. The agent's own identity aged out, and on restart it tried to re-attest with the join token in `.env`, which had already been used:
```
join token does not exist or has already been used
```
The agent crash-looped, the socket never appeared, and the backend sat in exactly the loop above. The fix is `infra/scripts/setup-spire.sh`: it issues a new single-use token, writes it to `.env`, removes the old agent's alias entry and attested record, recreates the agent's data volume and starts it. (Before that clean-up was added, every recovery left a stale alias entry behind; the live entry list showed two `node/local` aliases.)

## What this actually teaches
Fail-closed is only real if you have watched it happen: here the backend could not serve a single request without an identity, and nothing in it offered a fallback. The cost is availability: an identity outage is a full outage of the agent tier, which is the right trade for a system that moves money, but it needs the recovery path (`setup-spire.sh`) documented and rehearsed.
