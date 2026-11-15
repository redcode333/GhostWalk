"""gw: the GhostWalk CLI. Output follows design/CLI.dc.html (rich for colours and bars).

    gw map import ./acme            scan repos, save the proposed map
    gw why --alerts alerts.json     rank root causes for an alert storm
    gw learn INC-1042 --root X      turn a postmortem into reviewed graph changes
    gw eval --split test            print the held-out numbers from results.json (--run recomputes them)
    gw demo                         a demo workspace + the next outage as alerts.json, to try the above
"""
from __future__ import annotations
import json, os, pathlib, subprocess, sys
import click
from rich.console import Console
from rich.text import Text

from .api.workspace import Workspace, ui_kind
from .discover.scan import scan_directory, proposals
from .integrations import issues

VIOLET, VIOLET_TEXT, TEAL, AMBER, DIM, INK, MUTED_BAR, EMPTY = "#8E76FF", "#AC9BFF", "#12B5A0", "#F5B83F", "#8F8E9A", "#F6F5F1", "#4A4955", "#3A3A44"
TIER = {"edge": "#3D7DFF", "service": "#12B5A0", "data": "#E2549A", "infra": "#7FB800"}
BAR = 20
console = Console(highlight=False, soft_wrap=False)


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


def state_path():
    return pathlib.Path(os.environ.get("GW_HOME", ".gw")) / "state.json"


def workspace(create=False) -> Workspace:
    p = state_path()
    if not p.exists() and not create:
        raise click.ClickException("no map yet. Run `gw map import ./your-repos` (or `gw demo` to try it).")
    return Workspace(p, demo=False)


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
def main():
    """GhostWalk: why is it broken, and what should the map have said?"""


@main.group("map")
def map_():
    """The dependency map."""


@map_.command("import")
@click.argument("path", type=click.Path(exists=True, file_okay=False))
@click.option("--all", "take_all", is_flag=True, help="also accept low-confidence edges")
def map_import(path, take_all):
    """Scan PATH (each subfolder is a repo) for compose, k8s, Helm and *_URL evidence."""
    root = pathlib.Path(path)
    repos = [d for d in root.iterdir() if d.is_dir() and not d.name.startswith(".")] or [root]
    prompt_line(f"gw map import {path}")
    line((f"scanning {len(repos)} repo{'s' if len(repos) != 1 else ''} …", DIM))
    console.print()
    found = scan_directory(root)
    out = proposals(found)
    s = out["summary"]
    for label in ("docker-compose", "k8s manifests", "Helm values", "env vars"):
        if s["by_source"].get(label):
            shown = {"docker-compose": "docker-compose.yml", "k8s manifests": "k8s/*.yaml", "Helm values": "Helm values", "env vars": "env vars  *_URL"}[label]
            line(f"{shown:<26}{s['by_source'][label]:>3} edges")
    console.print()
    ws = workspace(create=True)
    ids = [e["id"] for e in out["edges"] if take_all or e["accepted"]]
    ws.set_proposals(out)
    r = ws.accept_map(ids)
    t = Text("  ")
    t.append("✓ ", style=TEAL)
    t.append(f"{r['services']} services · {r['dependencies']} dependencies")
    console.print(t)
    console.print()
    legend = Text("    ")
    for k in ("edge", "service", "data", "infra"):
        n = s["by_kind"].get(k, 0)
        legend.append("●", style=TIER[k]).append(f" {k} {n}   ")
    console.print(legend)
    skipped = len(out["edges"]) - len(ids)
    if skipped:
        line((f"{skipped} low-confidence edge{'s' if skipped != 1 else ''} left out (use --all to include)", DIM))


