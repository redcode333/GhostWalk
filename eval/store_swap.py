"""Store swap: the same engine and learner on real storage backends; report AC@1 and the change against the reference.

    python eval/store_swap.py --split test          # normally via: docker compose --profile eval run --rm eval

Reference store: the in-memory graph (the same GraphState the other backends rebuild). HydraDB is the intended
reference; it is reported only when a node answers AND the HydraGraph adapter can read results back (its
response parser is still a stub). Otherwise `hydradb.status` says exactly why not. Nothing is tuned here.
"""
from __future__ import annotations
import argparse, json, os, pathlib, sys, time
import numpy as np
import httpx

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from eval.runner import load, run_company
from eval.full_eval import table, bootstrap
from eval import stores

REDIS = os.environ.get("REDIS_URL", "redis://127.0.0.1:6380/0")
PG = os.environ.get("PG_URL", "postgresql://gw:gw@127.0.0.1:5433/gw")
HYDRA_READY = os.environ.get("HYDRA_READY", "http://127.0.0.1:9090/readyz")


def hydra_status():
    try:
        up = httpx.get(HYDRA_READY, timeout=2).status_code == 200
    except Exception:
        return {"status": f"not run: no HydraDB node reachable at {HYDRA_READY}"}
    from ghostwalk.graph import hydra
    try:
        hydra._tabulate({})
    except NotImplementedError:
        return {"status": "not run: node is up but ghostwalk/graph/hydra.py cannot parse query responses yet (_tabulate is a stub)"}
    return {"status": "available" if up else "not run"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="test")
    ap.add_argument("--results", default=None, help="results json to merge the store_swap section into")
    ap.add_argument("--boot", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=20261116)
    ap.add_argument("--limit", type=int, default=0, help="debug: only the first N companies")
    a = ap.parse_args()
    out = pathlib.Path(a.results or ("results.json" if a.split == "test" else "dev_results.json"))
    cos = load(a.split)[: a.limit or None]
    names = [c["name"] for c in cos]

    runs = {}

    def go(label, fn):
        t = time.time()
        runs[label] = {c["name"]: fn(c) for c in cos}
        print(f"  {label:22s} {time.time() - t:6.1f}s", flush=True)

    go("inmemory", lambda c: run_company(c, "ghostwalk"))
    kv = stores.KVGraph(REDIS)
    go("kv_1hop", lambda c: run_company(c, "ghostwalk", backend=kv))
    cte = stores.PgCteGraph(PG)
    go("pg_cte", lambda c: run_company(c, "ghostwalk", backend=cte))
    vec = stores.PgVectorStore(PG)
    go("pgvector", lambda c: stores.run_vector_company(c, vec))

    tabs = {k: table(v, names) for k, v in runs.items()}
    ci, diffs = bootstrap(tabs, a.boot, a.seed, [(k, "inmemory") for k in tabs if k != "inmemory"])
    desc = {"inmemory": "reference: in-process dict graph", "kv_1hop": "Redis hashes, 1-hop adjacency only (engine max_hops=1)",
            "pg_cte": "Postgres tables, multi-hop reach by recursive CTE",
            "pgvector": "pgvector: nearest embedded postmortem text names the root (no graph)"}
    res = {"split": a.split, "reference": "inmemory", "hydradb": hydra_status(), "backends": {}}
    for k in tabs:
        ms = np.array([r["ms"] for rs in runs[k].values() for r in rs])
        res["backends"][k] = {"description": desc[k], "ac1": ci[k], "delta_vs_reference": diffs.get(f"{k} - inmemory"),
                              "verdict_ms_p50": float(np.percentile(ms, 50)), "verdict_ms_p95": float(np.percentile(ms, 95))}
    res["note"] = ("ΔAC@1 is measured against the in-memory reference because no HydraDB result exists yet; "
                   "see hydradb.status. Embeddings are feature-hashed bags of words (no model).")
    for k, v in res["backends"].items():
        d = v["delta_vs_reference"]
        print(f"{k:10s} AC@1 {v['ac1']['point']:.3f}  delta vs reference " + (f"{d['point']:+.3f} [{d['ci95'][0]:+.3f}, {d['ci95'][1]:+.3f}]" if d else "-")
              + f"  p50 {v['verdict_ms_p50']:.1f} ms p95 {v['verdict_ms_p95']:.1f} ms")
    doc = json.loads(out.read_text()) if out.exists() else {}
    doc["store_swap"] = res
    out.write_text(json.dumps(doc, indent=2))
    print("merged store_swap into", out)


if __name__ == "__main__":
    main()
