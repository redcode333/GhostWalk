import base64, hashlib, hmac, json
import httpx
from ghostwalk.discover.parsers import classify, merge, summarize
from ghostwalk.discover.scan import scan_texts, proposals
from ghostwalk.integrations import github as gh, issues

COMPOSE = """
services:
  checkout-api:
    image: acme/checkout
    depends_on: [payments, cart]
    environment:
      CONFIG_SVC_URL: http://config-svc:8080
  payments:
    image: acme/payments
    depends_on:
      postgres-pay: {condition: service_healthy}
    environment:
      - DATABASE_URL=postgres://postgres-pay:5432/pay
      - STRIPE_URL=https://api.stripe.com/v1
  cart:
    image: acme/cart
  postgres-pay:
    image: postgres:16
  config-svc:
    image: acme/config
"""
K8S = """
apiVersion: v1
kind: Service
metadata: {name: checkout-api}
---
apiVersion: v1
kind: Service
metadata: {name: payments}
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata: {name: web-edge}
spec:
  rules:
    - http:
        paths:
          - path: /
            backend: {service: {name: checkout-api, port: {number: 80}}}
---
apiVersion: apps/v1
kind: Deployment
metadata: {name: fraud-check}
spec:
  template:
    spec:
      containers:
        - name: app
          env:
            - {name: PAYMENTS_URL, value: "http://payments.prod.svc.cluster.local:8080"}
"""
HELM = """
search:
  redisHost: redis-main
redis-main:
  image: redis
"""
ENV = "CONFIG_SVC_URL=http://config-svc:8080\nLOG_LEVEL=info\n"
FILES = [("acme/checkout", "docker-compose.yml", COMPOSE), ("acme/infra", "k8s/web.yaml", K8S),
         ("acme/infra", "charts/app/values.yaml", HELM), ("acme/payments", ".env", ENV), ("acme/payments", "README.md", "x")]


def edges():
    return {(e.src, e.dst): e for e in merge(scan_texts(FILES))}


def test_classify():
    assert classify("docker-compose.yml") == "compose" and classify("deploy/docker-compose.prod.yaml") == "compose"
    assert classify("k8s/web.yaml") == "k8s" and classify("charts/app/values.yaml") == "helm"
    assert classify(".env") == "env" and classify("README.md") is None and classify("src/app.yaml") is None


def test_compose_depends_on_is_high_with_source():
    e = edges()[("checkout-api", "payments")]
    assert (e.confidence, e.file, e.repo, e.evidence) == ("high", "docker-compose.yml", "acme/checkout", "compose depends_on")
    assert edges()[("payments", "postgres-pay")].confidence == "high"      # dict-form depends_on


def test_env_urls_and_external_hosts():
    es = edges()
    assert es[("checkout-api", "config-svc")].confidence in ("medium", "high")
    assert ("payments", "api") not in es and not any(d.startswith("api.stripe") for _, d in es)   # external FQDN ignored
    assert es[("payments", "postgres-pay")].confidence == "high"          # datastore scheme to a known service


def test_k8s_ingress_and_deployment_env():
    es = edges()
    assert es[("web-edge", "checkout-api")].evidence == "k8s Ingress" and es[("web-edge", "checkout-api")].confidence == "high"
    assert es[("fraud-check", "payments")].file == "k8s/web.yaml"


def test_helm_values_is_low_and_off_by_default():
    e = edges()[("search", "redis-main")]
    assert e.confidence == "low" and e.evidence.startswith("Helm values")
    out = proposals(scan_texts(FILES))
    assert next(x for x in out["edges"] if x["id"] == "search>redis-main")["accepted"] is False
    assert next(x for x in out["edges"] if x["id"] == "checkout-api>payments")["accepted"] is True


def test_duplicate_evidence_keeps_the_strongest_and_all_sources():
    es = edges()
    e = es[("checkout-api", "config-svc")]
    assert len(e.sources) >= 1
    s = summarize(scan_texts(FILES))
    assert s["dependencies"] == len(es) and set(s["by_source"]) >= {"docker-compose", "k8s manifests", "Helm values"}


def test_kinds():
    f = scan_texts(FILES)
    assert f.services["postgres-pay"]["kind"] == "data" and f.services["web-edge"]["kind"] == "edge"
    assert f.services["config-svc"]["kind"] == "infra" and f.services["payments"]["kind"] == "service"


# ---- issue forms -------------------------------------------------------------------------------
BODY = """### Actual root cause

config-svc

### How it reached the alerting service

config-svc -> fraud-check -> payments -> checkout-api

### What the map got wrong (optional)

fraud-check reads feature flags from config-svc on every request. "cfg" is config-svc.
"""
NAMES = {"config-svc": 1, "fraud-check": 2, "payments": 3, "checkout-api": 4}


