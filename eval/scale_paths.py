"""Where a graph engine should win: weighted best-path queries on big graphs, HydraDB algo.SPpaths vs a Postgres recursive CTE.

    python eval/scale_paths.py [--sizes 100 1000 5000] [--pairs 40]     # needs HydraDB + Postgres: docker compose --profile eval up -d hydradb postgres

Synthetic graphs from the benchmark generator (tier mix kept), loaded into both stores with the same weights (cost = -ln w).
For random REACHABLE (source, target) pairs at max_hops 3 and 5 it times each query end to end (client round trip) and checks both stores return the
exact best cost (against an in-process limited Bellman-Ford). Pairs are reachable on purpose: this measures path search, not "no path" fast paths.
Then, per size, whole-verdict latency: cold read vs the in-DB verdict. Latency only: no accuracy claims. Nothing here touches TEST.
"""
from __future__ import annotations
import argparse, concurrent.futures as cf, datetime, json, math, os, pathlib, platform, random, sys, time
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from gwsim.world import build_company, Knobs
from ghostwalk.engine.walk import walk, _limited_best
from ghostwalk.graph.state import GraphState, Edge
from ghostwalk.graph.hydra import HydraGraph, _tabulate, cost_of, RUN_SPAN, CO_SPAN, EDGE_PROPS, HydraError

HYDRA = os.environ.get("HYDRA_URL", "http://127.0.0.1:8443")
TOKEN = os.environ.get("HYDRA_TOKEN", "local-development-token-32-bytes")
PG = os.environ.get("PG_URL", "postgresql://gw:gw@127.0.0.1:5433/gw")
SEED = 5150
TIMEOUT_MS = 30_000

CTE = """
WITH RECURSIVE r(node, cost, depth, path) AS (
  SELECT %(s)s::int, 0::float8, 0, ARRAY[%(s)s::int]
  UNION ALL
  SELECT e.v, r.cost + e.cost, r.depth + 1, r.path || e.v
  FROM r JOIN scale_edge e ON e.sz = %(sz)s AND e.u = r.node
  WHERE r.depth < %(h)s AND NOT (e.v = ANY (r.path))
)
SELECT min(cost) FROM r WHERE node = %(t)s
"""
CTE_COUNT = CTE.replace("SELECT min(cost) FROM r WHERE node = %(t)s", "SELECT count(*) FROM r")


def pct(xs):
    a = np.array(xs, dtype=float)
    return {"p50": float(np.percentile(a, 50)), "p95": float(np.percentile(a, 95)), "max": float(a.max()), "n": int(len(a))} if len(a) else {"n": 0}


def load_hydra(hg: HydraGraph, co, workers=8):
    """Nodes by the node batch, edges one request each (this HydraDB version has no batch that writes edge properties); edges in parallel."""
    comps = {c["id"]: c for c in co["components"]}
    nodes = [{"id": hg.co + i, "name": c["name"], "kind": c["kind"], "tier": c["tier"], "co": hg.co, "rc": 0, "aff": 0, "miss": 0, "key": f"{hg.co}:{c['name']}"} for i, c in comps.items()]
    for chunk in hg._batches(nodes):
        hg._q("UNWIND $rows AS row MERGE (n {id: row.id}) SET n:Component, n.name = row.name, n.kind = row.kind, n.tier = row.tier, "
              "n.co = row.co, n.rc = row.rc, n.aff = row.aff, n.miss = row.miss, n.key = row.key", rows=chunk)

    def one(item):
        o, e = item
        for attempt in range(6):
            try:
                hg._q(f"MERGE (a:Component {{id: $u}})-[:DEPENDS_ON {EDGE_PROPS}]->(b:Component {{id: $v}})", u=hg.co + e["u"], v=hg.co + e["v"],
                      w=e["w"], cost=cost_of(e["w"]), origin="official", conf=0, lf=-1, cs=-1, o=o)
                return
            except HydraError as ex:
                if attempt == 5:
                    raise
                time.sleep(0.2 * (attempt + 1))
    t = time.time()
    with cf.ThreadPoolExecutor(workers) as pool:
        list(pool.map(one, enumerate(co["true_edges"])))
    hg._write_meta(0, len(co["true_edges"]), 0)
    return time.time() - t


