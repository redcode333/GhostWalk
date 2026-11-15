"""The Postgres side of the whole-verdict comparison: two batched recursive CTEs per verdict, the same shape as HydraDB's two MSpaths requests.

    python eval/pg_batch_verdict.py [--sizes 100 1000 5000]       # needs Postgres: docker compose --profile eval up -d postgres

  down: alerting services -> every service they reach (the candidate set, q(c, v) for alerting v)       one CTE, many start rows
  up  : every candidate   <- every service that depends on it (the silent-but-expected terms)           one CTE, many start rows, reversed join
Both keep a cycle guard, a hop limit and the cheapest cost per (source, node). The reaches are handed to the same walk() and the ranking must equal
the in-memory engine's. Writes `scale.postgres_verdict` in results.json. Latency only; nothing here touches TEST.
"""
from __future__ import annotations
import argparse, json, math, os, pathlib, sys, time
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from gwsim.world import build_company, Knobs
from ghostwalk.engine.walk import walk, resolve
from ghostwalk.graph.hydra import cost_of
from eval.scale_paths import truth_state, load_pg, SEED, PG, pct

DOWN = """
WITH RECURSIVE r(src, node, cost, depth, path) AS (
  SELECT s, s, 0::float8, 0, ARRAY[s] FROM unnest(%(srcs)s::int[]) AS s
  UNION ALL
  SELECT r.src, e.v, r.cost + e.cost, r.depth + 1, r.path || e.v
  FROM r JOIN scale_edge e ON e.sz = %(sz)s AND e.u = r.node
  WHERE r.depth < %(h)s AND NOT (e.v = ANY (r.path))
)
SELECT src, node, min(cost) FROM r WHERE node <> src GROUP BY src, node
"""
UP = DOWN.replace("e.v, r.cost", "e.u, r.cost").replace("e.u = r.node", "e.v = r.node").replace("r.path || e.v", "r.path || e.u").replace("NOT (e.v = ANY (r.path))", "NOT (e.u = ANY (r.path))")


def verdict(db, sz, g, alerts, h=5):
    A, _, _ = resolve(g, alerts)
    t0 = time.perf_counter()
    down = {v: {v: 1.0} for v in A}
    cands = set(A)
    for s, node, cost in db.execute(DOWN, {"srcs": sorted(A), "sz": sz, "h": h}).fetchall():
        down[s][node] = math.exp(-cost)
        cands.add(node)
    up = {c: {c: 1.0} for c in cands}
    for c, v, cost in db.execute(UP, {"srcs": sorted(cands), "sz": sz, "h": h}).fetchall():
        up[c][v] = math.exp(-cost)
    got = walk(g, alerts, reach=lambda x, d, hh: ((down if d == "out" else up)[x], {}))
    return got, (time.perf_counter() - t0) * 1000


def main():
    import psycopg
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", type=int, nargs="*", default=[100, 1000, 5000])
    ap.add_argument("--out", default=str(ROOT / "results.json"))
    a = ap.parse_args()
    db = psycopg.connect(PG, autocommit=True)
    res = {"definition": "two batched recursive CTEs per verdict (down from the alerting services, up from every candidate), then the same walk()", "sizes": {}}
    for n in a.sizes:
        co = json.loads(build_company(f"scale-{n}", "layered", SEED, n=n, knobs=Knobs(n_incidents=12)).to_json())
        g = truth_state(co)
        load_pg(db, n, co)
        ms, bad, checked, timeouts = [], 0, 0, 0
        db.execute("SET statement_timeout = 120000")
        for inc in [i for i in co["incidents"] if len(i["alerts"]) >= 2][:5]:
            want = walk(g, inc["alerts"]).ranking
            try:
                got, dt = verdict(db, n, g, inc["alerts"])
            except psycopg.errors.QueryCanceled:
                timeouts += 1
                continue
            ms.append(dt)
            checked += 1
            if len(got.ranking) != len(want) or any(abs(x - y) > 1e-9 for (_, x), (_, y) in zip(got.ranking, want)):
                bad += 1
        res["sizes"][str(n)] = {**pct(ms), "ranking_mismatches": bad, "checked": checked, "timeouts": timeouts}
        print(f"{n:>5} services: Postgres whole verdict p50 {res['sizes'][str(n)].get('p50', float('nan')):.0f} ms, mismatches {bad}/{checked}, timeouts {timeouts}", flush=True)
        db.execute("DELETE FROM scale_edge WHERE sz = %s", (n,))
    path = pathlib.Path(a.out)
    doc = json.loads(path.read_text(encoding="utf8")) if path.exists() else {}
    doc.setdefault("scale", {})["postgres_verdict"] = res
    path.write_text(json.dumps(doc, indent=2), encoding="utf8")


if __name__ == "__main__":
    main()