def test_issue_form_parses_three_fields():
    f = issues.parse_issue_form(BODY)
    assert f["root"] == "config-svc" and f["path"].startswith("config-svc ->") and "feature flags" in f["missed"]
    assert issues.parse_issue_form("### Actual root cause\n\n_No response_\n")["root"] == ""


def test_postmortem_chain_orientation_and_aliases():
    pm = issues.to_postmortem(issues.parse_issue_form(BODY), NAMES)
    assert pm["root"] == 1
    assert pm["chain"][:3] == [[2, 1], [3, 2], [4, 3]]          # [dependent, dependency], root first
    assert [2, 1] in pm["chain"] and ["cfg", 1] in pm["aliases"]


def test_unknown_names_are_reported_and_typos_matched():
    pm = issues.to_postmortem({"root": "config-svc", "path": "config-svc -> fraud-chek -> mystery", "missed": ""}, NAMES)
    assert pm["unresolved"] == ["mystery"] and [2, 1] in pm["chain"]


def test_event_filter_and_incident_ref():
    ev = lambda action, label: {"action": action, "label": {"name": label}, "issue": {"labels": [{"name": label}]}}
    assert issues.is_postmortem_event(ev("labeled", "postmortem")) and not issues.is_postmortem_event(ev("labeled", "bug"))
    assert not issues.is_postmortem_event(ev("closed", "postmortem"))
    assert issues.incident_ref("inc-1042: config", "") == "INC-1042" and issues.incident_ref("x", "see INC-7") == "INC-7"


def test_webhook_signature_fails_closed():
    body = b'{"a":1}'
    sig = "sha256=" + hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
    assert gh.verify_signature("s3cret", body, sig)
    assert not gh.verify_signature("s3cret", body, "sha256=00") and not gh.verify_signature("", body, sig)
    assert not gh.verify_signature("s3cret", body, None)


# ---- GitHub client (mock transport) ------------------------------------------------------------
def test_github_scan_reads_only_infra_files_with_get_requests():
    seen = []

    def handler(req: httpx.Request):
        seen.append((req.method, req.url.path))
        p = req.url.path
        if p == "/installation/repositories":
            return httpx.Response(200, json={"repositories": [{"full_name": "acme/checkout"}]})
        if p.endswith("/git/trees/HEAD"):
            return httpx.Response(200, json={"tree": [{"path": "docker-compose.yml", "type": "blob", "size": 100},
                                                      {"path": "src/main.py", "type": "blob", "size": 10}]})
        if p.endswith("/contents/docker-compose.yml"):
            return httpx.Response(200, json={"encoding": "base64", "content": base64.b64encode(COMPOSE.encode()).decode()})
        return httpx.Response(404)

    client = gh.GitHub("tok", httpx.MockTransport(handler))
    files = client.scan()
    assert [f[1] for f in files] == ["docker-compose.yml"]
    assert all(m == "GET" for m, _ in seen)                       # the read-only App never writes
    assert ("checkout-api", "payments") in {e.key() for e in merge(scan_texts(files))}


def test_template_pr_flow_and_fallback():
    calls = []

    def handler(req: httpx.Request):
        calls.append((req.method, req.url.path))
        p = req.url.path
        if req.method == "GET" and p == "/repos/acme/infra":
            return httpx.Response(200, json={"default_branch": "main"})
        if req.method == "GET" and p.endswith("/git/ref/heads/main"):
            return httpx.Response(200, json={"object": {"sha": "abc"}})
        if req.method == "POST" and p.endswith("/git/refs"):
            return httpx.Response(201, json={})
        if req.method == "GET" and "contents" in p:
            return httpx.Response(404)
        if req.method == "PUT":
            assert json.loads(req.content)["branch"] == "ghostwalk/postmortem-template"
            return httpx.Response(201, json={})
        if req.method == "POST" and p.endswith("/pulls"):
            return httpx.Response(201, json={"html_url": "https://github.com/acme/infra/pull/9"})
        return httpx.Response(500)

    url = gh.GitHub("write-token", httpx.MockTransport(handler)).open_template_pr("acme/infra")
    assert url.endswith("/pull/9") and ("PUT", "/repos/acme/infra/contents/.github/ISSUE_TEMPLATE/postmortem.yml") in calls
    fb = gh.template_fallback("acme/infra")
    assert fb["url"].startswith("https://github.com/acme/infra/new/main?filename=") and "postmortem" in fb["content"]
    import yaml
    t = yaml.safe_load(gh.POSTMORTEM_TEMPLATE)
    assert t["labels"] == ["postmortem"] and [b["attributes"]["label"] for b in t["body"]] == list(issues.FIELDS.values())
