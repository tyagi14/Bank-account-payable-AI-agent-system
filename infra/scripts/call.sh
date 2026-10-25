#!/bin/sh
# Call an internal (unpublished) service's HTTP API from inside its own container.
# Usage: infra/scripts/call.sh <service> <METHOD> <path> [json-body]
#   infra/scripts/call.sh policy-service POST /authorize '{"principal": ...}'
#   infra/scripts/call.sh custodian-audit-log GET /verify
set -eu
here=$(cd "$(dirname "$0")" && pwd)
[ $# -ge 3 ] || { echo "usage: $0 <service> <METHOD> <path> [json-body]" >&2; exit 2; }
service=$1 method=$2 path=$3 body=${4:-}
exec "$here/compose.sh" exec -T "$service" python -c '
import json, sys, urllib.error, urllib.request
method, path, body = sys.argv[1], sys.argv[2], sys.argv[3]
req = urllib.request.Request("http://127.0.0.1:8000" + path, method=method, data=body.encode() or None,
                             headers={"Content-Type": "application/json"})
try:
    with urllib.request.urlopen(req, timeout=60) as resp:
        status, raw = resp.status, resp.read()
except urllib.error.HTTPError as err:
    status, raw = err.code, err.read()
try:
    out = json.dumps(json.loads(raw), indent=2)
except ValueError:
    out = raw.decode()
print(f"HTTP {status}")
print(out)
sys.exit(0 if status < 400 else 1)
' "$method" "$path" "$body"
