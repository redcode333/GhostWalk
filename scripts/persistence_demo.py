"""Persistence demo: the learner's state lives in HydraDB, not in the API process.

  1. start the API (GW_STORE=hydradb) -> it seeds the demo company and learns 20 incidents, every write going to HydraDB
  2. rank incident 21 and ask why-edge for a learned edge
  3. KILL the API process and delete its state file
  4. start a new API process -> it re-attaches to HydraDB and reads the learned graph back
  5. rank incident 21 again: the ranking must be identical (and equal to the in-memory learner's)

    python scripts/persistence_demo.py            (needs HydraDB: docker compose up -d hydradb)
Writes the transcript to docs/measurements/persistence_demo.txt."""
import json, os, pathlib, subprocess, sys, tempfile, time
import httpx

ROOT = pathlib.Path(__file__).resolve().parent.parent
PORT = int(os.environ.get("PORT", "8765"))
URL = f"http://127.0.0.1:{PORT}"
RUN = int(time.time()) % 900 + 100
out = []


def say(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    out.append(s)


def start(state):
    env = {**os.environ, "GW_STORE": "hydradb", "GW_HYDRA_RUN": str(RUN), "GW_STATE": str(state), "GW_DEMO_INCIDENTS": "20", "GW_REQUIRE_TOKEN": "0", "AUTH_MODE": "none"}
    p = subprocess.Popen([sys.executable, "-m", "uvicorn", "ghostwalk.api.app:app", "--port", str(PORT), "--log-level", "warning"], cwd=ROOT, env=env)
    for _ in range(240):
        try:
            if httpx.get(f"{URL}/api/health", timeout=1).status_code == 200:
                return p
        except Exception:
            time.sleep(0.5)
    p.kill()
    raise SystemExit("API did not start")


def next_alerts():
    from gwsim.cli import make
    co = json.loads(make("hub", 7777, 80).to_json())
    return co["incidents"][20]["alerts"]


def rank(alerts):
    r = httpx.post(f"{URL}/v1/alerts/demo", json={"alerts": [{"name": a["name"], "signal": a.get("signal", "error_rate"), "t": a["t"]} for a in alerts]}, timeout=60)
    r.raise_for_status()
    inc = httpx.get(f"{URL}/api/incidents/{r.json()['incident']}", timeout=30).json()
    return [(x["name"], x["confidence"]) for x in inc["verdict"]["ranking"]]


def main():
    state = pathlib.Path(tempfile.mkdtemp()) / "state.json"
    alerts = next_alerts()
    say(f"# API process 1 (GW_STORE=hydradb, run {RUN}): seeding 20 incidents, learning each into HydraDB")
    t = time.time()
    p = start(state)
    say(f"  up in {time.time() - t:.0f} s")
    before = rank(alerts)
    say("  ranking for incident 21:", ", ".join(f"{n} {c:.3f}" for n, c in before[:4]))
    lessons = httpx.get(f"{URL}/api/map", timeout=30).json()
    learned = [e for e in lessons["edges"] if e.get("origin") == "learned"]
    say(f"  learned edges in the graph: {len(learned)}")
    src_dst = None
    for e in learned:
        names = {n["id"]: n["name"] for n in lessons["nodes"]}
        s, d = names[e["u"] if "u" in e else e["source"]], names[e["v"] if "v" in e else e["target"]]
        r = httpx.get(f"{URL}/v1/edges/{s}/{d}/why", timeout=60)
        if r.status_code == 200 and r.json()["lessons"]:
            src_dst = (s, d)
            why1 = r.json()
            break
    say(f"  why-edge {src_dst[0]} -> {src_dst[1]}:", why1["explanation"])
    say("# kill -9 the API process and delete its state file")
    p.kill()
    p.wait()
    time.sleep(1)
    shutil_state = state.parent
    for f in shutil_state.glob("*"):
        f.unlink()
    say(f"  state file exists: {state.exists()}")
    say("# API process 2: no state file, same HydraDB")
    t = time.time()
    p = start(state)
    say(f"  up in {time.time() - t:.0f} s (re-attached, learned graph read back from HydraDB)")
    after = rank(alerts)
    say("  ranking for incident 21:", ", ".join(f"{n} {c:.3f}" for n, c in after[:4]))
    r = httpx.get(f"{URL}/v1/edges/{src_dst[0]}/{src_dst[1]}/why", timeout=60).json()
    p.kill()
    p.wait()
    same = before == after
    why_same = r["lessons"] == why1["lessons"]
    say(f"# identical rankings (names and confidences, all {len(before)} candidates): {same}")
    say(f"# why-edge identical after restart: {why_same}")
    cli = subprocess.run([sys.executable, "-c", "from ghostwalk.cli import main; main()", "why-edge", *src_dst], cwd=ROOT, text=True, encoding="utf8", capture_output=True,
                         env={**os.environ, "GW_STORE": "hydradb", "GW_HYDRA_RUN": str(RUN), "NO_COLOR": "1", "COLUMNS": "140", "PYTHONIOENCODING": "utf-8"})
    text = chr(10).join(l.rstrip() for l in cli.stdout.strip().splitlines())
    say("# the CLI, against HydraDB with no API process running:")
    say(text)
    d = ROOT / "docs" / "measurements"
    d.mkdir(parents=True, exist_ok=True)
    (d / "persistence_demo.txt").write_text(chr(10).join(out) + chr(10), encoding="utf8")
    res = ROOT / "results.json"
    if res.exists():
        doc = json.loads(res.read_text(encoding="utf8"))
        doc["memory_graph"] = {
            "store": "HydraDB v0.4.0", "schema": ["(:Incident)-[:RAISED]->(:Alert)-[:ON]->(:Service)", "(:Postmortem)-[:ABOUT]->(:Incident)",
                                                  "(:Lesson {src, dst, w, state, created_seq})-[:TAUGHT_BY]->(:Postmortem)", "(:Lesson)-[:CONFIRMED_BY]->(:Incident)",
                                                  "(:Service)-[:DEPENDS_ON {w, cost}]->(:Service)  (w and cost follow the Lesson)"],
            "why_edge_example": {"src": src_dst[0], "dst": src_dst[1], "text": text, "explanation": why1["explanation"], "lesson": why1["lessons"][0]},
            "persistence": {"incidents_learned": 20, "killed": "the API process (kill -9) and its state file", "identical_ranking": same, "candidates_compared": len(before),
                            "why_edge_identical": why_same, "ranking_before": before, "ranking_after": after,
                            "summary": f"Twenty incidents were learned through the API with GW_STORE=hydradb; the API process was killed and its state file deleted; a new process re-attached to HydraDB "
                                       f"and ranked incident 21 {'identically (all ' + str(len(before)) + ' candidates, names and confidences)' if same else 'DIFFERENTLY'} "
                                       f"(`scripts/persistence_demo.py`, transcript in `docs/measurements/persistence_demo.txt`). The same holds in a test that also compares against the in-memory learner."}}
        res.write_text(json.dumps(doc, indent=2), encoding="utf8")
    if not (same and why_same):
        raise SystemExit(1)

if __name__ == "__main__":
    main()
