"""Regenerates the number-bearing README blocks from results.json (so they cannot go stale):
   - the proof headline at the top (between <!-- proof:begin --> and <!-- proof:end -->)
   - the '## HydraDB (live)' section at the end
   python scripts/update_readme_numbers.py"""
import json, pathlib
ROOT = pathlib.Path(__file__).resolve().parent.parent
r = json.loads((ROOT / "results.json").read_text(encoding="utf8"))
sw = r["store_swap"]
b = sw["backends"]
ref = sw["reference"]
pts = lambda x: f"{x * 100:+.1f}".replace("-", "−")
ci = lambda c: f"{pts(c['ci95'][0])} to {pts(c['ci95'][1])}"
n = r["meta"]["companies"]
refname = "HydraDB" if ref == "hydradb" else "the in-memory graph"
kv, vec, cte = b["kv_1hop"]["delta_vs_reference"], b["pgvector"]["delta_vs_reference"], b["pg_cte"]["delta_vs_reference"]
g = b[ref]["ac1"]

proof = f"""<!-- proof:begin -->
**Evaluated on {n} held-out companies never used for development or tuning; learning starts from zero at each company.**

**Replace graph traversal and it fails: key-value (1 hop) {pts(kv['point'])} pts, vector search {pts(vec['point'])} pts** (top-1 accuracy, {refname} as the reference;
95% CIs {ci(kv)} and {ci(vec)}). GhostWalk gets {g['point'] * 100:.1f}% against {b['pgvector']['ac1']['point'] * 100:.1f}% for vector search over postmortem text.

A relational database with recursive queries matches accuracy ({pts(cte['point'])} pts), as expected: the gain comes from multi-hop graph walks, not from which product stores the graph.
We use HydraDB for its native weighted path algorithms. In our latency measurements Postgres is faster, not slower (about 1 ms against 2 to 5 ms per path query once HydraDB's transport was fixed) (see [graph vs SQL](docs/graph-vs-sql.md)).

![GhostWalk proof card](docs/proof-card.png)
<!-- proof:end -->"""

hl = r["ops"]["hydradb_latency"]
w = hl["warm"]
before_sc = r["scale_before_transport_fix"]["path_query"]["sizes"]
sc = r["scale"]["path_query"]["sizes"]
pv = r["scale"]["postgres_verdict"]["sizes"]
f = lambda x: f"{x:.0f}" if x >= 10 else f"{x:.1f}"
rows = []
for k, lab in (("hydradb", "HydraDB v0.4.0 (published image)"), ("pg_cte", "Postgres recursive CTE"), ("kv_1hop", "Key-value, 1 hop (Redis)"), ("pgvector", "pgvector nearest postmortem"), ("inmemory", "In-memory graph")):
    if k not in b:
        continue
    v = b[k]
    d = "reference" if v["delta_vs_reference"] is None else f"{pts(v['delta_vs_reference']['point'])} ({ci(v['delta_vs_reference'])})"
    rows.append(f"| {lab} | {v['ac1']['point']:.3f} | {d} | {v['verdict_ms_p50']:.1f} ms | {v['verdict_ms_p95']:.1f} ms |")
scale_rows = "\n".join(
    f"| {k} | {f(e['path_query']['hops_3']['hydradb']['p50'])} / {f(e['path_query']['hops_3']['hydradb']['p95'])} | {f(e['path_query']['hops_3']['postgres']['p50'])} / {f(e['path_query']['hops_3']['postgres']['p95'])} | "
    f"{f(e['path_query']['hops_5']['hydradb']['p50'])} / {f(e['path_query']['hops_5']['hydradb']['p95'])} | {f(e['path_query']['hops_5']['postgres']['p50'])} / {f(e['path_query']['hops_5']['postgres']['p95'])} | "
    f"{f(e['verdict']['cold_read']['p50'])} / {f(e['verdict']['in_db']['p50'])} / {f(pv[k]['p50'])} |" for k, e in sc.items())
hist = r["meta"].get("ac1_history", [])
hist_txt = "\n".join(f"  - {h['engine']}: {h['hits']}/{h['of']} top-1 hits ({h['hits'] / h['of']:.4f})" for h in hist)

