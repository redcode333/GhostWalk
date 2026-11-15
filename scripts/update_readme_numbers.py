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
We use HydraDB for its native weighted path algorithms. In our latency measurements Postgres is faster, not slower (see [graph vs SQL](docs/graph-vs-sql.md)).

![GhostWalk proof card](docs/proof-card.png)
<!-- proof:end -->"""

hl = r["ops"]["hydradb_latency"]
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
- **Three read modes** (3 DEV companies, {hl['verdicts']} verdicts; latency only), p50 / p95 ms: cold (read the graph back) {f(hl['cold']['p50'])} / {f(hl['cold']['p95'])};
  cached by revision, hit {f(hl['cached']['hit']['p50'])} / {f(hl['cached']['hit']['p95'])} (a hit is a graph unchanged since the last verdict) and miss {f(hl['cached']['miss']['p50'])} / {f(hl['cached']['miss']['p95'])}
  (every incident in the online loop is a miss: each follows a learner write); in-DB (two `MSpaths` requests, no edge read) {f(hl['in_db']['p50'])} / {f(hl['in_db']['p95'])}.
  In-DB rankings matched the in-memory engine in {hl['in_db_matches_in_memory']['checked'] - hl['in_db_matches_in_memory']['mismatches']}/{hl['in_db_matches_in_memory']['checked']} verdicts.
- **Path queries at scale** (synthetic graphs, same generator; p50 / p95 ms; both stores return the exact same cost every time; one machine, loopback docker):

| services | HydraDB 3 hops | Postgres 3 hops | HydraDB 5 hops | Postgres 5 hops | whole verdict p50: HydraDB read / in-DB / Postgres |
|---|---|---|---|---|---|
{scale_rows}

  **Postgres keeps up and is faster at every size** (about 1 ms vs about 50 ms per path; no CTE blow-up at 5 hops on these graphs). Pushing the whole verdict into HydraDB is slower than reading
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
