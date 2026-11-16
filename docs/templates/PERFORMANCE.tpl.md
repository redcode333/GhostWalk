# Performance and latency

Generated from [`results.json`](../results.json) by `scripts/update_readme_numbers.py`. Every number is labelled with the machine it was measured on. Nothing here is a claim about other hardware.

## Machines

{{table_machines}}

## Per query on HydraDB

One request at a time after a warm-up (p50 / p95), on a generated or DEV company:

{{table_queries}}

The laptop columns are the median DEV company (HydraDB and Postgres side by side). The VM columns come from `deploy/measure_vm.py`: generated companies, the client in the API container, HydraDB on the same Docker network.

## Per verdict

{{table_verdicts}}

- **In memory** is the engine alone on an in-process graph.
- **Cache hit** is a revision check against HydraDB (one id-anchored read) plus the walk on the cached graph.
- **During learning** is every incident of the online loop: the learner writes to HydraDB and applies the identical change to the cached graph, so the next verdict is still a cache hit.
- **Cold read** reads the whole graph back from HydraDB every time. It is the cost of not having the cache, and it is why the cache exists.
- **Learning write** is everything the learner commits after a verdict (the graph change and the memory: incident, alerts, postmortem, lessons, links). It runs in a background queue and is never on the verdict path.

## Scale

{{table_scale}}

Synthetic layered graphs from one generator ({{scale_engine_note}}); the engine's budget rule was: {{engine_gate}}. Whole-verdict columns: HydraDB read-back (read the graph, walk in the engine), in-database (two `MSpaths` queries, measured and not used), Postgres (two batched recursive CTEs).

## Load test

{{table_load}}

Reproduce: `make loadtest URL=http://127.0.0.1:8000` against a server started with `GW_RATE_LIMIT=0`, or on the VM `deploy/loadtest_vm.sh`.

## Graph-memory retrieval

{{table_memory}}

{{memory_sentence}}

## The transport diagnosis

{{transport_cause}}

{{transport_evidence}}

Also fixed: {{transport_also_fixed}}. Raw data: `docs/measurements/`. The adapter sends each request in one write over a persistent connection (`ghostwalk/graph/fasthttp.py`).

## Reproduce

| what | command |
|---|---|
| engine at {{scale_sizes}} services | `make bench` |
| HydraDB per query and per verdict, with Postgres | `make bench-hydra` (needs `docker compose --profile eval up -d hydradb postgres`) |
| load test | `make loadtest URL=...` |
| VM latency | `deploy/measure_vm.py`, then `scripts/merge_vm_latency.py` |
| graph-memory retrieval | `python eval/memory_retrieval.py --split test` |
