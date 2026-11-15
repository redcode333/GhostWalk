#!/usr/bin/env bash
# Load test on the VM, from inside the api container (no network in the way), against a second API instance with the rate limit off.
#   ./deploy/loadtest_vm.sh > loadtest_vm.json && python scripts/merge_loadtest.py loadtest_vm.json
set -euo pipefail
cd "$(dirname "$0")/.."
DC="docker compose --env-file deploy/.env -f deploy/docker-compose.prod.yml"
$DC cp eval/loadtest.py api:/app/loadtest.py >/dev/null
$DC exec -T -e GW_MEASURED_ON=vm -e GW_RATE_LIMIT=0 -e GW_PUBLIC_DEMO=0 -e GW_STATE=/tmp/loadtest-state.json api sh -c '
  rm -f /tmp/loadtest-state.json
  uvicorn ghostwalk.api.app:app --host 127.0.0.1 --port 8001 --log-level warning > /tmp/lt-server.log 2>&1 &
  PID=$!
  for i in $(seq 1 60); do python -c "import urllib.request;urllib.request.urlopen(\"http://127.0.0.1:8001/api/health\",timeout=2)" 2>/dev/null && break; sleep 1; done
  python /app/loadtest.py --url http://127.0.0.1:8001 --levels 1,10,50,100 --seconds 10
  kill $PID'
