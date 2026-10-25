#!/bin/sh
# Print a Keycloak access token for one of the realm's operators (clerk | controller | cfo),
# using the custodian-cli client's direct-grant flow. Local development only.
# Usage: TOKEN=$(infra/scripts/token.sh controller)
set -eu
root=$(cd "$(dirname "$0")/../.." && pwd)
user=${1:?usage: token.sh clerk|controller|cfo}
var=$(printf 'KC_%s_PASSWORD' "$user" | tr '[:lower:]' '[:upper:]')
password=$(grep "^$var=" "$root/.env" | cut -d= -f2-)
[ -n "$password" ] || { echo "$var is not set in .env" >&2; exit 1; }
curl -sf http://127.0.0.1:18081/realms/custodian/protocol/openid-connect/token \
  -d grant_type=password -d client_id=custodian-cli -d username="$user" --data-urlencode password="$password" \
  | python3 -c 'import json, sys; print(json.load(sys.stdin)["access_token"])'
