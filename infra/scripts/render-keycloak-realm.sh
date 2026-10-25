#!/bin/sh
# Fills the realm template with values from .env. Run before Keycloak's first start.
set -eu
root=$(cd "$(dirname "$0")/../.." && pwd)
get() { grep -E "^$1=" "$root/.env" | head -1 | cut -d= -f2-; }
mkdir -p "$root/infra/keycloak/import"
sed -e "s|\${KC_CLERK_PASSWORD}|$(get KC_CLERK_PASSWORD)|" \
    -e "s|\${KC_CONTROLLER_PASSWORD}|$(get KC_CONTROLLER_PASSWORD)|" \
    -e "s|\${KC_CFO_PASSWORD}|$(get KC_CFO_PASSWORD)|" \
    "$root/infra/keycloak/realm.template.json" > "$root/infra/keycloak/import/custodian-realm.json"
echo "rendered infra/keycloak/import/custodian-realm.json"
