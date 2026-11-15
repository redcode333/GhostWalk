"""Warm HydraDB latency on the machine this runs on (meant for the deployment VM: no Docker Desktop proxy in between).

    docker compose --env-file deploy/.env -f deploy/docker-compose.prod.yml cp deploy/measure_vm.py api:/app/measure_vm.py
    docker compose --env-file deploy/.env -f deploy/docker-compose.prod.yml exec -T api python /app/measure_vm.py > vm_latency.json
    python scripts/merge_vm_latency.py vm_latency.json          # -> results.json ops.vm

It runs the online learning loop (learning on, write-through cache) on generated companies (not the DEV/TEST splits, which are not in the image) and times
the verdict, the learning write and single HydraDB requests, after a warm-up. Prints one JSON document on stdout."""
from __future__ import annotations
import json, os, platform, subprocess, sys, time
import numpy as np

sys.path.insert(0, "/app" if os.path.isdir("/app/ghostwalk") else ".")
from gwsim.cli import make
from eval.runner import run_company
from ghostwalk.engine.walk import walk, _limited_best
from ghostwalk.graph.hydra import cost_of, _tabulate
from ghostwalk.graph.state import GraphState
from gwsim.world import official_view
import types
from ghostwalk.graph.hydra import HydraGraph

URL = os.environ.get("HYDRA_URL", "http://hydradb:8443")
TOKEN = os.environ.get("HYDRA_TOKEN", "local-development-token-32-bytes")


def pct(xs):
    a = np.asarray(xs, dtype=float)
    return {"p50": float(np.percentile(a, 50)), "p95": float(np.percentile(a, 95)), "n": int(len(a))}


def sh(cmd):
    try:
        return subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return None


def machine():
    instance = sh("TOKEN=$(curl -s -m 2 -X PUT http://169.254.169.254/latest/api/token -H 'X-aws-ec2-metadata-token-ttl-seconds: 60') && curl -s -m 2 -H \"X-aws-ec2-metadata-token: $TOKEN\" http://169.254.169.254/latest/meta-data/instance-type") if os.environ.get("GW_MEASURED_ON") == "vm" else None
    cpu = None
    try:
        cpu = next(l.split(":", 1)[1].strip() for l in open("/proc/cpuinfo") if l.startswith("model name"))
    except Exception:
        pass
    mem = None
    try:
        mem = round(int(next(l.split()[1] for l in open("/proc/meminfo") if l.startswith("MemTotal"))) / 2**20, 1)
    except Exception:
        pass
    return {"label": "VM" if os.environ.get("GW_MEASURED_ON") == "vm" else os.environ.get("GW_MEASURED_ON", "unlabelled"), "cpu": cpu, "logical_cpus": os.cpu_count(), "ram_gb": mem,
            "instance_type": os.environ.get("GW_INSTANCE_TYPE") or instance, "kernel": platform.release(), "platform": platform.platform(), "python": platform.python_version(), "hydradb_url": URL,
            "note": "client (the API container) and HydraDB are containers on one docker network: no published-port proxy hop"}


def main():
    hg = HydraGraph(URL, TOKEN, run_id=int(time.time()) % 900 + 50)
    cos = [json.loads(make(f, s, n).to_json()) for f, s, n in (("hub", 31, 60), ("layered", 32, 90), ("hub", 33, 120))]
    rows, hits, one_hop = [], [], []
    q3, q5, wr, mem_v, cold_v = [], [], [], [], []
    for co in cos:
        rows += run_company(co, "ghostwalk", backend=hg)
        # warm single-request and cached-verdict timings on the graph this company learned
        base, snap = hg.co, hg.snapshot()
        src = max(snap.components, key=lambda c: len(snap.out_adj().get(c, [])))
        al = co["incidents"][-1]["alerts"]
        for _ in range(20):
            hg._rows("MATCH (a:Service {id: $s})-[:DEPENDS_ON]->(b:Service) RETURN b.id AS id", s=base + src)
            walk(hg.snapshot(), al)
        for _ in range(200):
            t = time.perf_counter()
            hg._rows("MATCH (a:Service {id: $s})-[:DEPENDS_ON]->(b:Service) RETURN b.id AS id", s=base + src)
            one_hop.append((time.perf_counter() - t) * 1000)
            t = time.perf_counter()
            walk(hg.snapshot(), al)
            hits.append((time.perf_counter() - t) * 1000)
        # per-query: best path at 3 and 5 hops (algo.SPpaths) and an edge-weight write, one at a time after a warm-up
        adj = snap.out_adj()
        tgt = {}
        for h in (3, 5):
            best = _limited_best(adj, src, h)[0]
            tgt[h] = max((t for t in best if t != src), key=lambda t: -np.log(best[t]))
        sp = lambda h: hg._rows("CALL algo.SPpaths({sourceNode: $s, targetNode: $t, relTypes: ['DEPENDS_ON'], relDirection: 'outgoing', maxLen: $m, weightProp: 'cost', costProp: 'cost', pathCount: 1}) YIELD path, pathCost RETURN path, pathCost",
                                s=base + src, t=base + tgt[h], m=h)
        (u0, v0), e0 = next(iter(snap.edges.items()))
        for _ in range(20):
            sp(3); sp(5)
        for h, bucket in ((3, q3), (5, q5)):
            for _ in range(200):
                t = time.perf_counter(); sp(h); bucket.append((time.perf_counter() - t) * 1000)
        for i in range(100):
            w = 0.5 + (i % 7) * 0.01
            t = time.perf_counter(); hg._set_edge(u0, v0, w=w, cost=cost_of(w)); wr.append((time.perf_counter() - t) * 1000)
        hg._set_edge(u0, v0, w=e0.w, cost=cost_of(e0.w))
        # verdict paths: in-memory graph (no store), a cold read of HydraDB every time
        g0 = GraphState.from_official(official_view(types.SimpleNamespace(components=co["components"], official_edges=co["official_edges"])))
        for _ in range(200):
            t = time.perf_counter(); walk(g0, al); mem_v.append((time.perf_counter() - t) * 1000)
        cold = HydraGraph(URL, TOKEN, run_id=hg.run_id, mode="cold"); cold.co = hg.co
        for _ in range(30):
            t = time.perf_counter(); walk(cold.snapshot(), al); cold_v.append((time.perf_counter() - t) * 1000)
        hg.drop()
    out = {"measured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "machine": machine(), "hydradb_image": os.environ.get("HYDRADB_IMAGE"),
           "companies": [{"name": c["name"], "services": len(c["components"]), "incidents": len(c["incidents"])} for c in cos],
           "online_loop": {"verdict_ms": pct([r["ms"] for r in rows]), "learning_write_ms": pct([r["apply_ms"] for r in rows if "apply_ms" in r]),
                           "full_graph_rereads": hg.full_reads, "cache_hits": hg.hits},
           "warm": {"one_hop_query_ms": pct(one_hop), "path_3_hops_ms": pct(q3), "path_5_hops_ms": pct(q5), "edge_write_ms": pct(wr),
                    "verdict_in_memory_ms": pct(mem_v), "verdict_cached_hit_ms": pct(hits), "verdict_cold_read_ms": pct(cold_v)},
           "note": "generated companies (hub and layered, 60 to 120 services), learning on, HydraDB write-through cache; not the DEV/TEST splits"}
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
