"""The landing page's "Inside GhostWalk" panels run on this: a small scenario pushed through the REAL engine and learner,
so every confidence on the page is computed, not typed. Before: the hidden dependency is missing from the map.
After: the postmortem has been applied (tentative edge, then confirmed by a second incident)."""
from __future__ import annotations
import copy, math
from ..engine.walk import walk, resolve
from ..graph.state import GraphState
from ..learn import update
from .workspace import ui_kind

NODES = [("web-edge", "service", 0), ("checkout-api", "service", 1), ("payments", "service", 1), ("cart", "service", 1),
         ("fraud-check", "service", 1), ("search", "service", 1), ("postgres-pay", "datastore", 3), ("redis-main", "cache", 3), ("config-svc", "shared", 3)]
OFFICIAL = [("web-edge", "checkout-api"), ("web-edge", "search"), ("checkout-api", "payments"), ("checkout-api", "cart"), ("payments", "fraud-check"),
            ("payments", "postgres-pay"), ("cart", "redis-main"), ("search", "redis-main"), ("fraud-check", "postgres-pay")]
# What really exists but the catalog never listed:
HIDDEN = ("fraud-check", "config-svc")
ALERTS = [("config-svc", "saturation", 0.0), ("fraud-check", "error_rate", 22.0), ("payments", "latency_p99", 41.0),
          ("checkout-api", "error_rate", 63.0), ("web-edge", "error_rate", 80.0)]


def _g():
    ids = {n: i for i, (n, _, _) in enumerate(NODES)}
    comps = {i: {"name": n, "kind": k, "tier": t} for i, (n, k, t) in enumerate(NODES)}
    g = GraphState(components=comps)
    g.names = {n: i for n, i in ids.items()}
    from ..graph.state import Edge, W0_OFFICIAL
    for a, b in OFFICIAL:
        g.edges[(ids[a], ids[b])] = Edge(W0_OFFICIAL)
    return g, ids


def _verdict(g, alerts):
    v = walk(g, alerts)
    top = v.ranking[0][1]
    z = sum(math.exp(s - top) for _, s in v.ranking)
    ranking = [{"id": c, "name": g.components[c]["name"], "confidence": round(math.exp(s - top) / z, 4)} for c, s in v.ranking[:5]]
    path = [{"u": u, "v": w, "origin": o} for u, w, o in v.path]
    return ranking, path, v


def demo_inside():
    g, ids = _g()
    alerts = [{"name": n, "signal": s, "t": t} for n, s, t in ALERTS]
    # config-svc alerts too, but nothing in the map connects it to the others:
    alerts_seen = alerts
    before, path_before, _ = _verdict(g, alerts_seen)
    pm = {"root": ids["config-svc"], "chain": [[ids["fraud-check"], ids["config-svc"]], [ids["payments"], ids["fraud-check"]], [ids["checkout-api"], ids["payments"]]],
          "aliases": [["cfg", ids["config-svc"]]], "correct": True}
    ops1 = update.propose(g, pm, walk(g, alerts_seen), alerts_seen, g.seq)
    shown = []
    n = lambda i: g.components[i]["name"]
    for i, o in enumerate(ops1):
        if o["op"] == "add_edge":
            shown.append({"index": i, "symbol": "+", "text": f"{n(o['u'])} ⇢ {n(o['v'])}", "detail": f"tentative {o['w']:.2f}", "apply": True})
        elif o["op"] == "reweight" and abs(g.edges[(o["u"], o["v"])].w - o["w"]) > 1e-9:
            shown.append({"index": i, "symbol": "~", "text": f"{n(o['u'])} → {n(o['v'])}", "detail": f"reweight {g.edges[(o['u'], o['v'])].w:.2f} → {o['w']:.2f}"})
        elif o["op"] == "alias":
            shown.append({"index": i, "symbol": "=", "text": f"\"{o['name']}\" alias of {n(o['id'])}", "detail": "alias"})
    g2 = copy.deepcopy(g)
    update.apply(g2, ops1)
    # a second incident with the same root confirms the edge and counts the root (that is how a tentative edge grows up)
    ops2 = update.propose(g2, pm, walk(g2, alerts_seen), alerts_seen, g2.seq)
    update.apply(g2, ops2)
    import time
    t0 = time.perf_counter()
    after, path_after, _ = _verdict(g2, alerts_seen)
    ms = (time.perf_counter() - t0) * 1000
    nodes = [{"id": i, "name": c["name"], "kind": ui_kind(c), "tier": c["tier"], "alerting": c["name"] in {a["name"] for a in alerts_seen}}
             for i, c in g.components.items()]
    edges = [{"u": u, "v": v, "origin": "official"} for (u, v) in g.edges]
    learned = [{"u": u, "v": v, "origin": "learned", "w": round(e.w, 2)} for (u, v), e in g2.edges.items() if e.origin == "learned"]
    # "Search old postmortems": the TF-IDF baseline over a few earlier incidents of the same company (each one's postmortem names its root).
    # None of them had config-svc as the root, which is the point: this is a first-time cause, so there is nothing to retrieve.
    from ..engine.walk import _limited_best
    from baselines import simple
    pm_of = lambda root: {"root": ids[root]}
    hist_spec = [("INC-0907", "postgres-pay", [("checkout-api", "error_rate"), ("payments", "latency_p99"), ("postgres-pay", "saturation")]),
                 ("INC-0931", "fraud-check", [("fraud-check", "latency_p99"), ("payments", "timeouts"), ("checkout-api", "error_rate")]),
                 ("INC-0958", "redis-main", [("search", "timeouts"), ("cart", "latency_p99"), ("redis-main", "saturation")]),
                 ("INC-0984", "payments", [("payments", "error_rate"), ("checkout-api", "error_rate")])]
    history = [{"alerts": [{"name": n, "signal": sg, "t": float(i)} for i, (n, sg) in enumerate(al)], "postmortem": pm_of(root), "root": ids[root]} for _, root, al in hist_spec]
    ranked = simple.rank_retrieval(g, alerts, history)
    inc_of = {ids[r]: i for i, r, _ in hist_spec}
    search = {"query": [f"{a['name']}|{a['signal']}" for a in alerts],
              "matches": [{"incident": inc_of[c], "root": g.components[c]["name"]} for c in ranked if c in inc_of][:3]}
    root_id = after[0]["id"]
    best, _ = _limited_best(g2.in_adj(), root_id, 3)
    blast = sorted(g.components[c]["name"] for c in best if c != root_id)
    return {"ms": round(ms, 2), "search": search, "blast": blast, "nodes": nodes, "edges": edges, "learned_edges": learned, "before": {"ranking": before, "path": path_before},
            "after": {"ranking": after, "path": path_after}, "changes": shown, "alerts": len(alerts_seen),
            "note": "computed by the real engine and learner on a 9-service scenario; the second matching incident confirms the edge"}
