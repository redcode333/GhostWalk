"""Load test of the verdict endpoint: concurrency 1 / 10 / 50 / 100, a fixed time per level.

    python eval/loadtest.py --url http://127.0.0.1:8000 [--levels 1,10,50,100] [--seconds 10] [--out loadtest.json]
    make loadtest URL=http://127.0.0.1:8000

Every request is POST /v1/alerts/demo with the alerts of a demo incident, so it measures the whole path: parse, resolve, walk, record the incident, save state.
Reports requests per second, latency p50/p95/p99, errors, and (when run inside a container with cgroup v2) the container's CPU and memory. Nothing is tuned.
Rate limiting must be off on the target (GW_RATE_LIMIT=0), otherwise you are measuring the limiter (429s are counted as errors)."""
from __future__ import annotations
import argparse, asyncio, json, os, platform, sys, time
import httpx
import numpy as np


def cgroup():
    """(cpu seconds used, memory bytes, cpu count) of this container, or None outside cgroup v2."""
    try:
        cpu = next(int(l.split()[1]) for l in open("/sys/fs/cgroup/cpu.stat") if l.startswith("usage_usec")) / 1e6
        mem = int(open("/sys/fs/cgroup/memory.current").read())
        return cpu, mem
    except Exception:
        return None


def alerts_payload():
    sys.path.insert(0, "/app" if os.path.isdir("/app/gwsim") else ".")
    from gwsim.cli import make
    co = json.loads(make("hub", 7777, 80).to_json())
    return {"alerts": [{"name": a["name"], "signal": a.get("signal", "error_rate"), "t": a["t"]} for a in co["incidents"][20]["alerts"]]}


async def level(url, payload, conc, seconds):
    lat, errors, codes = [], 0, {}
    stop = time.perf_counter() + seconds
    limits = httpx.Limits(max_connections=conc, max_keepalive_connections=conc)
    async with httpx.AsyncClient(limits=limits, timeout=60) as c:
        async def worker():
            nonlocal errors
            while time.perf_counter() < stop:
                t = time.perf_counter()
                try:
                    r = await c.post(url, json=payload)
                    codes[r.status_code] = codes.get(r.status_code, 0) + 1
                    if r.status_code != 200:
                        errors += 1
                except Exception:
                    errors += 1
                    codes["exc"] = codes.get("exc", 0) + 1
                lat.append((time.perf_counter() - t) * 1000)
        before, t0 = cgroup(), time.perf_counter()
        await asyncio.gather(*[worker() for _ in range(conc)])
        wall, after = time.perf_counter() - t0, cgroup()
    a = np.array(lat)
    out = {"concurrency": conc, "seconds": round(wall, 1), "requests": int(len(a)), "req_per_s": round(len(a) / wall, 1), "errors": errors, "status_codes": {str(k): v for k, v in codes.items()},
           "latency_ms": {"p50": float(np.percentile(a, 50)), "p95": float(np.percentile(a, 95)), "p99": float(np.percentile(a, 99)), "max": float(a.max())}}
    if before and after:
        out["container_cpu_percent_of_one_core"] = round((after[0] - before[0]) / wall * 100, 1)
        out["container_memory_mb"] = round(after[1] / 2**20, 1)
    return out


async def main_async(a):
    payload = alerts_payload()
    url = a.url.rstrip("/") + "/v1/alerts/demo"
    async with httpx.AsyncClient(timeout=30) as c:                      # one warm-up request, and a check that the target answers
        r = await c.post(url, json=payload)
        r.raise_for_status()
    rows = []
    for conc in [int(x) for x in a.levels.split(",")]:
        row = await level(url, payload, conc, a.seconds)
        rows.append(row)
        print(f"concurrency {conc:>3}: {row['req_per_s']:>7} req/s  p50 {row['latency_ms']['p50']:.1f}  p95 {row['latency_ms']['p95']:.1f}  p99 {row['latency_ms']['p99']:.1f} ms  errors {row['errors']}", file=sys.stderr, flush=True)
    return {"measured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "target": a.url, "endpoint": "POST /v1/alerts/demo", "seconds_per_level": a.seconds,
            "machine": {"label": os.environ.get("GW_MEASURED_ON", "unlabelled"), "cpus": os.cpu_count(), "platform": platform.platform(), "python": platform.python_version()},
            "levels": rows}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--levels", default="1,10,50,100")
    ap.add_argument("--seconds", type=float, default=10.0)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    res = asyncio.run(main_async(a))
    text = json.dumps(res, indent=2)
    if a.out:
        open(a.out, "w", encoding="utf8").write(text)
    else:
        print(text)


if __name__ == "__main__":
    main()
