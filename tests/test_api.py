import hashlib, hmac, json, os
import pytest
from fastapi.testclient import TestClient

os.environ["GW_AUTOSTART"] = "0"
from ghostwalk.api.app import create_app
from ghostwalk.api.alerts import normalize
from ghostwalk.api.workspace import Workspace


@pytest.fixture(scope="module")
def ws():
    return Workspace(None, demo_incidents=12)


@pytest.fixture()
def client(ws, tmp_path):
    res = tmp_path / "results.json"
    res.write_text(json.dumps({"headline": {"x": 1}}))
    return TestClient(create_app(workspace=ws, results_path=res))


def test_summary_and_incident_list(client):
    s = client.get("/api/summary").json()
    assert s["services"] == 80 and s["mode"] == "demo" and s["store"]["label"] == "In-memory graph"
    rows = client.get("/api/incidents").json()
    assert rows[0]["status"] == "Needs postmortem" and rows[0]["id"].startswith("INC-")
    assert all(0 <= r["confidence"] <= 1 for r in rows)


def test_incident_detail_has_verdict_path_and_blast_radius(client):
    inc = client.get("/api/incidents").json()[0]["id"]
    d = client.get(f"/api/incidents/{inc}").json()
    v = d["verdict"]
    assert v["ranking"][0]["confidence"] >= v["ranking"][1]["confidence"] and v["ms"] >= 0
    assert any(b["root"] for b in v["blast"]) and v["explains"] <= v["of"]
    assert client.get("/api/incidents/INC-9999").status_code == 404


def test_proof_reads_results_json(client):
    assert client.get("/api/proof").json() == {"headline": {"x": 1}}


def test_trigger_and_test_alert(client):
    n = len(client.get("/api/incidents").json())
    r = client.post("/api/incidents/trigger").json()
    assert client.get(f"/api/incidents/{r['id']}").json()["status"] == "Open"
    t = client.post("/api/test-alert").json()
    assert t["root"] and len(client.get("/api/incidents").json()) == n + 2
    assert client.get("/api/summary").json()["onboarding"]["alert"] is True


def test_webhook_formats():
    am = {"alerts": [{"status": "firing", "labels": {"alertname": "HighErrors", "service": "checkout-api"}, "startsAt": "2026-11-15T14:02:30Z"},
                     {"status": "firing", "labels": {"alertname": "Lag", "job": "payments"}, "startsAt": "2026-11-15T14:02:00Z"},
                     {"status": "resolved", "labels": {"service": "old"}, "startsAt": "2026-11-15T14:00:00Z"}]}
    out = normalize(am)
    assert [a["name"] for a in out] == ["payments", "checkout-api"] and out[1]["t"] == 30.0
    # The generic webhook normalizer accepts a Grafana-shaped alert and the supported
    # PagerDuty-style nested service summary; neither is a native vendor connection.
    assert normalize({"alerts": [{"status": "firing", "labels": {"alertname": "HighErrors", "service": "checkout-api"}, "startsAt": "2026-11-15T14:02:30Z"}]})[0]["name"] == "checkout-api"
    assert normalize({"incident": {"service": {"summary": "payments"}}, "alertType": "trigger"})[0]["name"] == "payments"
    assert normalize({"monitorFriendlyName": "search", "alertType": "down"})[0]["name"] == "search"
    with pytest.raises(ValueError):
        normalize({"alerts": []})


def test_alert_webhook_creates_incident_and_needs_token_when_required(client, monkeypatch):
    names = [c["name"] for c in list(client.app.state.ws.g.components.values())[:3]]
    body = {"alerts": [{"name": n, "signal": "error_rate", "t": i * 10} for i, n in enumerate(names)]}
    r = client.post("/v1/alerts/acme", json=body)
    assert r.status_code == 200 and r.json()["incident"].startswith("INC-")
    monkeypatch.setenv("GW_REQUIRE_TOKEN", "1")
    assert client.post("/v1/alerts/acme", json=body).status_code == 401
    tok = client.app.state.ws.issue_token()                       # only a hash is stored: the token is shown once, when it is issued
    ok = client.post("/v1/alerts/acme", json=body, headers={"Authorization": "Bearer " + tok})
    assert ok.status_code == 200
    assert client.post("/v1/alerts/acme", json={"alerts": []}, headers={"x-gw-token": tok}).status_code == 422
    assert client.post("/v1/alerts/acme", json=body, headers={"Authorization": "Bearer " + tok[:-1] + "0"}).status_code == 401


