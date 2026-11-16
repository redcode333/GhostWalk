# Performance and latency

Generated from [`results.json`](../results.json) by `scripts/update_readme_numbers.py`. Every number is labelled with the machine it was measured on. Nothing here is a claim about other hardware.

## Machines

| machine | what | how it was used |
|---|---|---|
| laptop | Windows-11-10.0.26300, 16 logical CPUs, 7.6 GB RAM, Python 3.12.4 | client on the host; HydraDB and Postgres in Docker Desktop containers through published ports (transport fixed, see below) |
| VM | AWS m7i-flex.large, Intel(R) Xeon(R) Platinum 8488C, 2 vCPU, 7.6 GB RAM, Linux 7.0.0-1016-aws, Python 3.12.16 | client in the API container, HydraDB on the same Docker network (no proxy hop); HydraDB's data in MinIO or on local disk, as labelled |

## Per query on HydraDB

One request at a time after a warm-up (p50 / p95), on a generated or DEV company:

| query (one at a time, after warm-up) | HydraDB, laptop | Postgres, laptop | HydraDB, VM, MinIO | HydraDB, VM, local disk |
|---|---|---|---|---|
| 1-hop neighbours | 2.7 ms / 3.8 ms | 0.27 ms / 0.48 ms | 2.8 ms / 4.4 ms | 2.9 ms / 4.3 ms |
| best path, 3 hops | 0.53 ms / 0.84 ms | 0.37 ms / 0.53 ms | 0.39 ms / 0.53 ms | not measured |
| best path, 5 hops | 0.57 ms / 1.0 ms | 0.45 ms / 0.68 ms | 0.41 ms / 0.60 ms | not measured |
| edge-weight write | 23 ms / 24 ms | 0.77 ms / 1.1 ms | 22 ms / 24 ms | not measured |

The laptop columns are the median DEV company (HydraDB and Postgres side by side). The VM columns come from `deploy/measure_vm.py`: generated companies, the client in the API container, HydraDB on the same Docker network.

## Per verdict

| verdict | laptop (30 TEST companies / DEV companies) | VM, HydraDB on MinIO |
|---|---|---|
| in memory (no store) | 0.21 ms / 0.76 ms | 0.06 ms / 0.08 ms |
| HydraDB, cache hit (nothing written since the last verdict) | 1.8 ms / 2.9 ms | 0.86 ms / 1.3 ms |
| HydraDB, during learning (write-through cache, every incident) | 2.3 ms / 3.8 ms | 1.3 ms / 1.8 ms |
| HydraDB, cold read of the whole graph | 40 ms / 64 ms | 380 ms / 464 ms |
| learning write (after the verdict, off the verdict path) | 403 ms / 1,071 ms | 559 ms / 1,520 ms |

- **In memory** is the engine alone on an in-process graph.
- **Cache hit** is a revision check against HydraDB (one id-anchored read) plus the walk on the cached graph.
- **During learning** is every incident of the online loop: the learner writes to HydraDB and applies the identical change to the cached graph, so the next verdict is still a cache hit.
- **Cold read** reads the whole graph back from HydraDB every time. It is the cost of not having the cache, and it is why the cache exists.
- **Learning write** is everything the learner commits after a verdict (the graph change and the memory: incident, alerts, postmortem, lessons, links). It runs in a background queue and is never on the verdict path.

## Scale

| services | engine verdict (in memory) | HydraDB 3 hops | Postgres 3 hops | HydraDB 5 hops | Postgres 5 hops | whole verdict p50: HydraDB read-back / in-DB / Postgres |
|---|---|---|---|---|---|---|
| 100 | 0.63 ms / 0.84 ms | 1.7 ms / 2.9 ms | 0.42 ms / 0.83 ms | 2.1 ms / 3.5 ms | 0.42 ms / 0.75 ms | 40 ms / 234 ms / 3.5 ms |
| 1000 | 15 ms / 22 ms | 5.4 ms / 11 ms | 0.98 ms / 4.1 ms | 3.0 ms / 5.8 ms | 0.76 ms / 1.7 ms | 475 ms / 1,905 ms / 12 ms |
| 5000 | 85 ms / 116 ms | 4.1 ms / 6.5 ms | 0.53 ms / 0.83 ms | 3.2 ms / 7.6 ms | 0.48 ms / 0.64 ms | 2,472 ms / 97,623 ms / 210 ms |

Synthetic layered graphs from one generator (gwsim layered, tier mix kept); the engine's budget rule was: stop if p95 at 1,000 services < 100 ms; port walk()'s Bellman-Ford to Rust only if p95 at 5,000 services > 250 ms. Whole-verdict columns: HydraDB read-back (read the graph, walk in the engine), in-database (two `MSpaths` queries, measured and not used), Postgres (two batched recursive CTEs).

