"""gw: the GhostWalk CLI (typer + rich). Output follows the spec: muted labels, violet for root and learned edges, teal check marks,
20-wide confidence bars, tier-coloured dots, and an "apply N changes? [Y/n]" prompt for learn.

    gw map import [PATH | --from github --repo owner/name]
    gw why --alerts alerts.json | --incident INC-1042
    gw learn INC-1042 --root config-svc [--path 'config-svc -> fraud-check -> checkout-api']
    gw eval --split dev|test [--run]
    gw mcp                            MCP server on stdio (Claude Code, Cursor, ...)
    gw demo                           a demo workspace + the next outage as alerts.json, to try the above
"""
from __future__ import annotations
import json, os, pathlib, subprocess, sys
from typing import List, Optional
import typer
from rich.console import Console
from rich.text import Text

from .api.workspace import Workspace
from .discover.scan import repo_folders, scan_directory, scan_texts, proposals

VIOLET, VIOLET_TEXT, TEAL, AMBER, RED, DIM, INK, MUTED_BAR, EMPTY = "#8E76FF", "#AC9BFF", "#12B5A0", "#F5B83F", "#D9534F", "#8F8E9A", "#F6F5F1", "#4A4955", "#3A3A44"
TIER = {"edge": "#3D7DFF", "service": "#12B5A0", "data": "#E2549A", "infra": "#7FB800"}
BAR = 20
console = Console(highlight=False, soft_wrap=False)

app = typer.Typer(help="GhostWalk: why is it broken, and what should the map have said?", add_completion=False, no_args_is_help=True,
                  context_settings={"help_option_names": ["-h", "--help"]})
map_app = typer.Typer(help="The dependency map.", no_args_is_help=True)
app.add_typer(map_app, name="map")
main = app


def fail(msg: str):
    console.print(Text("  " + msg, style=RED))
    raise typer.Exit(1)


def bar(value, color, width=BAR, pad=True):
    n = max(0, min(width, round(value * width)))
    t = Text()
    t.append("█" * n, style=color)
    if pad:
        t.append("░" * (width - n), style=EMPTY)
    return t


def line(*parts):
    t = Text("  ")
    for p in parts:
        t.append(*p) if isinstance(p, tuple) else t.append(p)
    console.print(t)


def prompt_line(cmd):
    t = Text()
    t.append("$ ", style=VIOLET_TEXT)
    t.append(cmd, style=INK)
    console.print(t)
    console.print()


def ok(msg):
    t = Text("  ")
    t.append("ok ", style=TEAL)
    t.append(msg)
    console.print(t)


def state_path():
    return pathlib.Path(os.environ.get("GW_HOME", ".gw")) / "state.json"


def workspace(create=False) -> Workspace:
    p = state_path()
    if os.environ.get("GW_STORE") == "hydradb":          # the map lives in HydraDB: no local state file needed
        return Workspace(p if p.exists() else None, demo=False)
    if not p.exists() and not create:
        fail("no map yet. Run `gw map import ./your-repos` (or `gw demo` to try it).")
    return Workspace(p, demo=False)


