#!/bin/sh
# docker compose with all six governance-layer files applied. Usage: infra/scripts/compose.sh up -d
set -eu
root=$(cd "$(dirname "$0")/../.." && pwd)
c="$root/infra/compose"
exec docker compose --env-file "$root/.env" --project-directory "$c" \
  -f "$c/docker-compose.base.yml" -f "$c/docker-compose.identity.yml" -f "$c/docker-compose.data.yml" \
  -f "$c/docker-compose.model.yml" -f "$c/docker-compose.app.yml" -f "$c/docker-compose.observability.yml" "$@"