@main.command("demo")
@click.option("--alerts", "alerts_out", default="alerts.json", show_default=True)
def demo(alerts_out):
    """Create the simulated acme-demo workspace and write the next outage to alerts.json."""
    p = state_path()
    ws = Workspace(p, demo=True)
    nxt = ws.company["incidents"][ws.next_sim]["alerts"]
    pathlib.Path(alerts_out).write_text(json.dumps({"alerts": nxt}, indent=1))
    ws.save()
    line((f"acme-demo · {len(ws.g.components)} services · {len(ws.incidents)} past incidents", DIM))
    line((f"wrote {alerts_out} ({len(nxt)} alerts). Now: gw why --alerts {alerts_out}", DIM))


def _load_alerts(path):
    from .api.alerts import normalize
    try:
        return normalize(json.loads(pathlib.Path(path).read_text(encoding="utf8")))
    except ValueError as e:
        raise click.ClickException(str(e))


@main.command("why")
@click.option("--alerts", "alerts_file", required=True, type=click.Path(exists=True, dir_okay=False))
@click.option("--top", default=3, show_default=True)
def why(alerts_file, top):
    """Rank the likely root causes of an alert storm and show the path."""
    ws = workspace()
    alerts = _load_alerts(alerts_file)
    prompt_line(f"gw why --alerts {alerts_file}")
    inc = ws.ingest_alerts(alerts, source="cli")
    v = inc["verdict"]
    if v["root"] is None:
        raise click.ClickException("none of the alerting names match services in the map. " + (f"Unknown: {', '.join(v['unresolved'][:5])}" if v["unresolved"] else ""))
    line((f"{len(alerts)} alerts · {v['services']} services · walked {v['edges_walked']} edges in {v['ms']:.0f} ms", DIM))
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
            t.append(" ⇢ " if hop["origin"] == "learned" else " → ", style=VIOLET_TEXT if hop["origin"] == "learned" else None)
            t.append(hop["v_name"])
        console.print(t)
        for l in v["learned_on_path"]:
            n = l["confirmations"]
            src = f"learned from {l['incident']}" if l.get("incident") else "learned"
            line(("        ", ), (f"⇢ {src}, confirmed {'twice' if n == 2 else str(n) + '×' if n > 2 else 'once'}", VIOLET_TEXT))
        console.print()
    order = [b["name"] for b in sorted((b for b in v["blast"] if b["alerting"]), key=lambda b: b["onset"] or 0)]
    t = Text("  ")
    t.append("why   ", style=DIM)
    t.append(f"explains {v['explains']} of {v['of']} alerts")
    if v["path"]:
        names = [v["path"][0]["u_name"]] + [h["v_name"] for h in v["path"]]
        alerted = [n for n in order if n in names]
        in_order = alerted == [n for n in reversed(names) if n in alerted]
        t.append(" · fired in path order" if in_order and len(alerted) > 1 else "")
    console.print(t)
    line((f"{inc['id']} saved. Teach it: gw learn {inc['id']} --root {v['root_name']}", DIM))


@main.command("learn")
@click.argument("incident")
@click.option("--root", required=True, help="the service that actually broke")
@click.option("--path", "path_", default="", help="root first, e.g. 'config-svc -> fraud-check -> checkout-api'")
@click.option("--missed", default="", help="what the map got wrong (optional)")
@click.option("--yes", "-y", is_flag=True)
def learn(incident, root, path_, missed, yes):
    """Turn a postmortem into graph changes, review them, apply."""
    ws = workspace()
    inc = ws.get(incident)
    if inc is None:
        raise click.ClickException(f"no incident {incident}. Run `gw why` first.")
    prompt_line(f"gw learn {incident} --root {root}")
    line((f"reading postmortem · 3 fields", DIM))
    console.print()
    fields = {"root": root, "path": path_ or f"{root} -> {inc['verdict']['entry_name']}", "missed": missed}
    pm = ws.make_pm(fields)
    if pm["root"] is None:
        raise click.ClickException(f"'{root}' is not in the map")
    for u in pm["unresolved"]:
        line(("? ", AMBER), f"{u} ", ("not in the map; ignored", DIM))
    pv = ws.preview(inc, pm)
    if not pv["shown"]:
        line((f"nothing to change: the map already explains {incident}", DIM))
    color = {"+": VIOLET_TEXT, "~": AMBER, "=": "#A6A5B1", "−": "#D9534F"}
    for r in pv["shown"]:
        t = Text("  ")
        t.append(r["symbol"] + " ", style=color[r["symbol"]])
        t.append(f"{r['text']:<34}")
        t.append(r["detail"], style=DIM)
        console.print(t)
    console.print()
    if pv["shown"] and not yes and not click.confirm(f"  apply {len(pv['shown'])} changes?", default=True):
        line(("nothing applied", DIM))
        return
    item = ws.queue(inc, pm, "cli")
    r = ws.apply_pending(item["id"])
    t = Text("  ")
    t.append("✓ ", style=TEAL)
    t.append(f"graph updated · revision {r['revision']}")
    console.print(t)