def truth_state(co):
    g = GraphState(components={c["id"]: {"name": c["name"], "kind": c["kind"], "tier": c["tier"]} for c in co["components"]})
    g.names = {c["name"]: c["id"] for c in co["components"]}
    for e in co["true_edges"]:
        g.edges[(e["u"], e["v"])] = Edge(e["w"])
    return g


def load_pg(db, sz, co):
    db.execute("CREATE TABLE IF NOT EXISTS scale_edge (sz int, u int, v int, w float8, cost float8)")
    db.execute("CREATE INDEX IF NOT EXISTS scale_edge_u ON scale_edge (sz, u)")
    db.execute("DELETE FROM scale_edge WHERE sz = %s", (sz,))
    with db.cursor() as cur:
        cur.executemany("INSERT INTO scale_edge VALUES (%s,%s,%s,%s,%s)", [(sz, e["u"], e["v"], e["w"], cost_of(e["w"])) for e in co["true_edges"]])
    db.execute("ANALYZE scale_edge")


def pick_pairs(g, hops, n, rng):
    adj = g.out_adj()
    srcs = [c for c in g.components if adj.get(c)]
    pairs = []
    while len(pairs) < n:
        s = rng.choice(srcs)
        best, _ = _limited_best(adj, s, hops)
        reach = [t for t in best if t != s]
        if reach:
            t = rng.choice(reach)
            pairs.append((s, t, -math.log(best[t])))
    return pairs


