# Graph store vs SQL: the same query, side by side

GhostWalk's walk needs one primitive: the best (cheapest, cost = -ln w) path between two services within a hop limit, and for a whole verdict, that
reach for many (source, target) pairs at once. Both HydraDB and Postgres can answer it. This page shows the exact queries that run in this repo, what
they cost to write, and what they measured. Numbers are from `results.json` (`scale`, `ops.hydradb_latency`); regenerate with
`python scripts/render_graph_vs_sql.py`.

## One weighted best path

**HydraDB** (4 lines, 1 round trip): `algo.SPpaths` is native; hop limit, weights and cycle-freedom (paths are simple) are arguments.
```cypher
CALL algo.SPpaths({sourceNode: $s, targetNode: $t, relTypes: ['DEPENDS_ON'], relDirection: 'outgoing',
                   maxLen: $m, weightProp: 'cost', costProp: 'cost', pathCount: 1})
YIELD path, pathCost
RETURN path, pathCost
```

**Postgres** (8 lines, 1 round trip): a recursive CTE with a hop limit, a cycle guard, and an aggregate for the cheapest cost.
```sql
WITH RECURSIVE r(node, cost, depth, path) AS (
  SELECT %(s)s::int, 0::float8, 0, ARRAY[%(s)s::int]
  UNION ALL
  SELECT e.v, r.cost + e.cost, r.depth + 1, r.path || e.v
  FROM r JOIN scale_edge e ON e.sz = %(sz)s AND e.u = r.node
  WHERE r.depth < %(h)s AND NOT (e.v = ANY (r.path))
)
SELECT min(cost) FROM r WHERE node = %(t)s
```

## A whole verdict (reach for every candidate root and every alerting service)

**HydraDB**: 8 lines, **2 `MSpaths` requests** (+4 small reads for names, aliases, shortcuts and counters; the edges are never read back):
```cypher
-- 1) alerting services -> every component          -- 2) every component -> every candidate
CALL algo.MSpaths({sourceLabel: 'Component', sourceProperty: 'key',
                   sourceValues: [<alerting keys>] | [<all keys>],
                   targetValues: [<all keys>]      | [<candidate keys>],
                   relTypes: ['DEPENDS_ON'], relDirection: 'outgoing', maxLen: 5,
                   weightProp: 'cost', costProp: 'cost', pathCount: 1, pairwise: false, resultLimit: 100000})
YIELD path, pathCost
RETURN path, pathCost
```

**Postgres, batched**: 8 + 8 = 16 lines, **2 queries**. Many start rows, a cycle guard, a hop limit and a `GROUP BY` for the
cheapest cost per pair. The second is the first with the join reversed.
```sql
WITH RECURSIVE r(src, node, cost, depth, path) AS (
  SELECT s, s, 0::float8, 0, ARRAY[s] FROM unnest(%(srcs)s::int[]) AS s
  UNION ALL
  SELECT r.src, e.v, r.cost + e.cost, r.depth + 1, r.path || e.v
  FROM r JOIN scale_edge e ON e.sz = %(sz)s AND e.u = r.node
  WHERE r.depth < %(h)s AND NOT (e.v = ANY (r.path))
)
SELECT src, node, min(cost) FROM r WHERE node <> src GROUP BY src, node
```
```sql
WITH RECURSIVE r(src, node, cost, depth, path) AS (
  SELECT s, s, 0::float8, 0, ARRAY[s] FROM unnest(%(srcs)s::int[]) AS s
  UNION ALL
  SELECT r.src, e.u, r.cost + e.cost, r.depth + 1, r.path || e.u
  FROM r JOIN scale_edge e ON e.sz = %(sz)s AND e.v = r.node
  WHERE r.depth < %(h)s AND NOT (e.u = ANY (r.path))
)
SELECT src, node, min(cost) FROM r WHERE node <> src GROUP BY src, node
```

**Postgres, per node** (what the store-swap run used, because it is the simplest code behind the store interface): one CTE per reach, so
**48 round trips per verdict** on average (alerting services + candidates, measured on the DEV companies) instead of 2.

| approach | lines | round trips per verdict |
|---|---|---|
| HydraDB, read the graph back (cold) | 5 `MATCH` reads | 5 |
| HydraDB, cached by revision | 1 revision read, 5 more only when it changed | 1 (hit) |
| HydraDB, in-DB (2 `MSpaths`) | 8 | 2 + 4 small reads |
| Postgres, batched CTEs | 16 | 2 |
| Postgres, one CTE per node | 8 | ~48 |

## What it measured (ms, p50 / p95, loopback docker, same machine)

One best path between random reachable pairs (40 pairs per cell, both stores checked against an in-process Bellman-Ford: every cost identical):

