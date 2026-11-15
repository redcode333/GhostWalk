import json, pathlib
from typer.testing import CliRunner
from ghostwalk.cli import app as main
from ghostwalk.api.samples import SAMPLE_FILES

RESULTS = {"meta": {"companies": 30, "split": "test", "git": {"short": "abc1234"}, "timestamp_utc": "2026-11-15T00:00:00+00:00"},
           "methods": {k: {"ac1": {"point": p, "ci95": [p - .02, p + .02]}} for k, p in
                       {"oracle": .8, "ghostwalk": .7, "learning_off": .6, "deepest": .5}.items()},
           "headline": {"gain_vs_best": {"point": .2, "baseline": "deepest"}, "gap_closed": {"point": .5}}}


def run(args, env, **kw):
    return CliRunner().invoke(main, args, env=env, catch_exceptions=False, **kw)


def test_map_import_why_learn_roundtrip(tmp_path):
    root = tmp_path / "acme"
    for repo, path, text in SAMPLE_FILES:
        p = root / repo.split("/")[1] / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    env = {"GW_HOME": str(tmp_path / ".gw")}
    r = run(["map", "import", str(root)], env)
    assert "scanning 3 repos" in r.output and "docker-compose.yml" in r.output and "services ·" in r.output and "dependencies" in r.output
    alerts = tmp_path / "alerts.json"
    alerts.write_text(json.dumps({"alerts": [{"labels": {"alertname": "E", "service": s}, "startsAt": f"2026-11-15T14:0{i}:00Z"}
                                             for i, s in enumerate(["config-svc", "pricing", "checkout-api"])]}))
    w = run(["why", "--alerts", str(alerts)], env)
    assert "rank  service" in w.output and "path  " in w.output and "explains" in w.output and "█" in w.output
    inc = [t for t in w.output.split() if t.startswith("INC-")][0]
    l = run(["learn", inc, "--root", "config-svc", "--path", "config-svc -> pricing -> checkout-api", "--missed", '"cfg" is config-svc', "-y"], env)
    assert "reading postmortem · 3 fields" in l.output and "graph updated · revision" in l.output


def test_eval_prints_numbers_from_results_json_only(tmp_path):
    p = tmp_path / "results.json"
    p.write_text(json.dumps(RESULTS))
    out = run(["eval", "--results", str(p)], {}).output
    assert "30 held-out companies" in out and "perfect map" in out and "0.700" in out
    assert "+20.0 pts (deepest)" in out and "gap closed 50%" in out and "abc1234" in out
    RESULTS["headline"]["gain_vs_best"]["point"] = .123
    p.write_text(json.dumps(RESULTS))
    assert "+12.3 pts" in run(["eval", "--results", str(p)], {}).output       # nothing is hard-coded


def test_missing_map_is_a_clear_error(tmp_path):
    r = CliRunner().invoke(main, ["why", "--alerts", str(tmp_path / "x.json")], env={"GW_HOME": str(tmp_path / "n")})
    assert r.exit_code != 0


def test_why_edge_explains_that_lineage_needs_hydradb(tmp_path):
    from ghostwalk.api.workspace import Workspace
    Workspace(tmp_path / ".gw" / "state.json", demo_incidents=4).save()
    r = CliRunner().invoke(main, ["why-edge", "web-bff", "payments-api"], env={"GW_HOME": str(tmp_path / ".gw")}, catch_exceptions=False)
    assert r.exit_code == 1 and "HydraDB" in r.output