# ---- map --------------------------------------------------------------------------------------
@map_app.command("import")
def map_import(path: Optional[pathlib.Path] = typer.Argument(None, exists=True, file_okay=False, help="folder of repos (each subfolder is a repo)"),
               from_: Optional[str] = typer.Option(None, "--from", help="'github' reads repos through a token (GITHUB_TOKEN, read-only is enough)"),
               repo: List[str] = typer.Option([], "--repo", help="owner/name, repeatable (with --from github)"),
               take_all: bool = typer.Option(False, "--all", help="also accept low-confidence edges")):
    """Scan compose, k8s, Helm and *_URL evidence and save the proposed map."""
    if from_ == "github":
        from .integrations.github import GitHub, GitHubError
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            fail("set GITHUB_TOKEN (read access to contents is enough)")
        prompt_line("gw map import --from github " + " ".join(f"--repo {r}" for r in repo))
        line((f"scanning {len(repo) or 'your'} repo{'s' if len(repo) != 1 else ''} …", DIM))
        try:
            found = scan_texts(GitHub(token).scan(repo or None))
        except GitHubError as e:
            fail(str(e))
    elif path is not None:
        repos = repo_folders(path) or [path]
        prompt_line(f"gw map import {path}")
        line((f"scanning {len(repos)} repo{'s' if len(repos) != 1 else ''} …", DIM))
        found = scan_directory(path)
    else:
        fail("give a PATH, or --from github --repo owner/name")
    console.print()
    out = proposals(found)
    s = out["summary"]
    names = {"docker-compose": "docker-compose.yml", "k8s manifests": "k8s/*.yaml", "Helm values": "Helm values", "env vars": "env vars  *_URL"}
    for label, shown in names.items():
        if s["by_source"].get(label):
            line(f"{shown:<26}{s['by_source'][label]:>3} edges")
    console.print()
    ws = workspace(create=True)
    ids = [e["id"] for e in out["edges"] if take_all or e["accepted"]]
    ws.set_proposals(out)
    r = ws.accept_map(ids)
    ok(f"{r['services']} services · {r['dependencies']} dependencies")
    console.print()
    legend = Text("    ")
    for k in ("edge", "service", "data", "infra"):
        legend.append("●", style=TIER[k]).append(f" {k} {s['by_kind'].get(k, 0)}   ")
    console.print(legend)
    skipped = len(out["edges"]) - len(ids)
    if skipped:
        line((f"{skipped} low-confidence edge{'s' if skipped != 1 else ''} left out (use --all to include)", DIM))


@app.command("demo")
def demo(alerts_out: str = typer.Option("alerts.json", "--alerts", help="where to write the next outage")):
    """Create the simulated acme-demo workspace and write the next outage to alerts.json."""
    ws = Workspace(state_path(), demo=True)
    nxt = ws.company["incidents"][ws.next_sim]["alerts"]
    pathlib.Path(alerts_out).write_text(json.dumps({"alerts": nxt}, indent=1))
    ws.save()
    line((f"acme-demo · {len(ws.g.components)} services · {len(ws.incidents)} past incidents", DIM))
    line((f"wrote {alerts_out} ({len(nxt)} alerts). Now: gw why --alerts {alerts_out}", DIM))


# ---- why --------------------------------------------------------------------------------------
def render_verdict(inc, top=3):
    v = inc["verdict"]
    line((f"{len(inc['alerts'])} alerts · {v['services']} services · walked {v['edges_walked']} edges in {v['ms']:.0f} ms", DIM))
    console.print()
    line(("rank  service            confidence", DIM))
    for i, r in enumerate(v["ranking"][:top], 1):
        t = Text(f"  {i}     ")
        t.append(f"{r['name']:<18}", style=VIOLET_TEXT if i == 1 else None)
        t.append_text(bar(r["confidence"], VIOLET if i == 1 else MUTED_BAR))
        t.append(f"  {r['confidence']:.2f}", style=INK if i == 1 else None)
        console.print(t)
    console.print()
    if v["path"]:
        t = Text("  ")
        t.append("path  ", style=DIM)
        t.append(v["path"][0]["u_name"])
        for hop in v["path"]:
            learned = hop["origin"] == "learned"
            t.append(" ⇢ " if learned else " → ", style=VIOLET_TEXT if learned else None)
            t.append(hop["v_name"])
        console.print(t)
        for l in v["learned_on_path"]:
            n = l["confirmations"]
            src = f"learned from {l['incident']}" if l.get("incident") else "learned"
            line(("        ",), (f"⇢ {src}, confirmed {'twice' if n == 2 else str(n) + '×' if n > 2 else 'once'}", VIOLET_TEXT))
        console.print()
    onset = sorted((b for b in v["blast"] if b["alerting"]), key=lambda b: b["onset"] or 0)
    t = Text("  ")
    t.append("why   ", style=DIM)
    t.append(f"explains {v['explains']} of {v['of']} alerts")
    if v["path"]:
        names = [v["path"][0]["u_name"]] + [h["v_name"] for h in v["path"]]
        alerted = [b["name"] for b in onset if b["name"] in names]
        if len(alerted) > 1 and alerted == [n for n in reversed(names) if n in alerted]:
            t.append(" · fired in path order")
    console.print(t)
    if v.get("change_note"):
        line(("      ",), (v["change_note"], VIOLET_TEXT))


