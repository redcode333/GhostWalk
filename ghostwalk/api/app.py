"""GhostWalk HTTP API (FastAPI). `uvicorn ghostwalk.api.app:app`.

AUTH_MODE=none (default)  no sign-in; opens the demo workspace.
AUTH_MODE=clerk           /api/* needs a Clerk session JWT (CLERK_JWKS_URL, CLERK_ISSUER); webhooks use their own secrets.
"""
from __future__ import annotations
import json, os, pathlib, secrets
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .alerts import normalize
from .samples import SAMPLE_FILES
from .workspace import Workspace
from .demo import demo_inside
from .. import mcp_tools
from ..discover.scan import scan_texts, proposals
from ..integrations import github as gh, issues

ROOT = pathlib.Path(__file__).resolve().parents[2]
AUTH_MODE = lambda: os.environ.get("AUTH_MODE", "none")
FREE_SERVICES = 25


def clerk_user(request: Request):
    if AUTH_MODE() != "clerk":
        return {"id": "demo"}
    import jwt
    tok = (request.headers.get("authorization") or "").removeprefix("Bearer ").strip()
    if not tok:
        raise HTTPException(401, "sign in required")
    try:
        key = jwt.PyJWKClient(os.environ["CLERK_JWKS_URL"]).get_signing_key_from_jwt(tok)
        return jwt.decode(tok, key.key, algorithms=["RS256"], issuer=os.environ.get("CLERK_ISSUER"), options={"verify_aud": False})
    except Exception as e:
        raise HTTPException(401, f"invalid session: {e}")


