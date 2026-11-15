#!/usr/bin/env bash
# Start one local HydraDB graph-node backed by a folder (no S3 needed).
# Usage: bash start_node.sh /path/to/hydradb-repo
set -euo pipefail
REPO="${1:-$HOME/hydradb}"
DATA="$HOME/.hydradb-test"
mkdir -p "$DATA/store" "$DATA/cache"
printf '%s\n' 'local-development-token-32-bytes' > "$DATA/auth-token"

export CLOUD_PROVIDER=local              # "S3" = a local folder
export LOCAL_PATH="$DATA/store"          # <- this folder is the "locker"
export GRAPH_NAMESPACE=default
export GRAPH_ID=default
export GRAPH_CELL_ID=cell-0
export GRAPH_CELLS=cell-0
export GRAPH_NODE_ID=node-0
export GRAPH_BOLT_NODE_ADDRESSES=node-0=127.0.0.1:7687
export GRAPH_ADVERTISED_BOLT_ADDR=127.0.0.1:7687
export GRAPH_DATA_CACHE_DIR="$DATA/cache"
export GRAPH_AUTH_TOKEN_FILE="$DATA/auth-token"
export GRAPH_ALLOW_PLAINTEXT=true
export RUST_MIN_STACK=33554432
export GRAPH_USAGE_REPORT_ENABLED=false  # node phones home by default; turn it off

exec "$REPO/target/debug/graph-node"