@app.command("why")
def why(alerts_file: Optional[pathlib.Path] = typer.Option(None, "--alerts", exists=True, dir_okay=False, help="alerts json (Alertmanager, Grafana or {alerts:[{name,signal,t}]})"),
        incident: Optional[str] = typer.Option(None, "--incident", help="re-read a saved verdict, e.g. INC-1042"),
        top: int = typer.Option(3, help="how many candidates to show"),
        use_changes: bool = typer.Option(False, "--use-changes", help="weigh what changed shortly before the first alert")):
    """Rank the likely root causes of an alert storm and show the path."""
    ws = workspace()
    ws.use_changes = use_changes or ws.use_changes
    if incident:
        prompt_line(f"gw why --incident {incident}")
        inc = ws.get(incident)
        if inc is None:
            fail(f"no incident {incident}")
    elif alerts_file:
        from .api.alerts import normalize
        try:
            alerts = normalize(json.loads(alerts_file.read_text(encoding="utf8")))
        except ValueError as e:
            fail(str(e))
        prompt_line(f"gw why --alerts {alerts_file}")
        inc = ws.ingest_alerts(alerts, source="cli")
    else:
        fail("give --alerts FILE or --incident ID")
    v = inc["verdict"]
    if v["root"] is None:
        fail("none of the alerting names match services in the map. " + (f"Unknown: {', '.join(v['unresolved'][:5])}" if v["unresolved"] else ""))
    render_verdict(inc, top)
    line((f"{inc['id']} saved. Teach it: gw learn {inc['id']} --root {v['root_name']}", DIM))


@app.command("doctor")
def doctor(url: Optional[str] = typer.Option(None, "--url", help="the GhostWalk API (default: GW_URL, else http://127.0.0.1:8000)")):
    """Check the stack: the API, the store it uses, HydraDB, the learning queue and the stored results."""
    import httpx
    url = (url or os.environ.get("GW_URL") or "http://127.0.0.1:8000").rstrip("/")
    prompt_line("gw doctor")
    bad = []

    def check(label, fn):
        try:
            detail = fn()
            t = Text("  ")
            t.append("ok ", style=TEAL)
            t.append(f"{label:<22}")
            t.append(str(detail or ""), style=DIM)
            console.print(t)
            return True
        except Exception as e:                        # noqa: BLE001  (a doctor reports everything)
            t = Text("  ")
            t.append("x  ", style=RED)
            t.append(f"{label:<22}")
            t.append(str(e)[:120], style=RED)
            console.print(t)
            bad.append(label)
            return False

    token = os.environ.get("GW_TOKEN")                        # a workspace token checks that workspace; without one the public demo workspace is checked
    hdr = {"authorization": f"Bearer {token}"} if token else {"x-gw-demo": "1"}

    def get(path):
        r = httpx.get(url + path, headers=hdr, timeout=15)
        r.raise_for_status()
        return r.json()
    check("api", lambda: f"{url} " + str(get("/api/health")))
    holder = {}

    def summary():
        holder["s"] = get("/api/summary")
        s = holder["s"]
        return f"{s['services']} services, {s['learned_edges']} learned edges, revision {s['revision']}"
    check("workspace", summary)
    check("store", lambda: holder["s"]["store"]["label"] + (" (hydradb)" if holder["s"]["store"]["name"] == "hydradb" else ""))
    check("learning queue", lambda: "saving " + str(holder["s"].get("saving", 0)) if holder["s"].get("saving", 0) == 0 else (_ for _ in ()).throw(RuntimeError(f"{holder['s']['saving']} write(s) still saving")))
    if holder.get("s", {}).get("store", {}).get("name") == "hydradb":
        ready = os.environ.get("HYDRA_READY", "http://127.0.0.1:9090/readyz")
        check("hydradb", lambda: f"ready ({ready})" if httpx.get(ready, timeout=5).status_code == 200 else (_ for _ in ()).throw(RuntimeError("not ready: " + ready)))
    check("results.json", lambda: f"{get('/api/proof')['meta']['companies']} held-out companies")
    console.print()
    if bad:
        fail(f"{len(bad)} check(s) failed: {', '.join(bad)}")
    ok("all checks passed")