def create_app(state_path=None, results_path=None, workspace: Workspace | None = None):
    app = FastAPI(title="GhostWalk", docs_url="/api/docs", openapi_url="/api/openapi.json")
    ws = workspace or Workspace(state_path if state_path is not None else os.environ.get("GW_STATE", str(ROOT / "var" / "state.json")))
    results_file = pathlib.Path(results_path or os.environ.get("GW_RESULTS", ROOT / "results.json"))
    app.state.ws = ws
    user = Depends(clerk_user)

    def public_url(request: Request):
        return os.environ.get("GW_PUBLIC_URL") or str(request.base_url).rstrip("/")

    def incident_or_404(inc_id):
        inc = ws.get(inc_id)
        if inc is None:
            raise HTTPException(404, f"no incident {inc_id}")
        return inc

    # ---- public ---------------------------------------------------------------------------
    @app.get("/api/health")
    def health():
        return {"ok": True, "services": len(ws.g.components)}

    @app.get("/api/config")
    def config():
        c = gh.env_config()
        return {"auth_mode": AUTH_MODE(), "clerk_publishable_key": os.environ.get("CLERK_PUBLISHABLE_KEY"),
                "github": {"configured": bool(c["app_id"] and c["private_key"]), "slug": c["slug"], "pr_token": bool(c["pr_token"])}}

    @app.get("/api/proof")
    def proof():
        if not results_file.exists():
            raise HTTPException(404, "results.json not found: run `make eval`")
        return JSONResponse(json.loads(results_file.read_text(encoding="utf8")), headers={"Cache-Control": "no-cache"})

    @app.get("/results.json")
    def results_download():
        if not results_file.exists():
            raise HTTPException(404, "results.json not found")
        return FileResponse(results_file, media_type="application/json", filename="results.json")

    @app.get("/api/demo/inside")
    def inside():
        return demo_inside()

    # ---- hosted MCP (the same four tools over HTTP; `gw mcp` with GW_URL + GW_TOKEN proxies here) --------------------------
    def check_mcp_token(request: Request):
        got = (request.headers.get("authorization") or "").removeprefix("Bearer ").strip()
        if not got or not secrets.compare_digest(got, ws.token):
            raise HTTPException(401, "bad or missing GW_TOKEN")

    @app.post("/api/mcp/{tool}")
    async def mcp_call(tool: str, request: Request):
        check_mcp_token(request)
        args = await request.json()
        fn = {"why": mcp_tools.why, "path": mcp_tools.path, "blast_radius": mcp_tools.blast_radius, "propose_edge": mcp_tools.propose_edge}.get(tool)
        if fn is None:
            raise HTTPException(404, f"no tool {tool}")
        try:
            return fn(ws, **args)
        except (mcp_tools.ToolError, TypeError, ValueError) as e:
            raise HTTPException(422, str(e))

    # ---- alert webhook (own token, not Clerk) -----------------------------------------------
    def check_token(request: Request):
        need = os.environ.get("GW_REQUIRE_TOKEN", "1" if AUTH_MODE() == "clerk" else "0") == "1"
        if not need:
            return
        got = (request.headers.get("authorization") or "").removeprefix("Bearer ").strip() or request.headers.get("x-gw-token") \
            or request.query_params.get("token")
        if not got or not secrets.compare_digest(got, ws.token):
            raise HTTPException(401, "bad or missing token")

    @app.post("/v1/alerts/{workspace_name}")
    async def alerts_webhook(workspace_name: str, request: Request):
        check_token(request)
        try:
            payload = await request.json()
            alerts = normalize(payload)
        except (ValueError, json.JSONDecodeError) as e:
            raise HTTPException(422, str(e))
        inc = ws.ingest_alerts(alerts)
        return {"incident": inc["id"], "root": inc["verdict"]["root_name"], "confidence": inc["verdict"]["confidence"], "ms": inc["verdict"]["ms"]}

    # ---- app ------------------------------------------------------------------------------
    @app.get("/api/summary")
    def summary(u=user):
        return ws.summary()

    @app.get("/api/incidents")
    def incidents(status: str | None = None, u=user):
        rows = [i for i in ws.incidents if not status or status == "All" or i["status"] == status]
        return [{"id": i["id"], "symptom": i["symptom"], "root": i["verdict"]["root_name"], "confidence": i["verdict"]["confidence"],
                 "status": i["status"], "started": i["started"], "alerts": len(i["alerts"]), "source": i["source"],
                 "taught": i.get("learned_changes", 0), "ms": i["verdict"]["ms"]} for i in reversed(rows)]

    @app.get("/api/incidents/{inc_id}")
    def incident(inc_id: str, u=user):
        return incident_or_404(inc_id)

    @app.post("/api/incidents/trigger")
    def trigger(u=user):
        inc = ws.trigger_outage()
        return {"id": inc["id"]}

    @app.post("/api/test-alert")
    def test_alert(u=user):
        inc = ws.test_alert()
        return {"id": inc["id"], "root": inc["verdict"]["root_name"], "ms": inc["verdict"]["ms"], "planted_root": inc.get("test_root")}

    @app.get("/api/map")
    def graph(u=user):
        return ws.graph_view()

    @app.get("/api/map/export")
    def export(u=user):
        v = ws.graph_view()
        return JSONResponse(v, headers={"Content-Disposition": "attachment; filename=ghostwalk-graph.json"})

    # ---- learn ----------------------------------------------------------------------------
    @app.get("/api/learn/queue")
    def queue(u=user):
        return [{k: p[k] for k in ("id", "incident", "ref", "source", "created", "shown", "unresolved", "root_name")} for p in ws.pending]

    @app.post("/api/learn/{inc_id}/preview")
    async def preview(inc_id: str, request: Request, u=user):
        inc = incident_or_404(inc_id)
        pm = ws.make_pm(await request.json())
        if pm["root"] is None:
            raise HTTPException(422, "root cause not found in the map. Try one of its names or aliases.")
        p = ws.preview(inc, pm)
        return {"shown": p["shown"], "unresolved": p["unresolved"], "root_name": p["root_name"]}

    @app.post("/api/learn/{inc_id}/queue")
    async def queue_draft(inc_id: str, request: Request, u=user):
        inc = incident_or_404(inc_id)
        pm = ws.make_pm(await request.json())
        if pm["root"] is None:
            raise HTTPException(422, "root cause not found in the map")
        item = ws.queue(inc, pm, "web form")
        return {"id": item["id"], "shown": item["shown"]}

    @app.post("/api/learn/pending/{pid}/apply")
    async def apply_pending(pid: str, request: Request, u=user):
        body = await request.json() if (await request.body()) else {}
        try:
            return ws.apply_pending(pid, body.get("reject", []))
        except KeyError:
            raise HTTPException(404, "no such proposal")

    @app.delete("/api/learn/pending/{pid}")
    def discard(pid: str, u=user):
        before = len(ws.pending)
        ws.pending[:] = [p for p in ws.pending if p["id"] != pid]
        ws.save()
        if len(ws.pending) == before:
            raise HTTPException(404, "no such proposal")
        return {"ok": True}

    # ---- settings -------------------------------------------------------------------------
    @app.get("/api/settings")
    def settings(request: Request, u=user):
        s = ws.summary()
        return {"webhook_url": f"{public_url(request)}/v1/alerts/acme", "token_masked": ws.token[:8] + "•" * 12 + ws.token[-4:],
                "receiving": bool(ws.onboarding["first_alert_at"]), "store": s["store"],
                "graph": {"nodes": s["services"], "edges": s["official_edges"] + s["learned_edges"], "learned": s["learned_edges"]},
                "version": "0.1.0", "auth_mode": AUTH_MODE()}

    @app.post("/api/settings/token/reveal")
    def reveal(u=user):
        return {"token": ws.token}

    @app.post("/api/settings/token/rotate")
    def rotate(u=user):
        ws.token = "gw_live_" + secrets.token_hex(16)
        ws.save()
        return {"token": ws.token}

    @app.post("/api/settings/reset-learned")
    def reset(u=user):
        ws.reset_learned()
        return {"ok": True}

    # ---- onboarding -----------------------------------------------------------------------
    @app.get("/api/onboarding")
    def onboarding(u=user):
        return {"steps": ws.onboarding, "proposals": ws.map_proposals, "installation": ws.installation,
                "repo": ws.repo_for_template, "summary": ws.summary()}

    @app.get("/api/onboarding/github/install-url")
    def install_url(u=user):
        c = gh.env_config()
        if not c["app_id"]:
            raise HTTPException(501, "GitHub App is not configured on this server (GITHUB_APP_ID / GITHUB_APP_PRIVATE_KEY)")
        return {"url": f"https://github.com/apps/{c['slug']}/installations/new"}

    @app.post("/api/onboarding/github/connect")
    async def connect(request: Request, u=user):
        body = await request.json()
        ws.installation = {"id": int(body["installation_id"])}
        ws.onboarding["github"] = True
        ws.save()
        return {"ok": True}

    @app.post("/api/onboarding/scan")
    async def scan(request: Request, u=user):
        body = await request.json() if (await request.body()) else {}
        source = body.get("source", "sample")
        if source == "github":
            c = gh.env_config()
            if not (c["app_id"] and c["private_key"] and ws.installation):
                raise HTTPException(400, "connect the GitHub App first (or scan the sample repos)")
            try:
                client = gh.GitHub.from_app(c["app_id"], c["private_key"], ws.installation["id"])
                files = client.scan(body.get("repos"))
            except gh.GitHubError as e:
                raise HTTPException(502, str(e))
        else:
            files = SAMPLE_FILES
            ws.onboarding["github"] = True
        out = proposals(scan_texts(files))
        out["source"] = source
        ws.set_proposals(out)
        if out["edges"]:
            ws.repo_for_template = body.get("template_repo") or (out["summary"]["repos"][-1] if out["summary"]["repos"] else None)
        return out

    @app.post("/api/onboarding/accept")
    async def accept(request: Request, u=user):
        body = await request.json()
        if AUTH_MODE() == "clerk" and ws.map_proposals:
            ids = set(body.get("edge_ids", []))
            names = {n for e in ws.map_proposals["edges"] if e["id"] in ids for n in (e["src"], e["dst"])}
            if len(names) > FREE_SERVICES:
                raise HTTPException(402, {"code": "plan_limit", "plan": "free", "limit": FREE_SERVICES, "services": len(names),
                                          "message": f"The free plan covers {FREE_SERVICES} services; this map has {len(names)}."})
        try:
            return ws.accept_map(body.get("edge_ids", []))
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.post("/api/onboarding/postmortem-pr")
    async def postmortem_pr(request: Request, u=user):
        body = await request.json() if (await request.body()) else {}
        repo = body.get("repo") or ws.repo_for_template
        if not repo or "/" not in repo:
            raise HTTPException(422, "which repo? e.g. acme/infra")
        token = gh.env_config()["pr_token"]
        if token:
            try:
                return {"mode": "pr", "url": gh.GitHub(token).open_template_pr(repo)}
            except gh.GitHubError as e:
                raise HTTPException(502, str(e))
        return {"mode": "link", **gh.template_fallback(repo),
                "why": "The GitHub App is read-only, so it can't open a pull request. Use this link (GitHub offers to open the PR), "
                       "or set GITHUB_PR_TOKEN to a token you control with contents + pull-request write access."}

    @app.post("/api/webhooks/github")
    async def github_webhook(request: Request):
        raw = await request.body()
        if not gh.verify_signature(gh.env_config()["webhook_secret"], raw, request.headers.get("x-hub-signature-256")):
            raise HTTPException(401, "bad signature")
        event = request.headers.get("x-github-event")
        if event == "ping":
            return {"ok": True}
        payload = json.loads(raw)
        if event != "issues" or not issues.is_postmortem_event(payload):
            return {"ignored": True}
        issue = payload["issue"]
        fields = issues.parse_issue_form(issue.get("body") or "")
        if not fields["root"]:
            return {"ignored": True, "reason": "root cause field is empty"}
        pm = ws.make_pm(fields)
        if pm["root"] is None:
            return {"ignored": True, "reason": f"root cause {fields['root']!r} is not in the map"}
        ref = issues.incident_ref(issue.get("title", ""), issue.get("body", ""))
        inc = ws.get(ref) if ref else None
        if inc is None:
            inc = next((i for i in reversed(ws.incidents) if i["status"] != "Resolved"), None)
        repo = (payload.get("repository") or {}).get("full_name")
        issue_ref = f"{repo}#{issue.get('number')}"
        ws.pending[:] = [p for p in ws.pending if p.get("ref") != issue_ref]          # an edited issue replaces its old proposal
        item = ws.queue(inc, pm, f"GitHub issue {issue_ref}", ref=issue_ref)
        return {"queued": item["id"], "changes": len(item["shown"]), "incident": item["incident"]}

    # ---- the built web app ----------------------------------------------------------------
    dist = ROOT / "web" / "dist"
    if dist.exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}")
        def spa(path: str):
            f = dist / path
            return FileResponse(f if path and f.is_file() else dist / "index.html")
    return app


app = create_app() if os.environ.get("GW_AUTOSTART", "1") == "1" else None
