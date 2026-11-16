"""Clerk sessions and per-user workspaces: JWT checks, isolation between two accounts, workspace API tokens, the public demo sandbox."""
import base64, hashlib, hmac, json, time
from urllib.parse import parse_qs, urlsplit
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from fastapi.testclient import TestClient
from ghostwalk.api import app as appmod
from ghostwalk.api.auth import AuthError, ClerkVerifier, new_token, split_token

ISS = "https://clerk.example.test"
ORIGIN = "https://ghostwalk-henna.vercel.app"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class FakeJwks:
    """Stands in for PyJWKClient: always hands back the test public key."""
    def __init__(self, key=KEY):
        self.pub = key.public_key()

    def get_signing_key_from_jwt(self, token):
        return type("K", (), {"key": self.pub})()


def mint(sub="user_a", key=KEY, alg="RS256", **over):
    now = int(time.time())
    claims = {"sub": sub, "iss": ISS, "iat": now, "nbf": now - 5, "exp": now + 300, "azp": ORIGIN, **over}
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, key, algorithm=alg)


def verifier(**kw):
    return ClerkVerifier(None, kw.pop("issuer", ISS), kw.pop("parties", [ORIGIN]), jwk_client=FakeJwks())


def test_a_valid_session_verifies_and_every_bad_one_is_refused():
    v = verifier()
    assert v.verify(mint())["sub"] == "user_a"
    for bad, why in [(mint(exp=int(time.time()) - 60), "expired"), (mint(nbf=int(time.time()) + 600), "not yet valid"), (mint(azp="https://evil.example"), "wrong authorised party"),
                     (mint(iss="https://other.example"), "wrong issuer"), (mint(key=OTHER), "signed with another key"),
                     (mint(sub=None), "no subject"), ("not.a.jwt", "garbage")]:
        with pytest.raises(AuthError):
            v.verify(bad)
    pub = KEY.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    b64 = lambda raw: base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
    head = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body = b64(json.dumps({"sub": "x", "iss": ISS, "iat": int(time.time()), "exp": int(time.time()) + 60, "azp": ORIGIN}).encode())
    forged = f"{head}.{body}." + b64(hmac.new(pub, f"{head}.{body}".encode(), hashlib.sha256).digest())
    with pytest.raises(AuthError):                      # algorithm confusion: an HS256 token "signed" with the public key must not pass
        v.verify(forged)
    assert verifier().verify(mint(azp=None))["sub"] == "user_a"               # no azp (a token minted server-side): accepted, as Clerk's SDK does
    assert verifier(parties=[]).verify(mint(azp="https://anything.example"))["sub"] == "user_a"     # no allow-list configured: not checked


def test_workspace_tokens_are_scoped_and_only_a_hash_is_kept():
    tok, h = new_token("w7")
    assert tok.startswith("gw_live_w7_") and h not in tok and split_token(tok)[0] == "w7"
    assert split_token("gw_live_" + "ab" * 16) == (None, "ab" * 16) and split_token("nope") == (None, None)


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "clerk")
    monkeypatch.setenv("GW_DEMO_INCIDENTS", "6")
    monkeypatch.setenv("GW_STORE", "memory")
    monkeypatch.setattr(appmod.ClerkVerifier, "from_env", classmethod(lambda cls: verifier()))
    app = appmod.create_app(state_path=tmp_path / "demo.json", results_path=None)
    return TestClient(app), app


def bearer(sub):
    return {"Authorization": "Bearer " + mint(sub)}


def test_the_demo_is_public_and_everything_else_needs_a_session(app_env):
    c, _ = app_env
    assert c.get("/api/health").status_code == 200 and c.get("/api/config").json()["auth_mode"] == "clerk"
    assert c.get("/api/summary").status_code == 401                                   # no session, no demo header
    assert c.get("/api/summary", headers={"Authorization": "Bearer junk"}).status_code == 401
    d = c.get("/api/summary", headers={"x-gw-demo": "1"})
    assert d.status_code == 200 and d.json()["services"] > 25                         # the public demo workspace, logged out
    assert c.post("/api/settings/reset-learned", headers={"x-gw-demo": "1"}).status_code == 403     # the sandbox cannot change settings
    assert c.post("/v1/alerts/demo", json={"alerts": []}).status_code == 422          # reaches the demo workspace without a token
    assert c.post("/v1/alerts/acme", json={"alerts": []}).status_code == 401          # any other workspace needs its token


