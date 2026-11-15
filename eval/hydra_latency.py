"""HydraDB verdict latency in three read modes, plus a parity check that the in-DB verdict ranks like the in-memory engine.

    python eval/hydra_latency.py [--split dev] [--companies 3]      # needs a HydraDB node: docker compose up -d hydradb

(i)   cold    : read the whole graph back, then walk
(ii)  cached  : read the revision (one tiny query); re-read the graph only if it changed. Reported as HIT (graph unchanged since the last
                verdict) and MISS (a learner write bumped the revision, which is every incident in the online loop)
(iii) in_db   : two algo.MSpaths requests supply every reach; the edges are never read back; Python only scores

Latency only, on the DEV split (no TEST). Learning is driven by the cached snapshot, exactly as in the online loop.
"""
from __future__ import annotations
import argparse, json, os, pathlib, sys, time
import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from eval.runner import load
from ghostwalk.engine.walk import walk
from ghostwalk.graph.hydra import HydraGraph
from ghostwalk.learn import update

URL = os.environ.get("HYDRA_URL", "http://127.0.0.1:8443")
TOKEN = os.environ.get("HYDRA_TOKEN", "local-development-token-32-bytes")


def pct(xs):
    a = np.array(xs)
    return {"p50": float(np.percentile(a, 50)), "p95": float(np.percentile(a, 95)), "p99": float(np.percentile(a, 99)), "n": int(len(a))}


def picks(split, k):
    cos = sorted(load(split), key=lambda c: (len(c["components"]), c["name"]))
    idx = np.unique(np.linspace(0, len(cos) - 1, k).round().astype(int))
    return [cos[i] for i in idx]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="dev")
    ap.add_argument("--companies", type=int, default=3)
    ap.add_argument("--out", default="results.json")
    a = ap.parse_args()
    assert a.split != "test", "latency is measured on DEV"
    cold_ms, hit_ms, miss_ms, db_ms, mem_ms = [], [], [], [], []
    mismatches = checked = mspaths = 0
    names = []
    run_id = int(time.time()) % 800 + 100
    hg = HydraGraph(URL, TOKEN, run_id=run_id, mode="cached")
    hc = HydraGraph(URL, TOKEN, run_id=run_id, mode="cold")
    for co in picks(a.split, a.companies):
        names.append(f"{co['name']} ({len(co['components'])} services)")
        hg.fresh(co)
        hc.co = hg.co
        for inc in co["incidents"]:
            al = inc["alerts"]
            t = time.perf_counter(); s = hc.snapshot(); walk(s, al); cold_ms.append((time.perf_counter() - t) * 1000)
            t = time.perf_counter(); snap = hg.snapshot(); v = walk(snap, al); miss_ms.append((time.perf_counter() - t) * 1000)   # revision changed since last incident
            t = time.perf_counter(); snap2 = hg.snapshot(); walk(snap2, al); hit_ms.append((time.perf_counter() - t) * 1000)      # same revision
            t = time.perf_counter(); vd = hg.verdict_in_db(al); db_ms.append((time.perf_counter() - t) * 1000)
            t = time.perf_counter(); vm = walk(snap, al); mem_ms.append((time.perf_counter() - t) * 1000)                           # the walk alone (cached graph)
            checked += 1
            if len(vd.ranking) != len(v.ranking) or any(abs(x - y) > 1e-9 for (_, x), (_, y) in zip(vd.ranking, v.ranking)):
                mismatches += 1
            hg.apply(update.propose(snap, inc["postmortem"], v, al, inc["seq"]))         # learn, as the online loop does
        mspaths = hg.mspaths_requests
        print(f"  {names[-1]}: done", flush=True)
        hg.drop()
    res = {"split": a.split, "companies": names, "verdicts": checked, "node": "HydraDB v0.4.0 published image, docker, loopback",
           "cold": pct(cold_ms), "cached": {"hit": pct(hit_ms), "miss": pct(miss_ms),
                                            "note": "in the online loop every incident follows a learner write, so every verdict is a MISS; hits happen when several alerts arrive between postmortems"},
           "in_db": {**pct(db_ms), "requests_per_verdict": 2 + 4, "mspaths_requests": mspaths,
                     "note": "2 MSpaths + 4 small reads (components, aliases, shortcuts, revision); no edge read"},
           "walk_only": pct(mem_ms), "in_db_matches_in_memory": {"checked": checked, "mismatches": mismatches, "tolerance": 1e-9}}
    path = pathlib.Path(a.out)
    doc = json.loads(path.read_text(encoding="utf8")) if path.exists() else {}
    ops = doc.setdefault("ops", {})
    old = ops.get("hydradb_latency")
    if isinstance(old, dict) and "verdict_ms_p50" in old:          # the store-swap loop measurement moves under its own name
        ops["hydradb_online_loop_test"] = old
    ops["hydradb_latency"] = res
    path.write_text(json.dumps(doc, indent=2), encoding="utf8")
    for k in ("cold",):
        print(f"cold        p50 {res['cold']['p50']:7.1f}  p95 {res['cold']['p95']:7.1f} ms")
    print(f"cached hit  p50 {res['cached']['hit']['p50']:7.1f}  p95 {res['cached']['hit']['p95']:7.1f} ms")
    print(f"cached miss p50 {res['cached']['miss']['p50']:7.1f}  p95 {res['cached']['miss']['p95']:7.1f} ms")
    print(f"in_db       p50 {res['in_db']['p50']:7.1f}  p95 {res['in_db']['p95']:7.1f} ms   mismatches vs in-memory: {mismatches}/{checked}")
    print(f"walk only   p50 {res['walk_only']['p50']:7.1f}  p95 {res['walk_only']['p95']:7.1f} ms")


if __name__ == "__main__":
    main()
