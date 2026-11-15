"""The six MCP tools as plain functions over a Workspace, so the stdio server, the hosted HTTP API and the tests share one implementation.

Read-only: why / path / blast_radius / why_edge / lesson_impact never change the graph. propose_edge only creates a PENDING proposal for a human to review.
GhostWalk never calls an LLM; the model on the other end asks, the graph answers."""
from __future__ import annotations
import math
from .api.alerts import normalize
from .api.workspace import Workspace
from .engine.walk import walk, resolve, explain, _limited_best, changes_before, change_note, tuned_changes
from .graph.state import W_TENTATIVE
from .integrations.issues import resolve_name


class ToolError(ValueError):
    pass


def _id(ws: Workspace, name: str) -> int:
    cid, _ = resolve_name(str(name), ws.g.names)
    if cid is None:
        close = [n for n in ws.g.names if str(name).lower() in n.lower()][:5]
        raise ToolError(f"'{name}' is not in the map" + (f". Did you mean: {', '.join(close)}?" if close else ""))
    return cid


def _alerts(raw):
    if isinstance(raw, list) and raw and all(isinstance(a, str) for a in raw):
        raw = [{"name": a, "t": float(i)} for i, a in enumerate(raw)]
    return normalize(raw)


def why(ws: Workspace, alerts) -> dict:
    rows = _alerts(alerts)
    import time
    epochs = [a["epoch"] for a in rows if a.get("epoch")]
    first = min(epochs) if epochs else time.time()
    gamma, tau = tuned_changes()
    ch = changes_before(ws.g, ws.changes, first) if ws.use_changes and ws.changes else None
    v = walk(ws.g, rows, changes=ch, gamma=gamma, tau=tau)
    if not v.ranking:
        raise ToolError("none of the alerting names match services in the map" + (f": {', '.join(v.unresolved[:5])}" if v.unresolved else ""))
    top = v.ranking[0][1]
    z = sum(math.exp(s - top) for _, s in v.ranking)
    name = lambda c: ws.g.components[c]["name"]
    A, _, _ = resolve(ws.g, rows)
    in_best, _ = _limited_best(ws.g.in_adj(), v.ranking[0][0], 5)
    explained = sum(1 for a in A if a in in_best)
    path = [{"from": name(u), "to": name(w), "origin": o} for u, w, o in v.path]
    root = name(v.ranking[0][0])
    learned = [p for p in path if p["origin"] == "learned"]
    text = f"Root cause: {root} ({math.exp(0) / z:.2f} confidence). It explains {explained} of {len(A)} alerting services."
    if path:
        text += " Path: " + path[0]["from"] + "".join(f" {'⇢' if p['origin'] == 'learned' else '→'} {p['to']}" for p in path) + "."
    note = change_note(ws.g, ws.changes, v.ranking[0][0], first) if ws.use_changes else None
    if note:
        text += f" {note[0].upper() + note[1:]}."
    if learned:
        text += f" {len(learned)} edge(s) on that path were learned from past postmortems and are not in the service catalog."
    return {"root": root, "confidence": round(1 / z, 4), "ranking": [{"service": name(c), "confidence": round(math.exp(s - top) / z, 4)} for c, s in v.ranking[:5]],
            "path": path, "explains": explained, "of": len(A), "unresolved": v.unresolved, "change_note": note, "explanation": text}


def path(ws: Workspace, root: str, service: str) -> dict:
    r, s = _id(ws, root), _id(ws, service)
    p = explain(ws.g, s, r, 5)
    if not p:
        return {"root": root, "service": service, "reachable": False, "path": [], "explanation": f"No dependency path from {service} to {root} within 5 hops."}
    hops = [{"from": ws.g.components[u]["name"], "to": ws.g.components[w]["name"], "origin": o, "weight": round(ws.g.edges[(u, w)].w, 3)} for u, w, o in p]
    return {"root": root, "service": service, "reachable": True, "path": hops,
            "explanation": f"{service} reaches {root} through " + " → ".join([hops[0]["from"]] + [h["to"] for h in hops]) + "."}


def blast_radius(ws: Workspace, service: str, hops: int = 3) -> dict:
    s = _id(ws, service)
    hops = max(1, min(int(hops), 6))
    best, _ = _limited_best(ws.g.in_adj(), s, hops)
    rows = sorted(((ws.g.components[c]["name"], round(p, 3)) for c, p in best.items() if c != s), key=lambda t: -t[1])
    return {"service": service, "hops": hops, "affected": [{"service": n, "likelihood": p} for n, p in rows], "count": len(rows),
            "explanation": f"If {service} fails, {len(rows)} services within {hops} hops depend on it, directly or not."}


def why_edge(ws: Workspace, src: str, dst: str) -> dict:
    """Why does the graph believe `src depends on dst`? Answered by traversal in HydraDB: the lesson, the postmortems that taught it, the incidents that confirmed it."""
    _id(ws, src), _id(ws, dst)
    try:
        r = ws.why_edge(src, dst)
    except LookupError as e:
        raise ToolError(str(e))
    if r["edge"] is None:
        raise ToolError(f"there is no edge {src} -> {dst} in the map")
    if not r["lessons"]:
        return {**r, "explanation": f"{src} -> {dst} is in the official map (weight {r['edge']['w']:.2f}); no postmortem taught it."}
    les = r["lessons"][0]
    t = les["taught_by"][0] if les["taught_by"] else None
    c = les["confirmed_by"]
    text = (f"{src} -> {dst} was learned: proposed from {t['incident']} (root {t['postmortem']['root']}, path {t['postmortem']['path'].replace('>', ' -> ')})"
            if t else f"{src} -> {dst} was learned")
    text += f", confirmed by {', '.join(x['incident'] for x in c)}" if c else ", not confirmed yet"
    return {**r, "explanation": text + f". Now {les['state']}, weight {les['w']:.2f}."}


def lesson_impact(ws: Workspace, lesson_id: int) -> dict:
    """Services and past incidents whose paths use a learned edge (a Lesson node in HydraDB)."""
    try:
        r = ws.lesson_impact(int(lesson_id))
    except LookupError as e:
        raise ToolError(str(e))
    if r is None:
        raise ToolError(f"no lesson {lesson_id}")
    return {**r, "explanation": f"{r['lesson']['src']} -> {r['lesson']['dst']} ({r['lesson']['state']}) sits on paths that reach {len(r['services'])} services "
                               f"and was relevant to {len(r['incidents'])} past incidents."}


def propose_edge(ws: Workspace, src: str, dst: str, incident_id: str | None = None, reason: str = "") -> dict:
    """src depends on dst. Creates a PENDING proposal only; a human applies it in Learn."""
    u, v = _id(ws, src), _id(ws, dst)
    if u == v:
        raise ToolError("src and dst are the same service")
    item = ws.queue_edge(u, v, incident_id, reason)
    return {"proposal": item["id"], "status": "pending", "applied": False,
            "message": f"Proposed {src} ⇢ {dst} at tentative weight {W_TENTATIVE}. It is not in the graph until a person approves it in Learn."}
