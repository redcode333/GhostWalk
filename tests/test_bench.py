import json, subprocess, sys, pathlib, time
import numpy as np
from fastapi.testclient import TestClient
from gwsim.world import build_company, Knobs
from ghostwalk.api.app import create_app
from ghostwalk.api.workspace import Workspace

ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_scaled_graphs_keep_the_tier_mix_and_the_small_benchmark_is_untouched():
    co = json.loads(build_company("b", "layered", 5, n=1000, knobs=Knobs(n_incidents=3)).to_json())
    tiers = [sum(1 for c in co["components"] if c["tier"] == k) for k in range(4)]
    assert len(co["components"]) == 1000 and tiers[0] == 2
    assert abs(tiers[1] / 1000 - 0.16) < 0.01 and abs(tiers[3] / 1000 - 0.28) < 0.01
    dev = ROOT / "data/dev/layered-1000.json"
    if dev.exists():                                  # the frozen 30-120 service companies must not change
        from gwsim.cli import splits, make
        _, _, sizes = splits()
        assert json.loads(make("layered", 1000, sizes[1000]).to_json()) == json.loads(dev.read_text())


def test_bench_script_writes_a_latency_section_and_the_gate(tmp_path):
    out = tmp_path / "r.json"
    out.write_text(json.dumps({"keep": 1}))
    r = subprocess.run([sys.executable, str(ROOT / "eval/bench.py"), "--sizes", "100", "1000", "--incidents", "20", "--out", str(out)], capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stderr
    d = json.loads(out.read_text())
    assert d["keep"] == 1                                    # merged, not overwritten
    lat = d["latency"]
    for n in ("100", "1000"):
        m = lat["sizes"][n]["in_memory_ms"]
        assert 0 < m["p50"] <= m["p95"] <= m["p99"] <= m["max"] and lat["sizes"][n]["hydradb_ms"] is None
    assert lat["gate"]["stopped_at_1000"] is True and lat["gate"]["rust_port"] == "5,000-service size not run"
    assert "not run" in lat["hydradb"]["status"] and lat["meta"]["git"] is not None


def test_proof_json_is_parsed_once_per_file_version(tmp_path, monkeypatch):
    res = tmp_path / "results.json"
    res.write_text(json.dumps({"a": 1}))
    c = TestClient(create_app(workspace=Workspace(None, demo_incidents=2), results_path=res))
    calls = []
    real = json.loads
    monkeypatch.setattr("ghostwalk.api.app.json.loads", lambda *a, **k: (calls.append(1) if a and a[0] == '{"a": 1}' else None, real(*a, **k))[1])
    for _ in range(5):
        assert c.get("/api/proof").json() == {"a": 1}
    assert len(calls) == 1
    time.sleep(0.01)
    res.write_text(json.dumps({"a": 2}))
    assert c.get("/api/proof").json() == {"a": 2}
