# 01. SPIRE issues short-lived workload identities from container attestation

**What this proves:** a workload's identity is issued by SPIRE from what the container verifiably is (its Docker labels), carries a one-hour lifetime, and is rotated without a restart.

## Background
`spire-server` holds the registration entries; `spire-agent` runs with `pid: host` and the Docker socket so its docker workload attestor can see which container is calling the Workload API socket. `infra/scripts/register-spire-entries.sh` registers six entries, each with `-x509SVIDTTL 3600`: the backend (selector `com.docker.compose.service:custodian-backend`), one per agent, and a probe (`custodian.workload:spire-verify`). The backend fetches its SVID with `spiffe`'s `X509Source` at import time (`custodian-backend/app/identity.py`) and exposes it on `/health`. The agent itself attested with a single-use join token whose entry gives it the stable alias `spiffe://custodian.local/node/local`.

## Steps
1. List the registration entries:
   `infra/scripts/compose.sh exec -T spire-server /opt/spire/bin/spire-server entry show -socketPath /tmp/spire-server/private/api.sock`
2. Ask for an SVID from a labelled throwaway container: `infra/scripts/compose.sh --profile tools run --rm spire-verify`
3. Look at the backend's SVID: `curl -s http://127.0.0.1:18000/health`
4. Wait half an hour and repeat step 3 without restarting anything.

## What you'll see
Step 1 (trimmed to the identifying lines; one entry per workload plus the agent alias):
```
Found 7 entries
SPIFFE ID               : spiffe://custodian.local/agent/approval
X509-SVID TTL           : 3600
Selector                : docker:label:custodian.agent:approval
...
SPIFFE ID               : spiffe://custodian.local/node/local
X509-SVID TTL           : default
Selector                : spiffe_id:spiffe://custodian.local/spire/agent/join_token/<join-token>
SPIFFE ID               : spiffe://custodian.local/service/custodian-backend
X509-SVID TTL           : 3600
Selector                : docker:label:com.docker.compose.service:custodian-backend
SPIFFE ID               : spiffe://custodian.local/test/svid-probe
X509-SVID TTL           : 3600
Selector                : docker:label:custodian.workload:spire-verify
```
Step 2:
```json
{
  "spiffe_id": "spiffe://custodian.local/test/svid-probe",
  "issued_at": "2026-10-24T16:10:47+00:00",
  "expires_at": "2026-10-24T17:10:57+00:00",
  "ttl_seconds": 3610,
  "seconds_remaining": 3588,
  "serial": "4dfaa8553f6b2af3e2bb8d892cea5e2e",
  "checked_at": "2026-10-24T16:11:08.311581+00:00"
}
```
Steps 3 and 4: the backend container was started at 15:27 UTC; at 16:10 its `/health` reported an SVID `issued_at` 15:54:41 and, later, 16:10:47. The certificate changed under the running process twice with no restart.
```json
"identity": {
  "spiffe_id": "spiffe://custodian.local/service/custodian-backend",
  "expires_at": "2026-10-24T17:10:57+00:00",
  "seconds_remaining": 3588,
  "issued_at": "2026-10-24T16:10:47+00:00"
}
```
The 3610 s TTL (not 3600) is SPIRE back-dating `NotBefore` by 10 s for clock skew.

## What this actually teaches
The identity is a property the platform observes (labels on a container the Docker daemon reports), not a secret someone copied into a config file, and it expires within the hour whether or not anyone remembers to rotate it. Honest limits: the four per-agent entries cannot be attested separately, because all agents run inside the one backend process and share its SVID; per-agent separation is enforced by Cedar and the capability manifests instead (scenario 13). The SVID gates start-up and every consequential action, but service-to-service calls are not mTLS. And anyone with access to the Docker socket can create a container with any label: the attestor is only as trustworthy as access to that socket.
