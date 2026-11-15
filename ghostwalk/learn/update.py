"""Learning loop: a postmortem (root, causal chain, aliases) becomes a graph diff.

Diff ops are plain dicts so the same diff can be shown on the Learn screen, applied to
the in-memory state, or written to HydraDB.
"""
from __future__ import annotations
from ..graph.state import Edge, W_TENTATIVE, W_CONFIRMED

ETA_UP = 0.3
DECAY_WRONG = 0.85
DROP_BELOW = 0.1

ALL_STEPS = ("hidden", "reweight", "alias", "shortcut", "guard", "blind")


def propose(g, pm, verdict, alerts, seq, steps=ALL_STEPS):
    ops = []
    if "alias" in steps:
        for name, cid in pm.get("aliases", []):
            if name not in g.names and cid in g.components:
                ops.append({"op": "alias", "name": name, "id": cid})
    chain = [tuple(e) for e in pm.get("chain", []) if e[0] in g.components and e[1] in g.components]
    for u, v in chain:
        e = g.edges.get((u, v))
        if e is None:
            if "hidden" in steps:
                ops.append({"op": "add_edge", "u": u, "v": v, "w": W_TENTATIVE if "guard" in steps else W_CONFIRMED})
        elif e.origin == "learned" and e.confirmations < 2 and "guard" in steps:
            ops.append({"op": "confirm", "u": u, "v": v, "w": max(e.w, W_CONFIRMED)})
        elif "reweight" in steps:
            ops.append({"op": "reweight", "u": u, "v": v, "w": round(e.w + ETA_UP * (1 - e.w), 4)})
    truth_root = pm.get("root")
    if verdict is not None and verdict.ranking and verdict.ranking[0][0] != truth_root and "reweight" in steps:
        on_chain = set(chain)
        for u, v, _ in verdict.path:  # edges that led the walk astray
            if (u, v) in on_chain:
                continue
            e = g.edges[(u, v)]
            nw = round(e.w * (0.5 if (e.origin == "learned" and e.confirmations < 2) else DECAY_WRONG), 4)
            ops.append({"op": "drop_edge", "u": u, "v": v} if nw < DROP_BELOW else {"op": "reweight", "u": u, "v": v, "w": nw})
    if truth_root in g.components:
        ops.append({"op": "root", "id": truth_root})
        if "shortcut" in steps and verdict is not None and verdict.entry is not None:
            ops.append({"op": "shortcut", "entry": verdict.entry, "root": truth_root})
    if "blind" in steps:
        alerted = {g.names.get(a["name"]) for a in alerts}
        for cid in {c for e in chain for c in e}:
            ops.append({"op": "observe", "id": cid, "silent": cid not in alerted})
    return [dict(o, seq=seq) for o in ops]


def apply(g, ops):
    for o in ops:
        k = o["op"]
        if k == "alias":
            g.names[o["name"]] = o["id"]
        elif k == "add_edge":
            g.edges[(o["u"], o["v"])] = Edge(o["w"], "learned", 1, o["seq"], o["seq"])
        elif k == "confirm":
            e = g.edges[(o["u"], o["v"])]
            e.w, e.confirmations = o["w"], e.confirmations + 1
        elif k == "reweight":
            g.edges[(o["u"], o["v"])].w = o["w"]
        elif k == "drop_edge":
            g.edges.pop((o["u"], o["v"]), None)
        elif k == "root":
            g.root_counts[o["id"]] = g.root_counts.get(o["id"], 0) + 1
        elif k == "shortcut":
            key = (o["entry"], o["root"])
            g.shortcuts[key] = g.shortcuts.get(key, 0) + 1
        elif k == "observe":
            g.affected[o["id"]] = g.affected.get(o["id"], 0) + 1
            if o["silent"]:
                g.missed[o["id"]] = g.missed.get(o["id"], 0) + 1
    g.seq += 1
    g.invalidate()                      # weights/edges changed: rebuild adjacency lazily on the next verdict
    return g
