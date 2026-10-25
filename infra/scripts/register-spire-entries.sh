#!/bin/sh
# Registers the six workload entries (1h X.509-SVID TTL). Safe to re-run: existing entries are skipped.
#
# Only the custodian-backend entry is ever fetched by a running process: SPIRE attests one identity
# per OS process, and the four agents are function calls inside that one process. The four agent
# entries document intended identities; per-agent separation is enforced by Cedar and the capability
# manifests instead (see INSTRUCTIONS.md).
set -eu
root=$(cd "$(dirname "$0")/../.." && pwd)
compose="$root/infra/scripts/layer.sh identity"
domain=$(grep -E '^SPIRE_TRUST_DOMAIN=' "$root/.env" | cut -d= -f2-)
parent="spiffe://$domain/node/local"

register() {
  id="spiffe://$domain/$1"; selector=$2
  if $compose exec -T spire-server /opt/spire/bin/spire-server entry show -spiffeID "$id" | grep -q "Entry ID"; then
    echo "exists: $id"
  else
    $compose exec -T spire-server /opt/spire/bin/spire-server entry create \
      -parentID "$parent" -spiffeID "$id" -selector "$selector" -x509SVIDTTL 3600 >/dev/null
    echo "created: $id ($selector)"
  fi
}

register service/custodian-backend docker:label:com.docker.compose.service:custodian-backend
register agent/extraction docker:label:custodian.agent:extraction
register agent/risk-scoring docker:label:custodian.agent:risk-scoring
register agent/approval docker:label:custodian.agent:approval
register agent/payment-execution docker:label:custodian.agent:payment-execution
register test/svid-probe docker:label:custodian.workload:spire-verify