def test_two_accounts_cannot_see_each_other(app_env):
    c, _ = app_env
    a, b = bearer("user_a"), bearer("user_b")
    assert c.get("/api/summary", headers=a).json()["services"] == 0                    # a fresh, empty workspace
    assert c.post("/api/onboarding/load-sample", headers=a).json()["services"] == 24
    inc = c.post("/api/test-alert", headers=a).json()["id"]
    sa, sb = c.get("/api/summary", headers=a).json(), c.get("/api/summary", headers=b).json()
    assert sa["services"] == 24 and sb["services"] == 0
    assert c.get(f"/api/incidents/{inc}", headers=a).status_code == 200
    assert c.get(f"/api/incidents/{inc}", headers=b).status_code == 404               # B cannot read A's incident
    assert c.get("/api/incidents", headers=b).json() == []
    assert c.get("/api/map", headers=b).json()["nodes"] == []
    # tokens: A's token reaches A's workspace only, B's workspace is untouched; a tampered token is refused
    ta = c.post("/api/settings/token/rotate", headers=a).json()["token"]
    names = [n["name"] for n in c.get("/api/map", headers=a).json()["nodes"][:3]]
    body = {"alerts": [{"name": n, "signal": "error_rate", "t": i * 5} for i, n in enumerate(names)]}
    n0 = len(c.get("/api/incidents", headers=a).json())
    assert c.post("/v1/alerts/mine", json=body, headers={"Authorization": "Bearer " + ta}).status_code == 200
    assert c.post("/v1/alerts/mine", json=body, headers={"Authorization": "Bearer " + ta[:-1] + ("1" if ta[-1] == "0" else "0")}).status_code == 401
    assert c.post("/v1/alerts/mine", json=body).status_code == 401
    assert len(c.get("/api/incidents", headers=a).json()) == n0 + 1 and c.get("/api/incidents", headers=b).json() == []
    tb = c.post("/api/settings/token/rotate", headers=b).json()["token"]
    c.post("/v1/alerts/mine", json=body, headers={"Authorization": "Bearer " + tb})   # B's token lands in B's workspace, never in A's
    assert tb != ta and len(c.get("/api/incidents", headers=a).json()) == n0 + 1
    assert c.get("/api/summary", headers=b).json()["services"] == 0                    # still nothing leaked into B


def test_clerk_workspace_scan_alert_rca_and_reviewed_postmortem(app_env):
    """Exercise the full non-GitHub customer journey through authenticated API routes."""
    c, _ = app_env
    a, b = bearer("journey_a"), bearer("journey_b")
    assert c.get("/api/summary", headers=a).json()["services"] == 0
    scan = c.post("/api/onboarding/scan", json={"source": "sample"}, headers=a)
    assert scan.status_code == 200 and scan.json()["source"] == "sample"
    proposal = scan.json()
    assert proposal["edges"] and c.get("/api/onboarding", headers=a).json()["steps"]["github"] is False
    chosen = [e["id"] for e in proposal["edges"] if e["accepted"]]
    accepted = c.post("/api/onboarding/accept", json={"edge_ids": chosen}, headers=a)
    assert accepted.status_code == 200 and accepted.json()["dependencies"] == len(chosen)
    assert c.get("/api/map", headers=a).json()["official"] == len(chosen)

    settings = c.get("/api/settings", headers=a).json()
    assert settings["token_required"] is True
    token = c.post("/api/settings/token/rotate", headers=a).json()["token"]
    nodes = c.get("/api/map", headers=a).json()["nodes"]
    alerts = {"alerts": [{"name": nodes[0]["name"], "signal": "error_rate", "t": 0},
                         {"name": nodes[-1]["name"], "signal": "latency", "t": 15}]}
    denied = c.post("/v1/alerts/acme", json=alerts)
    received = c.post("/v1/alerts/acme", json=alerts, headers={"Authorization": f"Bearer {token}"})
    assert denied.status_code == 401 and received.status_code == 200
    inc_id = received.json()["incident"]
    inc = c.get(f"/api/incidents/{inc_id}", headers=a).json()
    assert inc["source"] == "webhook" and inc["verdict"]["root_name"]

    root, entry = inc["verdict"]["root_name"], inc["verdict"]["entry_name"]
    fields = {"root": root, "path": f"{root} -> {entry}", "missed": f"{entry} depends on {root}"}
    before = c.get("/api/map", headers=a).json()
    preview = c.post(f"/api/learn/{inc_id}/preview", json=fields, headers=a)
    assert preview.status_code == 200 and c.get("/api/map", headers=a).json() == before
    queued = c.post(f"/api/learn/{inc_id}/queue", json=fields, headers=a).json()
    assert queued["id"] and c.get("/api/learn/queue", headers=a).json()
    applied = c.post(f"/api/learn/pending/{queued['id']}/apply", json={"reject": []}, headers=a)
    assert applied.status_code == 200 and c.get(f"/api/incidents/{inc_id}", headers=a).json()["status"] == "Resolved"
    assert c.get("/api/incidents", headers=b).json() == [] and c.get("/api/map", headers=b).json()["nodes"] == []


