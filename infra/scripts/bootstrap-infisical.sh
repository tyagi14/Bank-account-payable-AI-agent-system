#!/bin/sh
# Creates the Infisical instance admin (user + org + "Instance Admin Identity"), then exchanges the
# bootstrap token for a Universal Auth credential, proves it with a real login, and revokes the
# bootstrap token so it is genuinely one-shot. Writes INFISICAL_ADMIN_CLIENT_ID/SECRET into .env.
# Requires: curl, python3.
set -eu
root=$(cd "$(dirname "$0")/../.." && pwd)
env="$root/.env"
url=${INFISICAL_URL:-http://localhost:18082}
get() { grep -E "^$1=" "$env" | head -1 | cut -d= -f2-; }
json() { python3 -c 'import sys,json
d = json.load(sys.stdin)
for k in sys.argv[1:]: d = d[k]
print(d)' "$@"; }
setenv() { tmp="$env.tmp"; sed "s|^$1=.*|$1=$2|" "$env" > "$tmp" && mv "$tmp" "$env"; }

body=$(printf '{"email":"%s","password":"%s","organization":"custodian"}' "$(get INFISICAL_ADMIN_EMAIL)" "$(get INFISICAL_ADMIN_PASSWORD)")
resp=$(curl -sf -X POST "$url/api/v1/admin/bootstrap" -H 'Content-Type: application/json' -d "$body") || {
  echo "bootstrap failed - the instance may already be bootstrapped (it only works once)" >&2; exit 1; }
token=$(echo "$resp" | json identity credentials token)
identity=$(echo "$resp" | json identity id)
echo "bootstrapped org $(echo "$resp" | json organization slug), admin user $(echo "$resp" | json user email)"

auth="Authorization: Bearer $token"
anyip='[{"ipAddress":"0.0.0.0/0"},{"ipAddress":"::/0"}]'
client_id=$(curl -sf -X POST "$url/api/v1/auth/universal-auth/identities/$identity" -H "$auth" -H 'Content-Type: application/json' \
  -d "{\"accessTokenTTL\":3600,\"accessTokenMaxTTL\":3600,\"accessTokenTrustedIps\":$anyip,\"clientSecretTrustedIps\":$anyip}" \
  | json identityUniversalAuth clientId)
client_secret=$(curl -sf -X POST "$url/api/v1/auth/universal-auth/identities/$identity/client-secrets" -H "$auth" \
  -H 'Content-Type: application/json' -d '{"description":"custodian admin","ttl":0}' | json clientSecret)

login=$(curl -sf -X POST "$url/api/v1/auth/universal-auth/login" -H 'Content-Type: application/json' \
  -d "{\"clientId\":\"$client_id\",\"clientSecret\":\"$client_secret\"}")
echo "universal auth login ok (session expires in $(echo "$login" | json expiresIn)s)"

token_id=$(echo "$token" | cut -d. -f2 | python3 -c "import sys,base64,json; s=sys.stdin.read().strip(); s+='='*(-len(s)%4); print(json.loads(base64.urlsafe_b64decode(s))['identityAccessTokenId'])")
curl -sf -X POST "$url/api/v1/auth/token-auth/tokens/$token_id/revoke" -H "$auth" >/dev/null \
  && echo "bootstrap token revoked" || echo "warning: could not revoke bootstrap token" >&2

setenv INFISICAL_ADMIN_CLIENT_ID "$client_id"
setenv INFISICAL_ADMIN_CLIENT_SECRET "$client_secret"
echo "wrote INFISICAL_ADMIN_CLIENT_ID / INFISICAL_ADMIN_CLIENT_SECRET to .env"