def test_learn_preview_then_apply_changes_the_graph(client):
    w = client.app.state.ws
    inc = w.incidents[-1]
    root = inc["verdict"]["ranking"][1]["name"] if len(inc["verdict"]["ranking"]) > 1 else inc["verdict"]["root_name"]
    entry = inc["verdict"]["entry_name"]
    fields = {"root": root, "path": f"{root} -> {entry}", "missed": ""}
    before = len(w.g.edges)
    pv = client.post(f"/api/learn/{inc['id']}/preview", json=fields).json()
    assert pv["root_name"] == root and len(w.g.edges) == before        # preview writes nothing
    q = client.post(f"/api/learn/{inc['id']}/queue", json=fields).json()
    assert client.get("/api/learn/queue").json()[0]["id"] == q["id"]
    rev = w.revision
    client.post(f"/api/learn/pending/{q['id']}/apply", json={"reject": []})
    assert w.revision == rev + 1 and client.get(f"/api/incidents/{inc['id']}").json()["status"] == "Resolved"
    assert client.post(f"/api/learn/{inc['id']}/preview", json={"root": "no-such-svc", "path": "", "missed": ""}).status_code == 422


def test_settings_token_flow(client):
    s = client.get("/api/settings").json()
    assert s["webhook_url"].endswith("/v1/alerts/acme") and "•" in s["token_masked"]
    assert client.post("/api/settings/token/reveal").status_code == 410         # a stored token cannot be shown again
    first = client.post("/api/settings/token/rotate").json()
    second = client.post("/api/settings/token/rotate").json()
    assert first["shown_once"] and first["token"].startswith("gw_live_") and second["token"] != first["token"]
    assert not client.app.state.ws.token_ok(first["token"]) and client.app.state.ws.token_ok(second["token"])


def test_onboarding_scan_accept_replaces_map_and_test_alert_works():
    w = Workspace(None, demo_incidents=3)
    c = TestClient(create_app(workspace=w, results_path="nope.json"))
    out = c.post("/api/onboarding/scan", json={"source": "sample"}).json()
    assert out["summary"]["services"] > 10 and out["summary"]["dependencies"] > 15 and w.map_proposals
    assert all({"src", "dst", "repo", "file", "evidence", "confidence"} <= set(e) for e in out["edges"])
    assert w.g.components and len(w.g.components) == 80                    # nothing official yet
    accepted = [e["id"] for e in out["edges"] if e["accepted"]]
    before = client_map = c.get("/api/map").json()
    blocked = c.post("/api/onboarding/accept", json={"edge_ids": accepted})
    assert blocked.status_code == 400 and len(c.get("/api/map").json()["nodes"]) == len(before["nodes"])
    r = c.post("/api/onboarding/accept", json={"edge_ids": accepted, "replace_existing": True}).json()
    assert w.mode == "imported" and len(w.g.components) == r["services"] and r["dependencies"] == len(accepted)
    assert all(e.origin == "official" and e.w == 0.7 for e in w.g.edges.values())
    t = c.post("/api/test-alert").json()
    assert t["root"] in {x["name"] for x in w.g.components.values()}
    assert c.get("/api/summary").json()["onboarding"]["alert"] is True
    assert c.get("/api/onboarding").json()["steps"]["github"] is False  # sample repository files are not a GitHub connection


def test_postmortem_pr_falls_back_to_link_without_a_write_token(client, monkeypatch):
    monkeypatch.delenv("GITHUB_PR_TOKEN", raising=False)
    r = client.post("/api/onboarding/postmortem-pr", json={"repo": "acme/infra"}).json()
    assert r["mode"] == "link" and "read-only" in r["why"] and r["url"].startswith("https://github.com/acme/infra/new/")


def test_github_webhook_turns_issue_form_into_proposals(client, monkeypatch):
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "s3cret")
    w = client.app.state.ws
    inc = next(i for i in reversed(w.incidents) if i["status"] != "Resolved")
    a, b = inc["verdict"]["ranking"][0]["name"], inc["verdict"]["entry_name"]
    body = f"### Actual root cause\n\n{a}\n\n### How it reached the alerting service\n\n{a} -> {b}\n\n### What the map got wrong (optional)\n\n_No response_\n"
    payload = {"action": "labeled", "label": {"name": "postmortem"}, "repository": {"full_name": "acme/infra"},
               "issue": {"number": 7, "title": f"{inc['id']}: it was {a}", "body": body, "labels": [{"name": "postmortem"}]}}
    raw = json.dumps(payload).encode()
    sign = lambda s: "sha256=" + hmac.new(s.encode(), raw, hashlib.sha256).hexdigest()
    hdr = lambda sig: {"x-github-event": "issues", "x-hub-signature-256": sig, "content-type": "application/json"}
    assert client.post("/api/webhooks/github", content=raw, headers=hdr(sign("wrong"))).status_code == 401
    n = len(w.pending)
    r = client.post("/api/webhooks/github", content=raw, headers=hdr(sign("s3cret"))).json()
    assert r["queued"] and r["incident"] == inc["id"] and len(w.pending) == n + 1
    client.post("/api/webhooks/github", content=raw, headers=hdr(sign("s3cret")))      # an edited issue replaces its proposal
    assert len(w.pending) == n + 1
    other = dict(payload, label={"name": "bug"}, issue=dict(payload["issue"], labels=[{"name": "bug"}]))
    raw2 = json.dumps(other).encode()
    h2 = {"x-github-event": "issues", "x-hub-signature-256": "sha256=" + hmac.new(b"s3cret", raw2, hashlib.sha256).hexdigest()}
    assert client.post("/api/webhooks/github", content=raw2, headers=h2).json() == {"ignored": True}