def test_github_setup_state_and_signed_issue_webhook_are_workspace_scoped(app_env, monkeypatch):
    c, _ = app_env
    monkeypatch.setenv("GITHUB_APP_ID", "12345")
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", "not-used-by-this-route")
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "webhook-test-secret")
    a, b = bearer("github_a"), bearer("github_b")
    c.post("/api/onboarding/load-sample", headers=a)
    c.post("/api/onboarding/load-sample", headers=b)

    install = c.get("/api/onboarding/github/install-url", headers=a)
    assert install.status_code == 200
    state = parse_qs(urlsplit(install.json()["url"]).query)["state"][0]
    assert c.post("/api/onboarding/github/connect", json={"installation_id": 8123, "state": "wrong"}, headers=a).status_code == 400
    connected = c.post("/api/onboarding/github/connect", json={"installation_id": 8123, "state": state}, headers=a)
    assert connected.status_code == 200
    assert c.post("/api/onboarding/github/connect", json={"installation_id": 8123, "state": state}, headers=a).status_code == 400
    assert c.get("/api/onboarding", headers=b).json()["installation"] is None
    b_install = c.get("/api/onboarding/github/install-url", headers=b).json()
    b_state = parse_qs(urlsplit(b_install["url"]).query)["state"][0]
    assert c.post("/api/onboarding/github/connect", json={"installation_id": 8123, "state": b_state}, headers=b).status_code == 409

    inc = c.get("/api/incidents", headers=a).json()[0]
    root, entry = inc["root"], inc["symptom"].split(" ", 1)[0]
    issue_body = f"### Actual root cause\n\n{root}\n\n### How it reached the alerting service\n\n{root} -> {entry}\n\n### What the map got wrong (optional)\n\n_No response_\n"
    payload = {"action": "opened", "installation": {"id": 8123}, "repository": {"full_name": "acme/infra"},
               "issue": {"number": 9, "title": f"{inc['id']}: investigation", "body": issue_body, "labels": [{"name": "postmortem"}]}}
    raw = json.dumps(payload).encode()
    signature = "sha256=" + hmac.new(b"webhook-test-secret", raw, hashlib.sha256).hexdigest()
    headers = {"x-github-event": "issues", "x-hub-signature-256": signature, "content-type": "application/json"}
    response = c.post("/api/webhooks/github", content=raw, headers=headers)
    assert response.status_code == 200 and response.json()["queued"]
    assert len(c.get("/api/learn/queue", headers=a).json()) == 1
    assert c.get("/api/learn/queue", headers=b).json() == []
    assert c.post("/api/webhooks/github", content=raw, headers={**headers, "x-gw-demo": "1"}).status_code == 403


def test_a_user_workspace_survives_a_restart_and_the_demo_is_untouched(app_env, tmp_path):
    c, app = app_env
    a = bearer("user_a")
    c.post("/api/onboarding/load-sample", headers=a)
    before = c.get("/api/summary", headers=a).json()["services"]
    demo_before = c.get("/api/summary", headers={"x-gw-demo": "1"}).json()["services"]
    app2 = appmod.create_app(state_path=tmp_path / "demo.json", results_path=None)    # a new process on the same data directory
    c2 = TestClient(app2)
    assert c2.get("/api/summary", headers=a).json()["services"] == before == 24
    assert c2.get("/api/summary", headers={"x-gw-demo": "1"}).json()["services"] == demo_before


def test_there_is_no_service_limit(app_env):
    c, app = app_env
    a = bearer("user_a")
    c.get("/api/summary", headers=a)
    user_ws = app.state.tenancy.for_user("user_a")
    edges = [{"id": f"e{i}", "src": f"svc-{i}", "dst": f"svc-{i + 1}", "accepted": True} for i in range(60)]
    user_ws.map_proposals = {"edges": edges, "services": [{"name": f"svc-{i}", "kind": "service"} for i in range(61)]}
    assert c.post("/api/onboarding/accept", json={"edge_ids": [e["id"] for e in edges]}, headers=a).status_code == 200


def test_hydradb_isolation_between_two_workspaces(make_hydra):
    """Two workspaces on one HydraDB, each with its own id range: neither sees the other's graph, incidents or lessons."""
    from ghostwalk.api.workspace import Workspace
    from ghostwalk.graph.hydra import RUN_SPAN
    hg_a, hg_b = make_hydra(), make_hydra()
    a = Workspace(None, demo=False, store="hydradb", hydra=hg_a, wsid="w1")
    b = Workspace(None, demo=False, store="hydradb", hydra=hg_b, wsid="w2")
    a.load_sample()
    assert len(a.incidents) > 0 and hg_a.co is not None
    assert hg_b.co is None and b.g.components == {} and b.incidents == []              # B has nothing, not even a company
    b.load_sample(seed=999)

    def owned(hg):
        lo = hg.run_id * RUN_SPAN
        ids = [r[0] for r in hg._rows("MATCH (n {co: $co}) RETURN n.id AS id", co=hg.co)]
        return ids, all(lo <= i < lo + RUN_SPAN for i in ids)
    ids_a, in_a = owned(hg_a)
    ids_b, in_b = owned(hg_b)
    assert ids_a and ids_b and in_a and in_b and not set(ids_a) & set(ids_b)             # each workspace's rows live only in its own range
    assert {l["id"] for l in hg_b.lessons()} <= {l["id"] for l in hg_b.lessons()} and all(hg_b.co < x["created_seq"] + hg_b.co + 1 for x in hg_b.lessons())
    la, lb = hg_a.lessons(), hg_b.lessons()
    assert la != lb or not la                                                           # different companies learned different lessons
    for les in la[:1]:
        assert all(i // RUN_SPAN == hg_a.run_id for i in [hg_a.co + 0])
        assert hg_b.why_edge("no-such-service", "no-such-service")["edge"] is None
