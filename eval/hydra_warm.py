"""Warm HydraDB latency after the transport fix, with Postgres measured the same way on the same company.

    python eval/hydra_warm.py            # needs HydraDB and Postgres: docker compose --profile eval up -d hydradb postgres

Per query (200 timed after 20 warm-up, sequential): 1-hop neighbours, best path at 3 and 5 hops, edge-weight write.
Per verdict (3 DEV companies, every incident): HydraDB cached hit / cached miss / cold / in-DB, and Postgres' two batched CTEs.
Writes ops.hydradb_latency.warm and .postgres_warm into results.json and keeps the earlier numbers under before_transport_fix. Latency only; DEV only.
"""
from __future__ import annotations
import argparse, ctypes, json, math, os, pathlib, platform, subprocess, sys, time
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from eval.runner import load
from eval.hydra_latency import picks, pct
from eval import stores
from eval.pg_batch_verdict import DOWN, UP
from ghostwalk.engine.walk import walk, resolve
from ghostwalk.graph.hydra import HydraGraph, _tabulate, cost_of
from ghostwalk.learn import update

URL = os.environ.get("HYDRA_URL", "http://127.0.0.1:8443")
PG = os.environ.get("PG_URL", "postgresql://gw:gw@127.0.0.1:5433/gw")
N, WARM = 200, 20


def timed(fn, n=N, warm=WARM):
    for _ in range(warm):
        fn()
    out = []
    for _ in range(n):
        t = time.perf_counter(); fn(); out.append((time.perf_counter() - t) * 1000)
    return pct(out)


def machine():
    info = {"platform": platform.platform(), "processor": platform.processor(), "cpus": os.cpu_count(), "python": platform.python_version()}
    try:
        class MS(ctypes.Structure):
            _fields_ = [("l", ctypes.c_ulong), ("m", ctypes.c_ulong), ("tp", ctypes.c_ulonglong), ("ap", ctypes.c_ulonglong), ("tpf", ctypes.c_ulonglong), ("apf", ctypes.c_ulonglong), ("tv", ctypes.c_ulonglong), ("av", ctypes.c_ulonglong), ("ae", ctypes.c_ulonglong)]
        m = MS(); m.l = ctypes.sizeof(MS); ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        info["ram_gb"] = round(m.tp / 2**30, 1)
    except Exception:
        pass
    for k, cmd in (("docker", ["docker", "version", "--format", "{{.Server.Version}} on {{.Server.Os}}/{{.Server.Arch}}"]),
                   ("hydradb_image", ["docker", "inspect", "ghcr.io/hydra-db/hydradb:0.4.0", "--format", "{{index .RepoDigests 0}}"])):
        try:
            info[k] = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL).strip()
        except Exception:
            pass
    info["note"] = "client on the host (Windows), HydraDB and Postgres in docker containers reached through published ports on loopback"
    return info