METHOD_LABEL = [("oracle", "perfect map"), ("ghostwalk", "ghostwalk"), ("pagerank", "pagerank (tuned)"), ("placebo", "placebo"),
                ("learning_off", "learning off"), ("deepest", "deepest alert"), ("retrieval", "tf-idf retrieval"), ("random", "random")]


@main.command("eval")
@click.option("--split", default="test", type=click.Choice(["dev", "test"]), show_default=True)
@click.option("--run", is_flag=True, help="recompute instead of reading the stored results (dev: quick; test: full, ~1 min plus the store swap)")
@click.option("--results", default=None, type=click.Path(), help="path to results json")
def eval_(split, run, results):
    """The held-out numbers: AC@1 with 95% bootstrap intervals, the gain over the best baseline, the gap closed."""
    path = pathlib.Path(results or ("results.json" if split == "test" else "dev_results.json"))
    prompt_line(f"gw eval --split {split}" + (" --run" if run else ""))
    if run:
        cmd = [sys.executable, "eval/full_eval.py", "--split", split] + (["--quick"] if split == "dev" else [])
        if subprocess.call(cmd, stdout=subprocess.DEVNULL) != 0:
            raise click.ClickException("eval failed; run it directly to see why: " + " ".join(cmd))
    if not path.exists():
        raise click.ClickException(f"{path} not found. Run `make {'eval' if split == 'test' else 'eval-quick'}` or pass --run.")
    r = json.loads(path.read_text(encoding="utf8"))
    m = r["methods"]
    line((f"{r['meta']['companies']} {'held-out' if r['meta']['split'] == 'test' else 'development'} companies · 95% bootstrap CI", DIM))
    console.print()
    line(("method           AC@1   95% CI", DIM))
    for key, label in METHOD_LABEL:
        if key not in m:
            continue
        a = m[key]["ac1"]
        t = Text("  ")
        mine = key == "ghostwalk"
        t.append(f"{label:<17}", style=VIOLET_TEXT if mine else None)
        t.append(f"{a['point']:.3f}", style=INK if mine else None)
        t.append(f"  {a['ci95'][0]:.3f}–{a['ci95'][1]:.3f}  ")
        t.append_text(bar(a["point"], VIOLET if mine else ("#DAD9E2" if key == "oracle" else MUTED_BAR), pad=False))
        console.print(t)
    console.print()
    h = r["headline"]
    g, c = h["gain_vs_best"], h["gap_closed"]
    t = Text("  ")
    t.append("✓ ", style=TEAL)
    t.append("gain vs best baseline ")
    t.append(f"{g['point'] * 100:+.1f} pts", style=INK)
    t.append(f" ({g['baseline']})   gap closed ")
    t.append(f"{c['point'] * 100:.0f}%", style=INK)
    console.print(t)
    t = Text("  ")
    t.append("✓ ", style=TEAL)
    t.append(f"{path.name} {'written' if run else 'read'} · {r['meta']['git']['short']} · {r['meta']['timestamp_utc'][:10]}")
    console.print(t)


if __name__ == "__main__":
    main()