hydra = f"""
## HydraDB (live)
GhostWalk runs against HydraDB's own published image, `ghcr.io/hydra-db/hydradb:0.4.0` (the one `charts/hydradb` references): `docker compose up -d hydradb`.
(If you restart the container, remove its volume first, `docker compose down hydradb -v`: a restarted node rejects writes whose request ids it has seen.)
`ghostwalk/graph/hydra.py` is written against the dialect in `USING-HYDRADB.md` and checked on a live node: edgeless nodes need the node batch, writes accept only one-hop
edge patterns, `MERGE` cannot be followed by another clause so weight changes are `MATCH ... SET`, no batch shape writes edge properties (each edge is one request, about
65 ms), results are **paginated** (default 1,024 rows; the adapter follows `next_cursor` to the end), `algo.SPpaths` minimises `weightProp` while `costProp` is only
the cost it reports, and `algo.MSpaths` selects by a property shared across companies, so each node carries a per-company `key`.

- **Parity:** the HydraDB-vs-in-memory tests (`tests/test_parity.py`, 8) check identical rankings and scores, identical final graph state, path costs equal to the in-memory best path,
  the cache re-reading only when the revision changes, and in-DB verdicts matching in-memory rankings.
- **Why it was 48 ms per request, and the fix:** HydraDB answers in 0.1 to 0.9 ms (its own `/metrics` histogram) and its response arrives in one read. Clients that write the request headers
  and body separately (httpx, http.client, HTTP/2) took ~45 ms through Docker Desktop's published port on Windows, the same clients inside the docker network took 0.3 to 1.5 ms, and a client
  that sends headers and body in one write took 0.4 ms through the same port (so did Bolt). Client-side `TCP_NODELAY` did not help. The adapter now uses a persistent connection with one write per request
  (`ghostwalk/graph/fasthttp.py`); data in `docs/measurements/`, full results in `results.json` `ops.hydradb_latency.diagnosis`.
- **Warm latency after the fix** (this laptop: {w['machine']['platform']}, {w['machine']['cpus']} CPUs, {w['machine'].get('ram_gb', '?')} GB; client on the host, HydraDB and Postgres in docker; 200 timed requests after 20 warm-up; p50 / p95 ms):

| | HydraDB | Postgres |
|---|---|---|
| 1-hop neighbours | {f(w['per_query']['one_hop']['hydradb']['p50'])} / {f(w['per_query']['one_hop']['hydradb']['p95'])} | {f(w['per_query']['one_hop']['postgres']['p50'])} / {f(w['per_query']['one_hop']['postgres']['p95'])} |
| best path, 3 hops | {f(w['per_query']['path_3_hops']['hydradb']['p50'])} / {f(w['per_query']['path_3_hops']['hydradb']['p95'])} | {f(w['per_query']['path_3_hops']['postgres']['p50'])} / {f(w['per_query']['path_3_hops']['postgres']['p95'])} |
| best path, 5 hops | {f(w['per_query']['path_5_hops']['hydradb']['p50'])} / {f(w['per_query']['path_5_hops']['hydradb']['p95'])} | {f(w['per_query']['path_5_hops']['postgres']['p50'])} / {f(w['per_query']['path_5_hops']['postgres']['p95'])} |
| edge-weight write | {f(w['per_query']['edge_write']['hydradb']['p50'])} / {f(w['per_query']['edge_write']['hydradb']['p95'])} | {f(w['per_query']['edge_write']['postgres']['p50'])} / {f(w['per_query']['edge_write']['postgres']['p95'])} |
| verdict: cached hit | {f(w['per_verdict']['cached_hit']['p50'])} / {f(w['per_verdict']['cached_hit']['p95'])} | |
| verdict: cached miss (every incident in the online loop) | {f(w['per_verdict']['cached_miss']['p50'])} / {f(w['per_verdict']['cached_miss']['p95'])} | |
| verdict: cold read | {f(w['per_verdict']['cold']['p50'])} / {f(w['per_verdict']['cold']['p95'])} | |
| verdict: in-DB (two `MSpaths`) | {f(w['per_verdict']['in_db']['p50'])} / {f(w['per_verdict']['in_db']['p95'])} | |
| verdict: Postgres, two batched CTEs | | {f(w['postgres_per_verdict']['p50'])} / {f(w['postgres_per_verdict']['p95'])} |

  HydraDB's verdict p50 is under 20 ms only on a **cache hit** ({f(w['per_verdict']['cached_hit']['p50'])} ms); a miss or cold read is {f(w['per_verdict']['cold']['p50'])} to {f(w['per_verdict']['cached_miss']['p50'])} ms, and an in-DB verdict
  {f(w['per_verdict']['in_db']['p50'])} ms. In-DB verdicts matched the in-memory engine in {w['in_db_matches_in_memory']['checked'] - w['in_db_matches_in_memory']['mismatches']}/{w['in_db_matches_in_memory']['checked']} cases. Before the fix: cold p50 / p95 was
  {f(hl['before_transport_fix']['cold']['p50'])} / {f(hl['before_transport_fix']['cold']['p95'])} ms. HydraDB writes still cost about {f(w['per_query']['edge_write']['hydradb']['p50'])} ms each (server-side commit), so loading and learning are the slow part.
- **Path queries at scale, after the transport fix** (synthetic graphs, same generator; p50 / p95 ms; both stores return the exact same cost every time; before the fix HydraDB read about 48 ms at every size):

| services | HydraDB 3 hops | Postgres 3 hops | HydraDB 5 hops | Postgres 5 hops | whole verdict p50: HydraDB read / in-DB / Postgres |
|---|---|---|---|---|---|
{scale_rows}

  **Postgres is still faster at every size** (under 1 ms to about 1 ms per path against 2 to 5 ms for HydraDB; no CTE blow-up at 5 hops on these graphs). Pushing the whole verdict into HydraDB is slower than reading
  the graph back, and at 5,000 services `MSpaths` needs several requests to stay under its 64 MB response buffer. HydraDB's role here is native weighted path algorithms, not speed or accuracy.
  Side-by-side queries and round trips: [docs/graph-vs-sql.md](docs/graph-vs-sql.md).

Store swap on the TEST split, run once, same incidents, ΔAC@1 against {refname}:

| store | AC@1 | ΔAC@1 (95% CI, pts) | p50 | p95 |
|---|---|---|---|---|
{chr(10).join(rows)}

- **Accuracy history on TEST (top-1 hits of 1,800):**
{hist_txt}
  Every table in `results.json` now comes from the final engine.
"""

rd = ROOT / "README.md"
t = rd.read_text(encoding="utf8")
if "<!-- proof:begin -->" in t:
    a, z = t.index("<!-- proof:begin -->"), t.index("<!-- proof:end -->") + len("<!-- proof:end -->")
    t = t[:a] + proof + t[z:]
else:
    lines = t.split("\n")
    i = next((k for k, l in enumerate(lines) if l.startswith("Root cause analysis")), 1)
    lines.insert(i + 1, "\n" + proof)
    t = "\n".join(lines)
if "\n## HydraDB (live)" in t:
    t = t[: t.index("\n## HydraDB (live)")]
rd.write_text(t.rstrip() + "\n" + hydra, encoding="utf8")
print("README updated")