@app.command("why-edge")
def why_edge_cmd(src: str = typer.Argument(..., help="the service that depends on another, e.g. config-svc"),
                 dst: str = typer.Argument(..., help="what it depends on, e.g. fraud-check")):
    """Why does the map say SRC depends on DST: the lesson, the postmortems that taught it, the incidents that confirmed it (HydraDB store)."""
    from . import mcp_tools
    url, token = os.environ.get("GW_URL"), os.environ.get("GW_TOKEN")
    prompt_line(f"gw why-edge {src} {dst}")
    if url:
        import httpx
        r = httpx.get(f"{url.rstrip('/')}/v1/edges/{src}/{dst}/why", headers=({"authorization": f"Bearer {token}"} if token else {}), timeout=30)
        if r.status_code >= 400:
            fail(r.json().get("detail", r.text))
        res = r.json()
    else:
        ws = workspace()
        try:
            res = mcp_tools.why_edge(ws, src, dst)
        except mcp_tools.ToolError as e:
            fail(str(e))
    e = res["edge"]
    line((f"{src} ", INK), ("-> ", DIM), (f"{dst}", INK), (f"   w {e['w']:.2f}  {e['origin']}  {e['confirmations']} confirmations", DIM))
    console.print()
    if not res["lessons"]:
        line(("in the official map; no postmortem taught it", DIM))
        return
    for les in res["lessons"]:
        t = Text("  ")
        t.append("lesson ", style=DIM)
        t.append(f"L{les['id']}", style=VIOLET_TEXT)
        t.append(f"  {les['state']}  w {les['w']:.2f}  created at revision {les['created_seq']}", style=DIM)
        console.print(t)
        for x in les["taught_by"]:
            pm = x["postmortem"]
            line(("  taught by   ", DIM), (f"{x['incident']}", INK), (f"  root {pm['root']}  path {pm['path'].replace('>', ' -> ')}", DIM))
            if pm["missed"]:
                line(("              ", DIM), (f"silent in that incident: {', '.join(pm['missed'])}", DIM))
        for x in les["confirmed_by"]:
            t = Text("  ")
            t.append("  confirmed   ", style=DIM)
            t.append("ok ", style=TEAL)
            t.append(x["incident"], style=INK)
            console.print(t)
        if not les["confirmed_by"]:
            line(("  confirmed   not yet", DIM))
    console.print()
    line((f"gw why-edge answers by traversal: Lesson -> Postmortem -> Incident, in HydraDB", DIM))


# ---- change -----------------------------------------------------------------------------
change_app = typer.Typer(help="What changed: deploys and config changes the verdict can use.", no_args_is_help=True)
app.add_typer(change_app, name="change")


@change_app.command("add")
def change_add(service: str = typer.Argument(..., help="service name or alias"),
               kind: str = typer.Option("deploy", "--kind", help="deploy | config | release"),
               ref: str = typer.Option("", "--ref", help="for example '#482' or a commit"),
               ts: Optional[str] = typer.Option(None, "--ts", help="epoch seconds or ISO-8601 (default: now)")):
    """Record a change. Used by `gw why --use-changes`."""
    from .integrations.issues import parse_ts
    ws = workspace()
    try:
        ev = ws.add_change(service, parse_ts(ts), kind, ref)
    except ValueError as e:
        fail(str(e))
    prompt_line(f"gw change add {service}" + (f" --ref {ref}" if ref else ""))
    ok(f"{ev['service']} · {ev['kind']} {ev['ref']}".rstrip())


