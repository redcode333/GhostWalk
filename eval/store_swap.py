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


HYDRA_URL = os.environ.get("HYDRA_URL", "http://127.0.0.1:8443")
HYDRA_TOKEN = os.environ.get("HYDRA_TOKEN", "local-development-token-32-bytes")


def hydra_status():
    """Probe the node with a real query through the real parser. 'available' only when HydraDB answers and the adapter can read it."""
    try:
        if httpx.get(HYDRA_READY, timeout=3).status_code != 200:
            return {"status": f"not run: {HYDRA_READY} is not ready"}
    except Exception:
        return {"status": f"not run: no HydraDB node reachable at {HYDRA_READY}"}
    from ghostwalk.graph.hydra import HydraGraph, HydraError
    try:
        hg = HydraGraph(HYDRA_URL, HYDRA_TOKEN, run_id=0)
        hg._rows("MATCH (n:Component {co: 0}) RETURN n.id AS id")
        hg.close()
    except (HydraError, httpx.HTTPError) as e:
        return {"status": f"not run: node is up but a probe query failed: {str(e)[:160]}"}
    return {"status": "available", "url": HYDRA_URL, "image": os.environ.get("HYDRADB_IMAGE", "ghcr.io/hydra-db/hydradb:0.4.0")}


def only_hydradb(a):
    """Re-measure ONLY the HydraDB row on the same incidents: verdict latency and, separately, the learning write. Accuracy must not move; if it does, nothing is written."""
    out = pathlib.Path(a.results or ("results.json" if a.split == "test" else "dev_results.json"))
    doc = json.loads(out.read_text(encoding="utf8"))
    old = doc["store_swap"]["backends"]["hydradb"]
    cos = load(a.split)
    names = [c["name"] for c in cos]
    stat = hydra_status()
    assert stat["status"] == "available", stat
    from ghostwalk.graph.hydra import HydraGraph
    hg = HydraGraph(HYDRA_URL, HYDRA_TOKEN, run_id=int(time.time()) % 900 + 1)
    rows, t0 = {}, time.time()
    for c in cos:
        try:
            rows[c["name"]] = run_company(c, "ghostwalk", backend=hg)
        finally:
            hg.drop()
    print(f"  hydradb {time.time() - t0:6.1f}s  full re-reads {hg.full_reads}, cache hits {hg.hits}, disagreements {hg.disagreements}", flush=True)
    hits = sum(1 for rs in rows.values() for r in rs if r["rank"] is not None and r["rank"] <= 1)
    was = round(old["ac1"]["point"] * sum(len(v) for v in rows.values()))
    assert hits == was, f"accuracy moved: {hits} top-1 hits now vs {was} before; nothing written"
    verdict = np.array([r["ms"] for rs in rows.values() for r in rs])
    write = np.array([r["apply_ms"] for rs in rows.values() for r in rs if "apply_ms" in r])
    before = {k: old[k] for k in ("verdict_ms_p50", "verdict_ms_p95") if k in old}
    old["verdict_ms_p50"], old["verdict_ms_p95"] = float(np.percentile(verdict, 50)), float(np.percentile(verdict, 95))
    old["verdict_ms_before_write_through_cache"] = before
    old["learning_write_ms_p50"], old["learning_write_ms_p95"] = float(np.percentile(write, 50)), float(np.percentile(write, 95))
    old["learning_write_note"] = "the learner's writes to HydraDB (alias/add/confirm/reweight/decay/counters), measured separately: they happen after the verdict, off the verdict path"
    old["cache"] = {"kind": "revision-checked write-through", "full_graph_rereads": hg.full_reads, "cache_hits": hg.hits, "disagreements": hg.disagreements}
    old["description"] = "HydraDB v0.4.0 (published image): the graph lives in HydraDB; verdicts read it through a revision-checked write-through cache"
    doc["store_swap"]["hydradb"] = stat
    ops = doc.setdefault("ops", {})
    ops["hydradb_online_loop_test"] = {"verdict_ms_p50": old["verdict_ms_p50"], "verdict_ms_p95": old["verdict_ms_p95"], "n": int(len(verdict)), "split": a.split,
                                       "learning_write_ms_p50": old["learning_write_ms_p50"], "learning_write_ms_p95": old["learning_write_ms_p95"],
                                       "backend": "HydraDB v0.4.0, local node in docker (loopback), write-through cache", "before_write_through_cache": before}
    out.write_text(json.dumps(doc, indent=2), encoding="utf8")
    print(f"verdict p50 {old['verdict_ms_p50']:.2f} ms p95 {old['verdict_ms_p95']:.2f} ms (before {before['verdict_ms_p50']:.1f} / {before['verdict_ms_p95']:.1f}); "
          f"learning write p50 {old['learning_write_ms_p50']:.1f} ms p95 {old['learning_write_ms_p95']:.1f} ms; top-1 hits {hits} (unchanged)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only-hydradb", action="store_true", help="re-measure only the HydraDB row (latency); aborts if accuracy changes")
    ap.add_argument("--split", default="test")
    ap.add_argument("--results", default=None, help="results json to merge the store_swap section into")
    ap.add_argument("--boot", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=20261116)
    ap.add_argument("--limit", type=int, default=0, help="debug: only the first N companies")
    a = ap.parse_args()
    if a.only_hydradb:
        return only_hydradb(a)
    out = pathlib.Path(a.results or ("results.json" if a.split == "test" else "dev_results.json"))
    cos = load(a.split)[: a.limit or None]
    names = [c["name"] for c in cos]

    runs = {}

    def go(label, fn):
        t = time.time()
        runs[label] = {c["name"]: fn(c) for c in cos}
        print(f"  {label:22s} {time.time() - t:6.1f}s", flush=True)

    hstat = hydra_status()
    go("inmemory", lambda c: run_company(c, "ghostwalk"))
    if hstat["status"] == "available":
        from ghostwalk.graph.hydra import HydraGraph
        hg = HydraGraph(HYDRA_URL, HYDRA_TOKEN, run_id=int(time.time()) % 900 + 1)

        def hydra_company(c):
            try:
                return run_company(c, "ghostwalk", backend=hg)
            finally:
                hg.drop()                                   # keep the node tidy between companies
        go("hydradb", hydra_company)
    kv = stores.KVGraph(REDIS)
    go("kv_1hop", lambda c: run_company(c, "ghostwalk", backend=kv))
    cte = stores.PgCteGraph(PG)
    go("pg_cte", lambda c: run_company(c, "ghostwalk", backend=cte))
    vec = stores.PgVectorStore(PG)
    go("pgvector", lambda c: stores.run_vector_company(c, vec))

    tabs = {k: table(v, names) for k, v in runs.items()}
    ref = "hydradb" if "hydradb" in tabs else "inmemory"
    ci, diffs = bootstrap(tabs, a.boot, a.seed, [(k, ref) for k in tabs if k != ref])
    desc = {"hydradb": "HydraDB v0.4.0 (published image): graph in HydraDB, weighted paths and counters read back every verdict",
            "inmemory": "in-process dict graph (the parity-tested stand-in for HydraDB)", "kv_1hop": "Redis hashes, 1-hop adjacency only (engine max_hops=1)",
            "pg_cte": "Postgres tables, multi-hop reach by recursive CTE",
            "pgvector": "pgvector: nearest embedded postmortem text names the root (no graph)"}
    res = {"split": a.split, "reference": ref, "hydradb": hstat, "backends": {}}
    for k in tabs:
        ms = np.array([r["ms"] for rs in runs[k].values() for r in rs])
        res["backends"][k] = {"description": desc[k], "ac1": ci[k], "delta_vs_reference": diffs.get(f"{k} - {ref}"),
                              "verdict_ms_p50": float(np.percentile(ms, 50)), "verdict_ms_p95": float(np.percentile(ms, 95))}
    res["note"] = (("ΔAC@1 is measured against HydraDB. " if ref == "hydradb" else "ΔAC@1 is measured against the in-memory reference because HydraDB did not run (see hydradb.status). ")
                   + "Latency is the whole verdict (snapshot read + walk) per incident. Embeddings are feature-hashed bags of words (no model).")
    for k, v in res["backends"].items():
        d = v["delta_vs_reference"]
        print(f"{k:10s} AC@1 {v['ac1']['point']:.3f}  delta vs reference " + (f"{d['point']:+.3f} [{d['ci95'][0]:+.3f}, {d['ci95'][1]:+.3f}]" if d else "-")
              + f"  p50 {v['verdict_ms_p50']:.1f} ms p95 {v['verdict_ms_p95']:.1f} ms")
    doc = json.loads(out.read_text()) if out.exists() else {}
    doc["store_swap"] = res
    if "hydradb" in res["backends"]:                 # the measured HydraDB latency, where the Search-vs-walk panel and the Proof page look for it
        h = res["backends"]["hydradb"]
        doc.setdefault("ops", {})["hydradb_online_loop_test"] = {"verdict_ms_p50": h["verdict_ms_p50"], "verdict_ms_p95": h["verdict_ms_p95"],
                                                        "n": sum(len(v) for v in runs["hydradb"].values()), "split": a.split, "backend": "HydraDB v0.4.0, local node in docker (loopback)"}
        doc["ops"].pop("hydradb_latency_note", None)
    out.write_text(json.dumps(doc, indent=2))
    print("merged store_swap into", out)


if __name__ == "__main__":
    main()
