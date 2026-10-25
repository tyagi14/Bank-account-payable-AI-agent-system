#!/bin/sh
# Run one governance layer on its own (it pulls in only the layers it depends on).
# Usage: infra/scripts/layer.sh identity up -d
set -eu
root=$(cd "$(dirname "$0")/../.." && pwd)
layer=$1; shift
COMPOSE_IGNORE_ORPHANS=true exec docker compose --env-file "$root/.env" --project-directory "$root/infra/compose" \
  -f "$root/infra/compose/docker-compose.$layer.yml" "$@"