def main():
    import psycopg
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "results.json"))
    ap.add_argument("--companies", type=int, default=3)
    a = ap.parse_args()
    pg = psycopg.connect(PG, autocommit=True)
    run_id = int(time.time()) % 700 + 100
    hg = HydraGraph(URL, run_id=run_id, mode="cached")
    hc = HydraGraph(URL, run_id=run_id, mode="cold")

    # ---------------- per query, on the median DEV company ----------------
    co = sorted(load("dev"), key=lambda c: (len(c["components"]), c["name"]))[len(load("dev")) // 2]
    g = hg.fresh(co)
    pgs = stores.PgCteGraph(PG)
    pgs.fresh(co)
    base = hg.co
    adj = g.out_adj()
    src = max(g.components, key=lambda c: len(adj.get(c, [])))
    from ghostwalk.engine.walk import _limited_best
    reach = lambda h: [t for t in _limited_best(adj, src, h)[0] if t != src]
    # the farthest target reachable in exactly <=h hops so that the search has real work to do
    tgt = {h: max(reach(h), key=lambda t: -math.log(_limited_best(adj, src, h)[0][t])) for h in (3, 5)}
    u, v = next(iter(g.edges))
    CTE = ("WITH RECURSIVE r(node, cost, depth, path) AS (SELECT %(s)s::int, 0::float8, 0, ARRAY[%(s)s::int] UNION ALL "
           "SELECT e.v, r.cost - ln(e.w), r.depth + 1, r.path || e.v FROM r JOIN gw_edge e ON e.co = %(co)s AND e.u = r.node "
           "WHERE r.depth < %(h)s AND NOT (e.v = ANY (r.path))) SELECT min(cost) FROM r WHERE node = %(t)s")
    sp = lambda h: (lambda: _tabulate(hg._q("CALL algo.SPpaths({sourceNode: $s, targetNode: $t, relTypes: ['DEPENDS_ON'], relDirection: 'outgoing', maxLen: $m, "
                                            "weightProp: 'cost', costProp: 'cost', pathCount: 1}) YIELD path, pathCost RETURN path, pathCost", s=base + src, t=base + tgt[h], m=h)))
    wcount = [0]
    def hwrite():
        wcount[0] += 1
        hg._set_edge(u, v, w=0.5 + (wcount[0] % 7) * 0.01, cost=cost_of(0.5 + (wcount[0] % 7) * 0.01))
    def pgwrite():
        wcount[0] += 1
        pg.execute("UPDATE gw_edge SET w = %s WHERE co = %s AND u = %s AND v = %s", (0.5 + (wcount[0] % 7) * 0.01, co["name"], u, v))
    q = {
        "one_hop": {"hydradb": timed(lambda: hg._rows("MATCH (a:Component {id: $s})-[e:DEPENDS_ON]->(b:Component) RETURN b.id AS id", s=base + src)),
                    "postgres": timed(lambda: pg.execute("SELECT v FROM gw_edge WHERE co = %s AND u = %s", (co["name"], src)).fetchall())},
        "path_3_hops": {"hydradb": timed(sp(3)), "postgres": timed(lambda: pg.execute(CTE, {"s": src, "t": tgt[3], "co": co["name"], "h": 3}).fetchone())},
        "path_5_hops": {"hydradb": timed(sp(5)), "postgres": timed(lambda: pg.execute(CTE, {"s": src, "t": tgt[5], "co": co["name"], "h": 5}).fetchone())},
        "edge_write": {"hydradb": timed(hwrite), "postgres": timed(pgwrite)},
    }
    # identical answers (HydraDB path cost vs Postgres CTE cost vs in-process)
    for h in (3, 5):
        hc_cost = sp(h)()[0][1]
        pgc = pg.execute(CTE, {"s": src, "t": tgt[h], "co": co["name"], "h": h}).fetchone()[0]
        assert abs(hc_cost - pgc) < 1e-6, (h, hc_cost, pgc)
    hg.drop()
    print("per query done", flush=True)

    # ---------------- per verdict ----------------
    cold, hit, miss, indb, pgv = [], [], [], [], []
    mism = checked = 0
    pgdb = pg
    for c in picks("dev", a.companies):
        hg.fresh(c); hc.co = hg.co
        pgdb.execute("CREATE TABLE IF NOT EXISTS scale_edge (sz int, u int, v int, w float8, cost float8)")
        pgdb.execute("CREATE INDEX IF NOT EXISTS scale_edge_u ON scale_edge (sz, u)")
        pgdb.execute("DELETE FROM scale_edge WHERE sz = %s", (-1,))
        with pgdb.cursor() as cur:
            cur.executemany("INSERT INTO scale_edge VALUES (%s,%s,%s,%s,%s)", [(-1, x["u"], x["v"], 0.7, cost_of(0.7)) for x in c["official_edges"]])
        gstate = hg.snapshot()
        for inc in c["incidents"]:
            al = inc["alerts"]
            t = time.perf_counter(); s = hc.snapshot(); walk(s, al); cold.append((time.perf_counter() - t) * 1000)
            t = time.perf_counter(); snap = hg.snapshot(); vv = walk(snap, al); miss.append((time.perf_counter() - t) * 1000)
            t = time.perf_counter(); snap2 = hg.snapshot(); walk(snap2, al); hit.append((time.perf_counter() - t) * 1000)
            t = time.perf_counter(); vd = hg.verdict_in_db(al); indb.append((time.perf_counter() - t) * 1000)
            checked += 1
            if len(vd.ranking) != len(vv.ranking) or any(abs(x - y) > 1e-9 for (_, x), (_, y) in zip(vd.ranking, vv.ranking)):
                mism += 1
            # Postgres, same company: the two batched CTEs, then the same walk
            A, _, _ = resolve(gstate, al)
            if A:
                t = time.perf_counter()
                down = {x: {x: 1.0} for x in A}; cands = set(A)
                for s_, node, cost in pgdb.execute(DOWN, {"srcs": sorted(A), "sz": -1, "h": 5}).fetchall():
                    down[s_][node] = math.exp(-cost); cands.add(node)
                up = {x: {x: 1.0} for x in cands}
                for c_, v_, cost in pgdb.execute(UP, {"srcs": sorted(cands), "sz": -1, "h": 5}).fetchall():
                    up[c_][v_] = math.exp(-cost)
                walk(gstate, al, reach=lambda x, d, h: ((down if d == "out" else up)[x], {}))
                pgv.append((time.perf_counter() - t) * 1000)
            hg.apply(update.propose(snap, inc["postmortem"], vv, al, inc["seq"]))
        hg.drop()
        print("  verdicts:", c["name"], flush=True)
    pgdb.execute("DELETE FROM scale_edge WHERE sz = %s", (-1,))

    warm = {"measured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "machine": machine(), "transport": "persistent HTTP/1.1, one write per request (ghostwalk/graph/fasthttp.py)",
            "per_query": {k: {"n": N, "warmup": WARM, **v} for k, v in q.items()}, "companies_for_verdicts": [f"{c['name']} ({len(c['components'])} services)" for c in picks("dev", a.companies)],
            "verdicts": checked, "per_verdict": {"cached_hit": pct(hit), "cached_miss": pct(miss), "cold": pct(cold), "in_db": pct(indb)},
            "postgres_per_verdict": pct(pgv), "in_db_matches_in_memory": {"checked": checked, "mismatches": mism, "tolerance": 1e-9},
            "under_20ms": {"cached_hit_p50": float(np.percentile(hit, 50)) < 20, "cached_miss_p50": float(np.percentile(miss, 50)) < 20, "in_db_p50": float(np.percentile(indb, 50)) < 20}}
    path = pathlib.Path(a.out)
    doc = json.loads(path.read_text(encoding="utf8")) if path.exists() else {}
    ops = doc.setdefault("ops", {})
    old = ops.get("hydradb_latency", {})
    if "warm" in old:                                   # re-running: keep the original 'before'
        before = old.get("before_transport_fix")
    else:
        before = {k: v for k, v in old.items() if k not in ("warm", "before_transport_fix", "diagnosis")}
    ops["hydradb_latency"] = {"before_transport_fix": before, "diagnosis": old.get("diagnosis"), "warm": warm}
    path.write_text(json.dumps(doc, indent=2), encoding="utf8")
    f = lambda d: f"{d['p50']:7.2f} / {d['p95']:7.2f}"
    for k, v in q.items():
        print(f"{k:12s} HydraDB {f(v['hydradb'])}   Postgres {f(v['postgres'])} ms")
    for k, v in warm["per_verdict"].items():
        print(f"verdict {k:11s} {f(v)} ms")
    print(f"verdict postgres    {f(warm['postgres_per_verdict'])} ms | in-DB mismatches {mism}/{checked}")


if __name__ == "__main__":
    main()
