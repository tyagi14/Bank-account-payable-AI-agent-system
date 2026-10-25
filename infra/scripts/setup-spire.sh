#!/bin/sh
# Generates a fresh single-use SPIRE agent join token, exports the server trust bundle for the
# agent, and writes the token into .env. Re-run whenever the agent's persisted identity is lost
# or expired (fresh volume, or SVID aged past renewal while the server was unreachable).
set -eu
root=$(cd "$(dirname "$0")/../.." && pwd)
compose="$root/infra/scripts/layer.sh identity"
domain=$(grep -E '^SPIRE_TRUST_DOMAIN=' "$root/.env" | cut -d= -f2-)

$compose up -d --wait spire-server
server="$compose exec -T spire-server /opt/spire/bin/spire-server"
$server healthcheck >/dev/null
$server bundle show > "$root/infra/spire/bootstrap/bundle.crt"
# Retire the previous agent: its alias entry and its attested identity reference a consumed token.
for id in $($server entry show -spiffeID "spiffe://$domain/node/local" | awk '/Entry ID/ {print $4}'); do
  $server entry delete -entryID "$id" >/dev/null
done
for agent in $($server agent list | awk '/SPIFFE ID/ {print $4}'); do
  $server agent evict -spiffeID "$agent" >/dev/null
done
# -spiffeID gives the attested agent a stable alias, so workload entries survive token rotation.
token=$($server token generate \
  -spiffeID "spiffe://$domain/node/local" -ttl 600 | awk '/Token:/ {print $2}')
[ -n "$token" ] || { echo "failed to generate join token" >&2; exit 1; }

tmp="$root/.env.tmp"
sed "s|^SPIRE_JOIN_TOKEN=.*|SPIRE_JOIN_TOKEN=$token|" "$root/.env" > "$tmp" && mv "$tmp" "$root/.env"
echo "wrote fresh SPIRE_JOIN_TOKEN to .env (valid 10 minutes, single use)"

# A stale agent identity cannot be renewed with a consumed token: start the agent from a clean data dir.
$compose rm -sf spire-agent >/dev/null 2>&1 || true
docker volume rm custodian_spire-agent-data >/dev/null 2>&1 || true
$compose up -d --wait spire-agent
echo "spire-agent restarted with the new token"