## Load test

| concurrent clients | requests / s | latency p50 / p95 / p99 | errors | API container CPU (% of one core) | API container memory |
|---|---|---|---|---|---|
| 1 | 91 | 11 ms / 18 ms / 24 ms | 0 | 98% | 151 MB |
| 10 | 45 | 219 ms / 272 ms / 306 ms | 0 | 104% | 158 MB |
| 50 | 33 | 1,576 ms / 1,636 ms / 1,663 ms | 0 | 108% | 164 MB |
| 100 | 26 | 3,451 ms / 5,869 ms / 5,992 ms | 0 | 120% | 176 MB |

Each level ran 10 s against `POST /v1/alerts/demo` inside the API container on the VM (2 vCPUs), rate limit off; every request is a full verdict that is also recorded and saved.

Reproduce: `make loadtest URL=http://127.0.0.1:8000` against a server started with `GW_RATE_LIMIT=0`, or on the VM `deploy/loadtest_vm.sh`.

## Graph-memory retrieval

|  | graph (HydraDB) | vector (pgvector) | keyword (TF-IDF) |
|---|---|---|---|
| hit@5, repeat incidents (n=1,175) | 84.3% [82.1, 86.7] | 87.3% [85.0, 89.3] | 89.5% [87.5, 91.5] |
| MRR, repeat incidents | 0.709 [0.674, 0.744] | 0.721 [0.697, 0.745] | 0.746 [0.718, 0.770] |
| related@5, novel incidents (n=595) | 20.2% [17.3, 23.3] | 24.5% [20.4, 28.5] | 25.4% [21.4, 29.1] |
| retrieval latency p50 / p95 | 3.9 ms / 7.5 ms | 1.3 ms / 1.8 ms | 0.56 ms / 1.0 ms |

On repeat incidents, graph memory is behind vector search (−3.0 pts (95% CI −5.8 to −0.1)) and behind TF-IDF (−5.2 pts (95% CI −8.0 to −2.4)). Graph retrieval first took 164 ms p50 as a HydraDB query per step; now it expands the neighbourhood on the revision-checked cached graph and keeps a per-revision index (3.9 ms p50), returning identical lists for all 1,770 incidents.

## The transport diagnosis

Per-request overhead in the client-to-published-port hop, not HydraDB and not graph work. HydraDB answers in 0.1 to 0.9 ms (server-side, from its /metrics histogram) and its response always arrives in one read. Clients that write the request headers and body separately (httpx, http.client, HTTP/2) took ~45 ms through Docker Desktop's published port on Windows; the same clients inside the docker network took 0.3 to 1.5 ms. A client that sends headers+body in ONE write took 0.4 ms through the same published port, and so did Bolt. Client-side TCP_NODELAY did not change it (so it is not simply the client's Nagle), which points at the proxy hop reacting to the split writes.

| where | client | 1-hop query p50 |
|---|---|---|
| host (Windows) -> published port | httpx keep-alive | 47 ms |
| host (Windows) -> published port | httpx keep-alive + TCP_NODELAY | 47 ms |
| host (Windows) -> published port | http.client keep-alive | 44 ms |
| host (Windows) -> published port | http.client new connection | 3.0 ms |
| host (Windows) -> published port | httpx HTTP/2 | 45 ms |
| host (Windows) -> published port | raw socket, one write | 0.64 ms |
| host (Windows) -> published port | Bolt (neo4j driver) | 0.97 ms |
| inside the docker network | httpx keep-alive | 0.85 ms |
| inside the docker network | http.client keep-alive | 0.49 ms |
| inside the docker network | raw socket, one write | 0.41 ms |
| inside the docker network | Bolt (neo4j driver) | 0.63 ms |

Also fixed: the revision check is id-anchored (about 1 ms instead of 12 ms); a graph read issues its independent queries together (about 40 ms instead of 85 ms). Raw data: `docs/measurements/`. The adapter sends each request in one write over a persistent connection (`ghostwalk/graph/fasthttp.py`).

## Reproduce

| what | command |
|---|---|
| engine at 100, 1,000, 5,000 services | `make bench` |
| HydraDB per query and per verdict, with Postgres | `make bench-hydra` (needs `docker compose --profile eval up -d hydradb postgres`) |
| load test | `make loadtest URL=...` |
| VM latency | `deploy/measure_vm.py`, then `scripts/merge_vm_latency.py` |
| graph-memory retrieval | `python eval/memory_retrieval.py --split test` |
