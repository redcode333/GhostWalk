"""Pre-deploy blast radius: which dependencies does this change add or remove, and what would hang off them?

`gw diff --base main --head HEAD` parses the infra files at two git refs with the SAME parsers as onboarding, diffs the edge sets, and for
every added edge asks the CURRENT graph (official + learned, from `gw export`) what is upstream of the new dependency. Read-only, and it
works offline against a graph export file, so forks and CI need no token.
"""
from __future__ import annotations
import json, pathlib, subprocess
from .discover.parsers import classify, merge
from .discover.scan import scan_texts
from .engine.walk import _limited_best
from .graph.state import Edge, GraphState

MARKER = "<!-- ghostwalk-diff -->"
CONF_RANK = {"low": 0, "medium": 1, "high": 2}


class GitError(RuntimeError):
    pass


def _git(repo, *args):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf8")
    if r.returncode != 0:
        raise GitError(r.stderr.strip() or f"git {' '.join(args)} failed")
    return r.stdout


def edges_at(repo, ref, min_conf="medium"):
    """{(src, dst): {"confidence", "file", "evidence"}} for the infra files at `ref`."""
    repo = pathlib.Path(repo).resolve()
    files = []
    for path in _git(repo, "ls-tree", "-r", "--name-only", ref).splitlines():
        if classify(path):
            files.append((repo.name, path, _git(repo, "show", f"{ref}:{path}")))
    found = scan_texts(files)
    return {e.key(): {"confidence": e.confidence, "file": e.file, "evidence": e.evidence}
            for e in merge(found) if CONF_RANK[e.confidence] >= CONF_RANK[min_conf]}


def diff_edges(base: dict, head: dict):
    added = sorted(k for k in head if k not in base)
    removed = sorted(k for k in base if k not in head)
    return added, removed


# ---- graph export ------------------------------------------------------------------------------
def export_graph(ws) -> dict:
    g = ws.g
    return {"version": 1, "revision": ws.revision,
            "components": {str(i): c for i, c in g.components.items()}, "names": g.names,
            "edges": [[u, v, round(e.w, 4), e.origin, e.confirmations, e.learned_from] for (u, v), e in g.edges.items()],
            "incidents": [{"id": i["id"], "root": i["verdict"]["root_name"], "confirmed_root": i.get("confirmed_root"), "status": i["status"]}
                          for i in ws.incidents]}


def load_graph(d: dict):
    g = GraphState(components={int(i): c for i, c in d["components"].items()})
    g.names = dict(d["names"])
    for u, v, w, origin, conf, lf in d["edges"]:
        g.edges[(u, v)] = Edge(w, origin, conf, lf)
    return g, d.get("incidents", []), d.get("revision")


# ---- analysis ----------------------------------------------------------------------------------
def analyse_added(g: GraphState, incidents, src: str, dst: str, hops=3):
    d_id, s_id = g.names.get(dst), g.names.get(src)
    out = {"src": src, "dst": dst, "known": d_id is not None, "blast": [], "touches_learned": [], "incidents": []}
    if d_id is None:
        return out
    in_adj = g.in_adj()
    reach = {}
    for start in {d_id} | ({s_id} if s_id is not None else set()):
        best, _ = _limited_best(in_adj, start, hops)
        for c, p in best.items():
            if c != d_id and p > reach.get(c, 0):
                reach[c] = p
    if s_id is not None and s_id != d_id:
        reach[s_id] = max(reach.get(s_id, 0), 1.0)           # the new dependent itself
    out["blast"] = [g.components[c]["name"] for c, _ in sorted(reach.items(), key=lambda t: (-t[1], g.components[t[0]]["name"]))]
    out["touches_learned"] = sorted(f"{g.components[u]['name']} ⇢ {g.components[v]['name']}"
                                    for (u, v), e in g.edges.items() if e.origin == "learned" and d_id in (u, v))
    out["incidents"] = sorted({i["id"] for i in incidents if (i.get("confirmed_root") or "") == dst})
    return out


def build_report(repo, base, head, graph=None, min_conf="medium", hops=3):
    b, h = edges_at(repo, base, min_conf), edges_at(repo, head, min_conf)
    added, removed = diff_edges(b, h)
    g = incidents = rev = None
    if graph:
        g, incidents, rev = load_graph(graph)
    items = []
    for src, dst in added:
        a = analyse_added(g, incidents, src, dst, hops) if g else {"src": src, "dst": dst, "known": None, "blast": [], "touches_learned": [], "incidents": []}
        a.update(file=h[(src, dst)]["file"], evidence=h[(src, dst)]["evidence"], confidence=h[(src, dst)]["confidence"])
        items.append(a)
    return {"base": base, "head": head, "added": items, "removed": [{"src": s, "dst": d, "file": b[(s, d)]["file"]} for s, d in removed],
            "graph": {"loaded": g is not None, "revision": rev}}


# ---- rendering ---------------------------------------------------------------------------------
def _names(xs, n=4):
    return ", ".join(xs[:n]) + (", …" if len(xs) > n else "")


def line_for(a):
    parts = [f"+ `{a['src']}` → `{a['dst']}`", "new dependency"]
    if a["known"] is None:
        parts.append("no graph export, so no blast radius")
    elif not a["known"]:
        parts.append(f"`{a['dst']}` is not in the graph yet")
    else:
        n = len(a["blast"])
        parts.append(f"blast radius {n} service{'s' if n != 1 else ''}" + (f" ({_names(a['blast'])})" if n else ""))
        if a["touches_learned"]:
            parts.append("a learned edge already touches it: " + _names(a["touches_learned"], 2))
        if a["incidents"]:
            parts.append(f"`{a['dst']}` caused {', '.join(a['incidents'][:3])}")
    return " · ".join(parts)


def to_markdown(rep) -> str:
    out = [MARKER, "### GhostWalk: dependency changes in this PR", ""]
    if not rep["added"] and not rep["removed"]:
        out.append(f"No dependency changes between `{rep['base']}` and `{rep['head']}`.")
    for a in rep["added"]:
        out.append("- " + line_for(a))
    for r in rep["removed"]:
        out.append(f"- − `{r['src']}` → `{r['dst']}` · removed (`{r['file']}`)")
    out += ["", f"<sub>Read-only. Compared `{rep['base']}` with `{rep['head']}`"
            + (f" against graph revision {rep['graph']['revision']}." if rep["graph"]["loaded"] else " without a graph export (add `gw export > graph.json` for blast radius).") + "</sub>"]
    return "\n".join(out) + "\n"


def to_json(rep) -> str:
    return json.dumps(rep, indent=2, ensure_ascii=False)
