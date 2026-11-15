"""Scale benchmark: verdict latency on synthetic graphs of 100 / 1,000 / 5,000 services, 1,000 incidents each.

    python eval/bench.py [--reference] [--incidents 1000] [--out results.json]      # `make bench`

Graphs come from the same generator as the benchmark (tier mix kept: 2 gateways, 16% API, 28% shared infra, the rest domain services).
Latency is the full per-incident verdict (graph snapshot + walk) in the online loop, so adjacency caching and learning both count.
HydraDB-backed latency is NOT part of the scale benchmark (loading a big graph through HydraDB's one-request-per-edge writes is impractical); it is measured on the TEST companies by eval/store_swap.py.
`--reference` also times the previous walk loop (tests/reference_walk.py) on the same incidents, for an honest before/after.
"""
from __future__ import annotations
import argparse, datetime, json, os, pathlib, platform, subprocess, sys, time
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from eval import runner
from gwsim.world import build_company, Knobs

SIZES = (100, 1000, 5000)
SEED = 5150
GATE_1K_MS, PORT_5K_MS = 100.0, 250.0


def pct(ms):
    return {"p50": float(np.percentile(ms, 50)), "p95": float(np.percentile(ms, 95)), "p99": float(np.percentile(ms, 99)), "mean": float(np.mean(ms)), "max": float(np.max(ms))}


def git():
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True, cwd=ROOT, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return None


def hydra_up():
    try:
        import httpx
        return httpx.get(os.environ.get("HYDRA_READY", "http://127.0.0.1:9090/readyz"), timeout=2).status_code == 200
    except Exception:
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--incidents", type=int, default=1000)
    ap.add_argument("--out", default=str(ROOT / "results.json"))
    ap.add_argument("--reference", action="store_true", help="also time the previous walk loop")
    ap.add_argument("--sizes", type=int, nargs="*", default=list(SIZES))
    a = ap.parse_args()

    out = {"incidents_per_size": a.incidents, "generator": "gwsim layered, tier mix kept", "seed": SEED, "sizes": {}}
    for n in a.sizes:
        t = time.time()
        co = json.loads(build_company(f"bench-{n}", "layered", SEED, n=n, knobs=Knobs(n_incidents=a.incidents)).to_json())
        gen = time.time() - t
        tiers = {k: sum(1 for c in co["components"] if c["tier"] == k) for k in range(4)}
        rows = runner.run_company(co, "ghostwalk")
        ms = np.array([r["ms"] for r in rows])
        entry = {"services": len(co["components"]), "edges": len(co["official_edges"]), "tiers": tiers, "generate_s": round(gen, 1),
                 "avg_alerts": round(float(np.mean([len(i["alerts"]) for i in co["incidents"]])), 1),
                 "in_memory_ms": pct(ms), "hydradb_ms": None}
        if a.reference:
            import reference_walk
            orig = runner.walk
            runner.walk = reference_walk.walk
            try:
                ref = np.array([r["ms"] for r in runner.run_company(co, "ghostwalk")])
            finally:
                runner.walk = orig
            entry["reference_walk_ms"] = pct(ref)
        out["sizes"][str(n)] = entry
        m = entry["in_memory_ms"]
        print(f"{n:>5} services  p50 {m['p50']:7.1f} ms  p95 {m['p95']:7.1f} ms  p99 {m['p99']:7.1f} ms"
              + (f"   (previous loop p95 {entry['reference_walk_ms']['p95']:.1f} ms)" if a.reference else ""), flush=True)

    out["hydradb"] = {"status": ("not run at scale: HydraDB is reachable, but a write costs about 65 ms (one request per edge), so loading 1,000 or 5,000 services through it "
                                 "was not benchmarked. Its latency on the 30 TEST companies is in ops.hydradb_latency")
                      if hydra_up() else "not run: no HydraDB node reachable (HYDRA_READY)"}
    p1k = out["sizes"].get("1000", {}).get("in_memory_ms", {}).get("p95")
    p5k = out["sizes"].get("5000", {}).get("in_memory_ms", {}).get("p95")
    out["gate"] = {"rule": f"stop if p95 at 1,000 services < {GATE_1K_MS:.0f} ms; port walk()'s Bellman-Ford to Rust only if p95 at 5,000 services > {PORT_5K_MS:.0f} ms",
                   "p95_1000_ms": p1k, "p95_5000_ms": p5k,
                   "stopped_at_1000": p1k is not None and p1k < GATE_1K_MS,
                   "rust_port_needed": p5k is not None and p5k > PORT_5K_MS,
                   "rust_port": ("not needed" if p5k is not None and p5k <= PORT_5K_MS else "needed") if p5k is not None else "5,000-service size not run"}
    out["hygiene"] = ["adjacency built once per graph revision and cached (GraphState.invalidate on every learner write)",
                      "per-verdict memo of (1 - miss rate); loop constants hoisted; the candidate loop visits only the services a candidate reaches and charges "
                      "unreachable alerting services their closed-form ln(eps)",
                      "HydraDB path costs (-ln w) are already stored with w on every write; UNWIND batching of path queries was NOT done (needs a node and a response parser)",
                      "no per-request JSON reload: results.json is re-read only when its mtime changes"]
    out["meta"] = {"timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"), "git": git(),
                   "python": platform.python_version(), "numpy": np.__version__, "cpus": os.cpu_count(), "platform": platform.platform(),
                   "command": " ".join(sys.argv)}
    path = pathlib.Path(a.out)
    doc = json.loads(path.read_text(encoding="utf8")) if path.exists() else {}
    doc["latency"] = out
    path.write_text(json.dumps(doc, indent=2), encoding="utf8")
    print("gate:", out["gate"]["rust_port"], "| wrote latency section to", path)


if __name__ == "__main__":
    main()
