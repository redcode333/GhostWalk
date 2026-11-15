import hashlib, hmac, json, time
from fastapi.testclient import TestClient
from typer.testing import CliRunner
from ghostwalk import mcp_tools
from ghostwalk.api.app import create_app
from ghostwalk.api.workspace import Workspace
from ghostwalk.cli import app


def _alerts(inc):
    return [{"name": a["name"], "signal": a["signal"], "t": a["t"]} for a in inc["alerts"]]


def test_post_changes_and_the_verdict_line():
    w = Workspace(None, demo_incidents=4, use_changes=True)
    c = TestClient(create_app(workspace=w, results_path="x.json"))
    inc = w.incidents[-1]
    root = inc["verdict"]["root_name"]
    r = c.post("/v1/changes", json={"service": root, "ts": time.time() - 60, "kind": "deploy", "ref": "#482"})
    assert r.status_code == 200 and r.json()["service"] == root
    assert c.post("/v1/changes", json={"service": "nope"}).status_code == 422
    assert c.post("/v1/changes", json={}).status_code == 422
    n = w.ingest_alerts(_alerts(inc))
    if n["verdict"]["root_name"] == root:
        assert n["verdict"]["change_note"] == f"{root} changed 1 min before the first alert (deploy #482)"
    out = mcp_tools.why(w, _alerts(inc))
    if out["root"] == root:
        assert out["change_note"] == f"{root} changed 1 min before the first alert (deploy #482)" and "changed 1 min" in out["explanation"]


def test_changes_are_ignored_without_the_flag():
    w = Workspace(None, demo_incidents=3, use_changes=False)
    w.add_change(w.incidents[-1]["verdict"]["root_name"], time.time() - 30, "deploy", "#1")
    inc = w.ingest_alerts(_alerts(w.incidents[-1]))
    assert inc["verdict"]["change_note"] is None


def test_github_deployment_and_release_events_become_changes(monkeypatch):
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "s")
    w = Workspace(None, demo_incidents=2)
    svc = list(w.g.components.values())[3]["name"]
    c = TestClient(create_app(workspace=w, results_path="x.json"))

    def send(event, payload):
        raw = json.dumps(payload).encode()
        h = {"x-github-event": event, "x-hub-signature-256": "sha256=" + hmac.new(b"s", raw, hashlib.sha256).hexdigest(), "content-type": "application/json"}
        return c.post("/api/webhooks/github", content=raw, headers=h).json()

    ok = send("deployment_status", {"deployment_status": {"state": "success", "created_at": "2026-11-15T14:00:00Z"}, "deployment": {"id": 482, "payload": {"service": svc}}, "repository": {"name": "x"}})
    assert ok["recorded"]["service"] == svc and ok["recorded"]["ref"] == "#482" and ok["recorded"]["ts"] > 1e9
    assert send("deployment_status", {"deployment_status": {"state": "failure"}, "deployment": {"id": 1}, "repository": {"name": svc}}) == {"ignored": True}
    rel = send("release", {"action": "published", "release": {"tag_name": "v1.4", "published_at": "2026-11-15T15:00:00Z"}, "repository": {"name": svc}})
    assert rel["recorded"]["kind"] == "release" and rel["recorded"]["ref"] == "v1.4"
    assert "ignored" in send("deployment", {"deployment": {"id": 2}, "repository": {"name": "unknown-repo"}})


def test_gw_change_add_cli(tmp_path):
    home = tmp_path / ".gw"
    Workspace(home / "state.json", demo_incidents=2).save()
    svc = list(Workspace(home / "state.json").g.components.values())[2]["name"]
    r = CliRunner().invoke(app, ["change", "add", svc, "--kind", "config", "--ref", "#9"], env={"GW_HOME": str(home)})
    assert r.exit_code == 0 and "config #9" in r.output
    assert Workspace(home / "state.json").changes[-1]["service"] == svc
    assert CliRunner().invoke(app, ["change", "add", "nope"], env={"GW_HOME": str(home)}).exit_code == 1
