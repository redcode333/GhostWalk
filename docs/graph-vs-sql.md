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
| 100 | 233 | 48 / 51 | 0.9 / 1.5 | 48 / 53 | 0.7 / 1.5 |
| 1000 | 2,355 | 48 / 52 | 0.8 / 1.8 | 49 / 52 | 0.8 / 1.8 |
| 5000 | 11,959 | 49 / 60 | 0.8 / 2.1 | 51 / 56 | 0.7 / 1.1 |

Whole verdict (the first incidents with several alerts; rankings identical to the in-memory engine in every case, tolerance 1e-9), p50:

| services | HydraDB read graph back (cold) | HydraDB in-DB (MSpaths) | Postgres batched CTEs |
|---|---|---|---|
| 100 | 265 ms | 466 ms | 4.0 ms |
| 1000 | 681 ms | 1666 ms | 34 ms |
| 5000 | 4235 ms | 102605 ms | 221 ms |

HydraDB on the 3 DEV companies (42 to 105 services), 180 verdicts: cold p50 289 / p95 328 ms,
cached hit p50 55 / p95 64 ms (a miss, which is every incident in the online loop because each one
follows a learner write: p50 346 ms), in-DB p50 400 / p95 510 ms.

## Reading it honestly
- **Postgres keeps up, and wins on latency here.** A recursive CTE answers a bounded weighted path in about 1 ms at every size tried and never exploded (no
  timeouts at 5,000 services and 5 hops: this graph family has small out-degree, so the number of paths within five hops stays small). HydraDB's `SPpaths`
  takes about 50 ms regardless of size, which is per-request overhead of this single-node setup rather than search time. Both return the exact same costs.
- **Accuracy is the same.** Postgres with recursive queries gets the same AC@1 as HydraDB (store swap, delta 0.0). The gain over key-value (1 hop) and
  vector search comes from the multi-hop weighted walk, not from the product that stores the graph.
- **Pushing the verdict into HydraDB did not help.** Reading the graph back is cheaper than asking HydraDB for every path, and at 5,000 services
  `MSpaths` returns so much path data that one verdict needs several requests at its 64 MB response buffer.
- **Where HydraDB is the better fit:** native weighted path algorithms (`SPpaths`, `SSpaths`, `MSpaths`) as one query instead of a hand-written CTE, and a graph
  model without an edge table. Those are conveniences and a different operating model, not a measured speed or accuracy advantage in this benchmark.
- Caveats: one machine, both databases in docker over loopback, HydraDB writes cost about 65 ms each (so loading and learning are slow), and the graphs come
  from our generator. A denser graph or a much larger hop limit could make the CTE enumerate far more paths; we did not find that regime.