def test_state_survives_restart(tmp_path):
    p = tmp_path / "state.json"
    a = Workspace(p, demo_incidents=5)
    a.reset_learned()
    a.test_alert()
    b = Workspace(p)
    assert len(b.incidents) == len(a.incidents) and b.token_hash == a.token_hash and b.g.edges.keys() == a.g.edges.keys()


def test_inside_demo_is_computed_by_the_engine(client):
    d = client.get("/api/demo/inside").json()
    assert d["before"]["ranking"][0]["name"] != d["after"]["ranking"][0]["name"] == "config-svc"
    assert any(e["origin"] == "learned" for e in d["after"]["path"]) and d["learned_edges"] and d["changes"]


def test_there_is_no_service_limit_and_a_burst_is_rate_limited(monkeypatch):
    """No plan limit: a map of any size is accepted, signed in or not. Only the per-client abuse guard can refuse, with 429."""
    from ghostwalk.api.app import clerk_user
    w = Workspace(None, demo_incidents=2)
    app = create_app(workspace=w, results_path="nope.json")
    app.dependency_overrides[clerk_user] = lambda: {"id": "u1"}
    c = TestClient(app)
    big = {"services": [{"name": f"s{i}", "kind": "service"} for i in range(80)],
           "edges": [{"id": f"s{i}>s{i+1}", "src": f"s{i}", "dst": f"s{i+1}"} for i in range(79)]}
    ids = [e["id"] for e in big["edges"]]
    for mode in ("none", "clerk"):
        monkeypatch.setenv("AUTH_MODE", mode)
        w.map_proposals = big
        assert c.post("/api/onboarding/accept", json={"edge_ids": ids, "replace_existing": True}).status_code == 200


def test_rate_limit_is_a_quiet_429_with_a_plain_message(monkeypatch):
    monkeypatch.setenv("GW_RATE_LIMIT", "5/60")
    c = TestClient(create_app(workspace=Workspace(None, demo_incidents=2), results_path="nope.json"))
    codes = [c.post("/api/onboarding/accept", json={"edge_ids": []}).status_code for _ in range(8)]
    assert 429 in codes and codes.index(429) == 5
    r = c.post("/api/onboarding/accept", json={"edge_ids": []})
    assert r.json()["detail"] == "Slow down, try again in a minute"


def test_rate_limit_is_off_unless_configured(monkeypatch):
    monkeypatch.delenv("GW_RATE_LIMIT", raising=False)
    c = TestClient(create_app(workspace=Workspace(None, demo_incidents=2), results_path="nope.json"))
    assert all(c.post("/api/onboarding/accept", json={"edge_ids": []}).status_code != 429 for _ in range(120))


def test_health_reports_the_version(monkeypatch):
    monkeypatch.setenv("GW_VERSION", "abc1234")
    c = TestClient(create_app(workspace=Workspace(None, demo_incidents=2), results_path="nope.json"))
    assert c.get("/api/health").json()["version"] == "abc1234" and c.get("/health").json()["version"] == "abc1234"


def test_scan_pasted_files_and_accept_a_large_map(monkeypatch):
    """A 35-service compose file pasted in is scanned and accepted whole: there is no service limit, signed in or not."""
    from ghostwalk.api.app import clerk_user
    nl = chr(10)
    compose = "services:" + nl + "".join(f"  svc-{i}:" + nl + f"    image: acme/svc-{i}" + nl + (f"    depends_on: [svc-{i - 1}]" + nl if i else "") for i in range(35))
    w = Workspace(None, demo_incidents=2)
    app = create_app(workspace=w, results_path="nope.json")
    app.dependency_overrides[clerk_user] = lambda: {"id": "u1"}
    c = TestClient(app)
    monkeypatch.setenv("AUTH_MODE", "clerk")
    out = c.post("/api/onboarding/scan", json={"source": "files", "files": [{"repo": "acme/infra", "path": "docker-compose.yml", "text": compose}]}).json()
    assert out["summary"]["services"] == 35
    r = c.post("/api/onboarding/accept", json={"edge_ids": [e["id"] for e in out["edges"]], "replace_existing": True})
    assert r.status_code == 200 and r.json()["services"] == 35
    assert c.post("/api/onboarding/scan", json={"source": "files", "files": []}).status_code == 422