def main():
    import psycopg
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", type=int, nargs="*", default=[100, 1000, 5000])
    ap.add_argument("--pairs", type=int, default=40)
    ap.add_argument("--hops", type=int, nargs="*", default=[3, 5])
    ap.add_argument("--out", default=str(ROOT / "results.json"))
    a = ap.parse_args()
    rng = random.Random(SEED)
    db = psycopg.connect(PG, autocommit=True)
    out = {"pairs_per_cell": a.pairs, "seed": SEED, "generator": "gwsim layered, tier mix kept", "statement_timeout_ms": TIMEOUT_MS, "sizes": {}}
    run_id = int(time.time()) % 700 + 100
    for n in a.sizes:
        print(f"== {n} services", flush=True)
        co = json.loads(build_company(f"scale-{n}", "layered", SEED, n=n, knobs=Knobs(n_incidents=12)).to_json())
        g = truth_state(co)
        hg = HydraGraph(HYDRA, TOKEN, run_id=run_id, mode="cold")
        hg.co = run_id * RUN_SPAN + (n % 50) * CO_SPAN
        entry = {"services": len(co["components"]), "edges": len(co["true_edges"]), "path_query": {}, "verdict": {}}
        entry["load_hydradb_s"] = round(load_hydra(hg, co), 1)
        t = time.time(); load_pg(db, n, co); entry["load_postgres_s"] = round(time.time() - t, 2)
        print(f"   loaded: HydraDB {entry['load_hydradb_s']} s, Postgres {entry['load_postgres_s']} s", flush=True)
        for h in a.hops:
            pairs = pick_pairs(g, h, a.pairs, rng)
            cell = {"hydradb": {"ms": [], "wrong": 0}, "postgres": {"ms": [], "wrong": 0, "timeouts": 0}}
            worst = (0, None)
            for s, t, truth in pairs:
                t0 = time.perf_counter()
                rows = _tabulate(hg._q("CALL algo.SPpaths({sourceNode: $s, targetNode: $t, relTypes: ['DEPENDS_ON'], relDirection: 'outgoing', maxLen: $m, "
                                       "weightProp: 'cost', costProp: 'cost', pathCount: 1}) YIELD path, pathCost RETURN path, pathCost", s=hg.co + s, t=hg.co + t, m=h))
                dt = (time.perf_counter() - t0) * 1000
                cell["hydradb"]["ms"].append(dt)
                if not rows or abs(rows[0][1] - truth) > 1e-6:
                    cell["hydradb"]["wrong"] += 1
                try:
                    db.execute(f"SET statement_timeout = {TIMEOUT_MS}")
                    t0 = time.perf_counter()
                    r = db.execute(CTE, {"s": s, "t": t, "sz": n, "h": h}).fetchone()[0]
                    dt = (time.perf_counter() - t0) * 1000
                    cell["postgres"]["ms"].append(dt)
                    if r is None or abs(r - truth) > 1e-6:
                        cell["postgres"]["wrong"] += 1
                    if dt > worst[0]:
                        worst = (dt, (s, t))
                except psycopg.errors.QueryCanceled:
                    cell["postgres"]["timeouts"] += 1
                    cell["postgres"]["ms"].append(TIMEOUT_MS)
                    worst = (TIMEOUT_MS, (s, t))
            res = {k: {**pct(v["ms"]), **{x: y for x, y in v.items() if x != "ms"}} for k, v in cell.items()}
            if worst[1] and h == max(a.hops):               # what the CTE does at the slowest pair: rows enumerated and the plan's top line
                s, t = worst[1]
                try:
                    db.execute(f"SET statement_timeout = {TIMEOUT_MS}")
                    rows_enum = db.execute(CTE_COUNT, {"s": s, "t": t, "sz": n, "h": h}).fetchone()[0]
                    plan = db.execute("EXPLAIN (ANALYZE, FORMAT JSON) " + CTE, {"s": s, "t": t, "sz": n, "h": h}).fetchone()[0][0]
                    res["postgres"]["slowest_pair"] = {"ms": round(worst[0], 1), "rows_enumerated_by_cte": rows_enum, "plan_execution_ms": plan["Execution Time"],
                                                       "plan_top": plan["Plan"]["Node Type"]}
                except psycopg.errors.QueryCanceled:
                    res["postgres"]["slowest_pair"] = {"ms": TIMEOUT_MS, "note": "the CTE hit the statement timeout while counting"}
            entry["path_query"][f"hops_{h}"] = res
            print(f"   hops {h}: HydraDB p50 {res['hydradb']['p50']:.1f} p95 {res['hydradb']['p95']:.1f} ms (wrong {res['hydradb']['wrong']}) | "
                  f"Postgres p50 {res['postgres']['p50']:.1f} p95 {res['postgres']['p95']:.1f} ms (wrong {res['postgres']['wrong']}, timeouts {res['postgres']['timeouts']})", flush=True)

        # whole-verdict latency on the first incidents with several alerts: read the graph back vs two MSpaths requests
        cold, indb, bad, checked = [], [], 0, 0
        for inc in [i for i in co["incidents"] if len(i["alerts"]) >= 2][:5]:
            want = walk(g, inc["alerts"]).ranking
            t0 = time.perf_counter(); snap = hg._read_graph(); got_cold = walk(snap, inc["alerts"]); cold.append((time.perf_counter() - t0) * 1000)
            hg.mspaths_requests = 0
            t0 = time.perf_counter(); got = hg.verdict_in_db(inc["alerts"]); indb.append((time.perf_counter() - t0) * 1000)
            checked += 1
            if len(got.ranking) != len(want) or any(abs(x - y) > 1e-9 for (_, x), (_, y) in zip(got.ranking, want)) or \
               any(abs(x - y) > 1e-9 for (_, x), (_, y) in zip(got_cold.ranking, want)):
                bad += 1
        entry["verdict"] = {"cold_read": pct(cold), "in_db": {**pct(indb), "mspaths_requests_last": hg.mspaths_requests}, "incidents": checked, "ranking_mismatches": bad}
        print(f"   verdict: cold read p50 {entry['verdict']['cold_read']['p50']:.0f} ms | in-DB p50 {entry['verdict']['in_db']['p50']:.0f} ms "
              f"({hg.mspaths_requests} MSpaths requests) | mismatches {bad}/{checked}", flush=True)
        out["sizes"][str(n)] = entry
        hg.drop()
        db.execute("DELETE FROM scale_edge WHERE sz = %s", (n,))
        out["meta"] = {"timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"), "python": platform.python_version(),
                       "hydradb": "ghcr.io/hydra-db/hydradb:0.4.0", "postgres": "pgvector/pgvector:pg16", "note": "both databases in docker on one machine, loopback"}
        path = pathlib.Path(a.out)
        doc = json.loads(path.read_text(encoding="utf8")) if path.exists() else {}
        prev = doc.get("scale", {}).get("path_query", {}).get("sizes", {}) if a.sizes != [100, 1000, 5000] else {}
        merged = {**prev, **out["sizes"]}
        doc["scale"] = {"path_query": {**out, "sizes": dict(sorted(merged.items(), key=lambda kv: int(kv[0])))}}
        path.write_text(json.dumps(doc, indent=2), encoding="utf8")           # written after every size, so a long 5,000-service run keeps what it has


if __name__ == "__main__":
    main()