# ---- learn ------------------------------------------------------------------------------------
@app.command("learn")
def learn(incident: str = typer.Argument(...),
          root: str = typer.Option(..., "--root", help="the service that actually broke"),
          path_: str = typer.Option("", "--path", help="root first, e.g. 'config-svc -> fraud-check -> checkout-api'"),
          missed: str = typer.Option("", "--missed", help="what the map got wrong (optional)"),
          yes: bool = typer.Option(False, "--yes", "-y")):
    """Turn a postmortem into graph changes, review them, apply."""
    ws = workspace()
    inc = ws.get(incident)
    if inc is None:
        fail(f"no incident {incident}. Run `gw why` first.")
    prompt_line(f"gw learn {incident} --root {root}")
    line(("reading postmortem · 3 fields", DIM))
    console.print()
    pm = ws.make_pm({"root": root, "path": path_ or f"{root} -> {inc['verdict']['entry_name']}", "missed": missed})
    if pm["root"] is None:
        fail(f"'{root}' is not in the map")
    for u in pm["unresolved"]:
        line(("? ", AMBER), f"{u} ", ("not in the map; ignored", DIM))
    pv = ws.preview(inc, pm)
    if not pv["shown"]:
        line((f"nothing to change: the map already explains {incident}", DIM))
    color = {"+": VIOLET_TEXT, "~": AMBER, "=": "#A6A5B1", "−": RED}
    for r in pv["shown"]:
        t = Text("  ")
        t.append(r["symbol"] + " ", style=color[r["symbol"]])
        t.append(f"{r['text']:<34}")
        t.append(r["detail"], style=DIM)
        console.print(t)
    console.print()
    if pv["shown"] and not yes and not typer.confirm(f"  apply {len(pv['shown'])} changes?", default=True):
        line(("nothing applied", DIM))
        return
    r = ws.apply_pending(ws.queue(inc, pm, "cli")["id"])
    ok(f"graph updated · revision {r['revision']}")


# ---- eval -------------------------------------------------------------------------------------
METHOD_LABEL = [("oracle", "perfect map"), ("ghostwalk", "ghostwalk"), ("pagerank", "pagerank (tuned)"), ("placebo", "placebo"),
                ("learning_off", "learning off"), ("deepest", "deepest alert"), ("retrieval", "tf-idf retrieval"), ("random", "random")]


@app.command("eval")
def eval_(split: str = typer.Option("test", "--split", help="dev or test"),
          run: bool = typer.Option(False, "--run", help="recompute instead of reading the stored results"),
          results: Optional[pathlib.Path] = typer.Option(None, "--results", help="path to a results json")):
    """The held-out numbers: AC@1 with 95% bootstrap intervals, the gain over the best baseline, the gap closed."""
    if split not in ("dev", "test"):
        fail("--split must be dev or test")
    path = results or pathlib.Path("results.json" if split == "test" else "dev_results.json")
    prompt_line(f"gw eval --split {split}" + (" --run" if run else ""))
    if run:
        cmd = [sys.executable, "eval/full_eval.py", "--split", split] + (["--quick"] if split == "dev" else [])
        if subprocess.call(cmd, stdout=subprocess.DEVNULL) != 0:
            fail("eval failed; run it directly to see why: " + " ".join(cmd))
    if not path.exists():
        fail(f"{path} not found. Run `make {'eval' if split == 'test' else 'eval-quick'}` or pass --run.")
    r = json.loads(path.read_text(encoding="utf8"))
    m = r["methods"]
    line((f"{r['meta']['companies']} {'held-out' if r['meta']['split'] == 'test' else 'development'} companies · 95% bootstrap CI", DIM))
    console.print()
    line(("method           AC@1   95% CI", DIM))
    for key, label in METHOD_LABEL:
        if key not in m:
            continue
        a = m[key]["ac1"]
        mine = key == "ghostwalk"
        t = Text("  ")
        t.append(f"{label:<17}", style=VIOLET_TEXT if mine else None)
        t.append(f"{a['point']:.3f}", style=INK if mine else None)
        t.append(f"  {a['ci95'][0]:.3f}–{a['ci95'][1]:.3f}  ")
        t.append_text(bar(a["point"], VIOLET if mine else ("#DAD9E2" if key == "oracle" else MUTED_BAR), pad=False))
        console.print(t)
    console.print()
    g, c = r["headline"]["gain_vs_best"], r["headline"]["gap_closed"]
    t = Text("  ")
    t.append("ok ", style=TEAL)
    t.append("gain vs best baseline ")
    t.append(f"{g['point'] * 100:+.1f} pts", style=INK)
    t.append(f" ({g['baseline']})   gap closed ")
    t.append(f"{c['point'] * 100:.0f}%", style=INK)
    console.print(t)
    ok(f"{path.name} {'written' if run else 'read'} · {r['meta']['git']['short']} · {r['meta']['timestamp_utc'][:10]}")