| services | edges | HydraDB, 3 hops | Postgres, 3 hops | HydraDB, 5 hops | Postgres, 5 hops |
|---|---|---|---|---|---|
| 100 | 233 | 1.7 / 2.9 | 0.4 / 0.8 | 2.1 / 3.5 | 0.4 / 0.8 |
| 1000 | 2,355 | 5.4 / 11 | 1.0 / 4.1 | 3.0 / 5.8 | 0.8 / 1.7 |
| 5000 | 11,959 | 4.1 / 6.5 | 0.5 / 0.8 | 3.2 / 7.6 | 0.5 / 0.6 |

Whole verdict (the first incidents with several alerts; rankings identical to the in-memory engine in every case, tolerance 1e-9), p50:

| services | HydraDB read graph back (cold) | HydraDB in-DB (MSpaths) | Postgres batched CTEs |
|---|---|---|---|
| 100 | 40 ms | 234 ms | 3.5 ms |
| 1000 | 475 ms | 1905 ms | 12 ms |
| 5000 | 2472 ms | 97623 ms | 210 ms |

**Per query, warm** (200 timed requests after 20 warm-up, one at a time, the median DEV company, p50 / p95 ms):

| query | HydraDB | Postgres |
|---|---|---|
| 1-hop neighbours | 2.7 / 3.8 | 0.3 / 0.5 |
| best path, 3 hops | 0.5 / 0.8 | 0.4 / 0.5 |
| best path, 5 hops | 0.6 / 1.0 | 0.5 / 0.7 |
| edge-weight write | 23 / 24 | 0.8 / 1.1 |

**Per verdict, warm** (180 verdicts on 3 DEV companies of 42 to 105 services, p50 / p95 ms): HydraDB cached hit 1.8 / 2.9,
cached miss 36 / 66 (every incident in the online loop is a miss: each follows a learner write),
cold read 40 / 64, in-DB 144 / 269;
Postgres, two batched CTEs 2.8 / 4.3.
Machine: Windows-11-10.0.26300-SP0, 16 logical CPUs, 7.6 GB RAM; HydraDB and Postgres in docker, reached over published loopback ports.

**Before a transport fix, every HydraDB request took about 45 ms** (the path-query rows above read 48 ms at 1,000 services and 3 hops).
The cause was not HydraDB and not graph work: Per-request overhead in the client-to-published-port hop, not HydraDB and not graph work. HydraDB answers in 0.1 to 0.9 ms (server-side, from its /metrics histogram) and its response always arrives in one read. Clients that write the request headers and body separately (httpx, http.client, HTTP/2) took ~45 ms through Docker Desktop's published port on Windows; the same clients inside the docker network took 0.3 to 1.5 ms. A client that sends headers+body in ONE write took 0.4 ms through the same published port, and so did Bolt. Client-side TCP_NODELAY did not change it (so it is not simply the client's Nagle), which points at the proxy hop reacting to the split writes.
Evidence and raw data: `docs/measurements/`. The adapter now keeps one connection and writes each request in one segment (`ghostwalk/graph/fasthttp.py`).

## Reading it honestly
- **Postgres still wins on latency here, by a smaller margin than first measured.** With the transport fixed, HydraDB's `SPpaths` takes a few milliseconds
  (about 0.5 ms on a 75-service company, 2 ms at 100 services, 3 to 5 ms at 1,000 to 5,000 services) and a recursive CTE under 1 ms, both with identical costs. Whole verdicts: Postgres' two
  batched CTEs are faster than a HydraDB read-back or an in-DB verdict at every size, and a Postgres write is about 0.8 ms against about 22 ms for HydraDB (server-side commit).
  The first measurement (about 48 ms for every HydraDB query, flat across sizes) was a client/proxy artefact on this laptop, now diagnosed and fixed.
- **Accuracy is the same.** Postgres with recursive queries gets the same AC@1 as HydraDB (store swap, delta 0.0). The gain over key-value (1 hop) and
  vector search comes from the multi-hop weighted walk, not from the product that stores the graph.
- **Pushing the verdict into HydraDB did not help.** Reading the graph back is cheaper than asking HydraDB for every path, and at 5,000 services
  `MSpaths` returns so much path data that one verdict needs several requests at its 64 MB response buffer.
- **Where HydraDB is the better fit:** native weighted path algorithms (`SPpaths`, `SSpaths`, `MSpaths`) as one query instead of a hand-written CTE, and a graph
  model without an edge table. Those are conveniences and a different operating model, not a measured speed or accuracy advantage in this benchmark.
- Caveats: one machine, both databases in docker over loopback, HydraDB writes cost about 65 ms each (so loading and learning are slow), and the graphs come
  from our generator. A denser graph or a much larger hop limit could make the CTE enumerate far more paths; we did not find that regime.
