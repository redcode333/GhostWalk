# HydraDB 0.4.0: HTTP writes are rejected with `409 mutation_conflict` after the node restarts

Draft for filing on `hydra-db/hydradb`. Found while running GhostWalk against `ghcr.io/hydra-db/hydradb:0.4.0` (v0.4.0, commit `9166374`); reproduced with `curl` alone.

## Summary
After a restart of `graph-node`, single-statement HTTP writes (for example `MERGE (a)-[:REL]->(b)`) are rejected with

```json
{"error":{"code":"mutation_conflict","message":"DataFusion graph provider error: idempotency identity was reused for a different request"}}
```

for as long as the node runs, until every number the old process used has been passed. Reads keep working. Data is intact (the same happens with `CLOUD_PROVIDER=local` and with S3-compatible storage).

## Cause (from the source)
- `src/client/http.rs:698-700`: when the request body has no `query_id`, the server uses `format!("http-query-{}", NEXT_HTTP_QUERY_ID.fetch_add(1, ...))`. `NEXT_HTTP_QUERY_ID` is a process-wide `AtomicU64` starting at 1 (`http.rs:43`), so every process numbers its requests `http-query-1, 2, 3, ...`.
- `src/client/service.rs:3303-3306` (`query_context`): the durable mutation idempotency key is the caller-supplied key, a server-generated one (Bolt mints `bolt-mutation-v1-<ULID>`, `src/client/bolt.rs:976`), **or, when neither exists, `request.query_id`**. HTTP never sets one of the first two, so its idempotency key is `http-query-N`.
- `crates/graph-slate/src/provider/mutation.rs:990` (`statement_receipt_key_for`) stores a receipt per (scope, identity) in the cell's durable storage. A later request with the same identity and a different fingerprint fails with `GraphProviderError` "idempotency identity was reused for a different request" (`crates/graph-provider/src/error.rs:82`), surfaced as 409.
- After a restart the counter is back at 1, so the Nth write of the new process meets the receipt of the Nth write of the old one. The first request often passes (its receipt may be a different statement kind); the next ones collide.

The comment on `ClientQueryRequest::query_id` says it is an "ephemeral request handle ... not a durable mutation identity", but for HTTP it is used as one.

## Minimal reproduction
```bash
docker run -d --name hydradb -p 8443:8443 -p 9090:9090 --entrypoint /bin/sh \
  -e CLOUD_PROVIDER=local -e LOCAL_PATH=/var/cache/slatedb/store -e GRAPH_NAMESPACE=default -e GRAPH_ID=default -e GRAPH_CELL_ID=cell-0 \
  -e GRAPH_CELLS=cell-0 -e GRAPH_NODE_ID=node-0 -e GRAPH_BOLT_NODE_ADDRESSES=node-0=127.0.0.1:7687 -e GRAPH_ADVERTISED_BOLT_ADDR=127.0.0.1:7687 \
  -e GRAPH_DATA_CACHE_DIR=/var/cache/slatedb/cache -e GRAPH_AUTH_TOKEN_FILE=/tmp/graph/auth-token -e GRAPH_ALLOW_PLAINTEXT=true \
  -v hydra-data:/var/cache/slatedb ghcr.io/hydra-db/hydradb:0.4.0 \
  -c 'mkdir -p /var/cache/slatedb/store /var/cache/slatedb/cache && echo local-development-token-32-bytes > /tmp/graph/auth-token && exec graph-node'

T=local-development-token-32-bytes
q() { curl -s -X POST localhost:8443/v1/graphs/default/query -H "Authorization: Bearer $T" -H "X-Graph-Namespace: default" -H "Content-Type: application/json" -d "$1"; echo; }
edge() { echo "{\"cell_id\":\"cell-0\",\"query\":\"MERGE (a:Thing {id: \$a})-[:REL {w: \$w}]->(b:Thing {id: \$b})\",\"parameters\":{\"a\":$1,\"b\":$2,\"w\":0.5}}"; }

q '{"cell_id":"cell-0","query":"UNWIND $rows AS row MERGE (n {id: row.id}) SET n:Thing","parameters":{"rows":[{"id":1},{"id":2},{"id":3},{"id":4},{"id":5}]}}'
q "$(edge 1 2)"      # query_id: http-query-2   -> 200
q "$(edge 2 3)"      # query_id: http-query-3   -> 200
q "$(edge 3 4)"      # query_id: http-query-4   -> 200

docker restart hydradb        # wait for http://localhost:9090/readyz

q "$(edge 4 5)"      # query_id: http-query-1   -> 200 (a node batch used that number before)
q "$(edge 1 5)"      # query_id: http-query-2   -> 409 mutation_conflict (the old edge 1->2 used it)
q "$(edge 2 5)"      # query_id: http-query-3   -> 409
q "$(edge 3 5)"      # query_id: http-query-4   -> 409
```

Request that fails (token redacted):

```
POST /v1/graphs/default/query HTTP/1.1
Authorization: Bearer <redacted>
X-Graph-Namespace: default
Content-Type: application/json

{"cell_id":"cell-0","query":"MERGE (a:Thing {id: $a})-[:REL {w: $w}]->(b:Thing {id: $b})","parameters":{"a":1,"b":5,"w":0.5}}
```

Sending any of `Idempotency-Key`, `X-Request-Id`, `X-Idempotency-Key` does not help (they are not read). Giving the node a new `GRAPH_NODE_ID` on each boot does not help either.

## Workaround (what GhostWalk does)
Put a unique `"query_id"` in every request body (`"query_id": "gw-<uuid>"`), and re-send the same id when retrying the same request. With that, the request above is accepted after any number of restarts, and a re-sent request is still deduplicated. GhostWalk's regression test: `tests/test_hydra_restart.py`.

## Suggested fix
Do not use the process-local counter as a durable identity. Either generate HTTP mutation keys the way Bolt does (`http-mutation-v1-<ULID>`), or prefix the fallback with a per-boot nonce. Also consider documenting `query_id` as the HTTP idempotency key.

## Related
No existing issue found for this. Nearby: #204 (conflicts reported as internal errors), #196 (mutation/delete cycle in Docker local mode). v0.4.0 is the latest release (no newer fix).