# ---- export / diff ----------------------------------------------------------------------
@app.command("export")
def export_cmd(out: Optional[pathlib.Path] = typer.Option(None, "--out", help="write to a file instead of stdout")):
    """The graph (official + learned) and incident roots as JSON: the input `gw diff` needs in CI. `gw export > graph.json`."""
    from .diff import export_graph
    text = json.dumps(export_graph(workspace()), indent=1)
    if out:
        out.write_text(text, encoding="utf8")
    else:
        typer.echo(text)


@app.command("diff")
def diff_cmd(base: str = typer.Option("main", "--base", help="git ref to compare from"),
             head: str = typer.Option("HEAD", "--head", help="git ref to compare to"),
             repo: pathlib.Path = typer.Option(pathlib.Path("."), "--repo", exists=True, file_okay=False),
             graph: Optional[pathlib.Path] = typer.Option(None, "--graph", exists=True, dir_okay=False, help="graph export (gw export). Default: the local workspace if there is one"),
             fmt: str = typer.Option("text", "--format", help="text | markdown | json"),
             hops: int = typer.Option(3, "--hops", help="blast radius depth"),
             low: bool = typer.Option(False, "--low", help="also count low-confidence edges (Helm values)")):
    """Pre-deploy blast radius: dependencies this change adds or removes, and what hangs off them. Read-only, works offline."""
    from . import diff as D
    g = None
    if graph:
        g = json.loads(graph.read_text(encoding="utf8"))
    elif state_path().exists():
        g = D.export_graph(Workspace(state_path(), demo=False))
    try:
        rep = D.build_report(repo, base, head, g, "low" if low else "medium", hops)
    except D.GitError as e:
        fail(str(e))
    if fmt == "markdown":
        typer.echo(D.to_markdown(rep), nl=False)
        return
    if fmt == "json":
        typer.echo(D.to_json(rep))
        return
    prompt_line(f"gw diff --base {base} --head {head}")
    line((f"{len(rep['added'])} added · {len(rep['removed'])} removed dependencies", DIM))
    console.print()
    for a in rep["added"]:
        t = Text("  ")
        t.append("+ ", style=VIOLET_TEXT)
        t.append(f"{a['src']} → {a['dst']}")
        console.print(t)
        if a["known"] is None:
            line(("    no graph export: run `gw export > graph.json` for blast radius", DIM))
        elif not a["known"]:
            line((f"    {a['dst']} is not in the graph yet", DIM))
        else:
            n = len(a["blast"])
            line(("    blast radius ", DIM), (f"{n} service{'s' if n != 1 else ''}", INK), (f"  {D._names(a['blast'], 5)}", DIM))
            for l in a["touches_learned"][:3]:
                line(("    ", ), (f"⇢ learned edge touches it: {l}", VIOLET_TEXT))
            if a["incidents"]:
                line(("    ", ), (f"{a['dst']} caused {', '.join(a['incidents'][:3])}", AMBER))
    for r in rep["removed"]:
        t = Text("  ")
        t.append("− ", style=RED)
        t.append(f"{r['src']} → {r['dst']}")
        t.append(f"  removed ({r['file']})", style=DIM)
        console.print(t)
    if not rep["added"] and not rep["removed"]:
        line(("no dependency changes", DIM))


# ---- mcp --------------------------------------------------------------------------------------
@app.command("mcp")
def mcp_cmd():
    """Run the MCP server on stdio (tools: why, path, blast_radius, why_edge, lesson_impact, propose_edge). Read-only; GW_URL + GW_TOKEN for hosted mode."""
    from .mcp_server import main as serve
    serve()


if __name__ == "__main__":
    app()
