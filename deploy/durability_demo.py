"""Durability demo: HydraDB's local data is only a cache; the graph lives in object storage (MinIO).

    python deploy/durability_demo.py --api https://<API_DOMAIN> [--insecure]        # or: make durability-demo API=https://<API_DOMAIN>

  1. rank a fixed incident and ask why-edge about a learned edge
  2. stop the whole stack and DELETE ONLY HydraDB's local volume (the MinIO volume is kept)
  3. start the stack again (HydraDB comes up empty-handed and reads the graph back from MinIO)
  4. rank the same incident and ask the same why-edge: both must be identical
Run it from the repository root on the machine that runs the stack (it calls docker compose with deploy/.env)."""
import argparse, json, os, subprocess, sys, time
import httpx

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="https://localhost")
    ap.add_argument("--insecure", action="store_true")
    ap.add_argument("--project", default="ghostwalk-prod")
    ap.add_argument("--ssh", default=None, help="user@host: run the docker commands on that machine (the stack runs there), the API calls still go to --api")
    a = ap.parse_args()
    import shlex
    def sh(cmd, **kw):
        cmd = list(cmd)
        if a.ssh:
            cmd = ["ssh", "-o", "BatchMode=yes", a.ssh, "cd GhostWalk && " + shlex.join(cmd)]
        return subprocess.run(cmd, **kw)
    dc = ["docker", "compose", "--env-file", "deploy/.env", "-f", "deploy/docker-compose.prod.yml"]
    c = httpx.Client(timeout=60, verify=not a.insecure)
    api = a.api.rstrip("/")
    from gwsim.cli import make
    co = json.loads(make("hub", 7777, 80).to_json())
    alerts = [{"name": x["name"], "signal": x.get("signal", "error_rate"), "t": x["t"]} for x in co["incidents"][20]["alerts"]]

    def snapshot():
        r = c.post(f"{api}/v1/alerts/demo", json={"alerts": alerts}).raise_for_status().json()
        ranking = [(x["name"], x["confidence"]) for x in c.get(f"{api}/api/incidents/{r['incident']}").json()["verdict"]["ranking"]]
        m = c.get(f"{api}/api/map").json()
        names = {n["id"]: n["name"] for n in m["nodes"]}
        why = None
        for e in sorted(m["learned"], key=lambda e: (e["u"], e["v"])):
            w = c.get(f"{api}/v1/edges/{names[e['u']]}/{names[e['v']]}/why")
            if w.status_code == 200 and w.json()["lessons"]:
                why = {"edge": [names[e["u"]], names[e["v"]]], "lessons": w.json()["lessons"]}
                break
        health = c.get(f"{api}/api/health").json()
        return ranking, why, health

    def wait():
        for _ in range(120):
            try:
                if c.get(f"{api}/api/health").status_code == 200:
                    return
            except Exception:
                pass
            time.sleep(2)
        raise SystemExit("the API did not come back")

    before, why_before, h = snapshot()
    print(f"before: store={h['store']} revision={h['revision']} ranking {before[:3]} why-edge {why_before['edge'] if why_before else None}")
    vols = sh(["docker", "volume", "ls", "--format", "{{.Name}}"], capture_output=True, text=True).stdout.split()
    hv, mv = f"{a.project}_hydradb-data", f"{a.project}_minio-data"
    assert hv in vols and mv in vols, (hv, mv, vols)
    print(f"stop the stack, delete ONLY {hv} (keep {mv})")
    sh(dc + ["stop"], check=True, capture_output=True)
    sh(dc + ["down"], check=True, capture_output=True)                              # containers only: volumes stay
    sh(["docker", "volume", "rm", hv], check=True, capture_output=True)
    assert mv in sh(["docker", "volume", "ls", "--format", "{{.Name}}"], capture_output=True, text=True).stdout.split()
    sh(dc + ["up", "-d"], check=True, capture_output=True)
    wait()
    after, why_after, h2 = snapshot()
    print(f"after:  store={h2['store']} revision={h2['revision']} ranking {after[:3]} why-edge {why_after['edge'] if why_after else None}")
    same = before == after and why_before == why_after and why_before is not None
    print("identical ranking and why-edge after deleting HydraDB's local data:", same)
    sys.exit(0 if same else 1)


if __name__ == "__main__":
    main()
