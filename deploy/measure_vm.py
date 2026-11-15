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
from ghostwalk.engine.walk import walk
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
            "kernel": platform.release(), "platform": platform.platform(), "python": platform.python_version(), "hydradb_url": URL,
            "note": "client (the API container) and HydraDB are containers on one docker network: no published-port proxy hop"}


def main():
    hg = HydraGraph(URL, TOKEN, run_id=int(time.time()) % 900 + 50)
    cos = [json.loads(make(f, s, n).to_json()) for f, s, n in (("hub", 31, 60), ("layered", 32, 90), ("hub", 33, 120))]
    rows, hits, one_hop = [], [], []
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
        hg.drop()
    out = {"measured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "machine": machine(), "hydradb_image": os.environ.get("HYDRADB_IMAGE"),
           "companies": [{"name": c["name"], "services": len(c["components"]), "incidents": len(c["incidents"])} for c in cos],
           "online_loop": {"verdict_ms": pct([r["ms"] for r in rows]), "learning_write_ms": pct([r["apply_ms"] for r in rows if "apply_ms" in r]),
                           "full_graph_rereads": hg.full_reads, "cache_hits": hg.hits},
           "warm": {"one_hop_query_ms": pct(one_hop), "verdict_cached_hit_ms": pct(hits)},
           "note": "generated companies (hub and layered, 60 to 120 services), learning on, HydraDB write-through cache; not the DEV/TEST splits"}
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
