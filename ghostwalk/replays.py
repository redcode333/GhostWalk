"""Real-outage replays: two public postmortems (Cloudflare, 18 Nov 2025; AWS us-east-1, 20 Oct 2025) turned into small scenarios and run through the real engine and learner.

Replay built from the public postmortem; illustrative, not an accuracy measurement. The 'official map' is our construction of what a service catalog would list (without the hidden dependency); nothing here
says GhostWalk would have prevented either outage. The scenario files are in docs/replays/.

Stages, on the SAME alerts: (1) the official map without the hidden dependency; (2) after one postmortem teaches the missing edge (tentative); (3) after a second incident confirms it. The deepest-alert baseline runs on the
official map. The LLM answer for the same input is recorded by eval/replays.py (cached) and attached here when present."""
from __future__ import annotations
import json, math, pathlib, time
from baselines import simple
from .engine.walk import walk
from .graph.state import GraphState
from .learn import update

ROOT = pathlib.Path(__file__).resolve().parent.parent
DIR = ROOT / "docs" / "replays"
ABSTAIN_BELOW = 0.5            # a verdict whose top confidence is under this is shown as "not sure": the product would ask for a second look instead of naming a service


def ids():
    return sorted(p.stem for p in DIR.glob("*.json") if p.stem != "results")


def load(sid: str) -> dict:
    return json.loads((DIR / f"{sid}.json").read_text(encoding="utf8"))


def graph(sc) -> tuple[GraphState, dict]:
    comps = [{"id": i, "name": s["name"], "kind": s["kind"], "tier": s["tier"]} for i, s in enumerate(sc["services"])]
    idx = {c["name"]: c["id"] for c in comps}
    g = GraphState.from_official({"components": comps, "edges": [{"u": idx[a], "v": idx[b]} for a, b in sc["official_edges"]]})
    return g, idx


def _view(g, v, ms, root_name):
    name = lambda i: g.components[i]["name"]
    top = v.ranking[0][1] if v.ranking else 0.0
    z = sum(math.exp(s - top) for _, s in v.ranking) or 1.0
    ranked = [{"name": name(c), "confidence": round(math.exp(s - top) / z, 4)} for c, s in v.ranking[:5]]
    rank = next((i + 1 for i, (c, _) in enumerate(v.ranking) if name(c) == root_name), None)
    conf = ranked[0]["confidence"] if ranked else 0.0
    return {"ranking": ranked, "top1": ranked[0]["name"] if ranked else None, "confidence": conf, "top1_is_root": bool(ranked) and ranked[0]["name"] == root_name,
            "root_rank": rank, "abstains": conf < ABSTAIN_BELOW,
            "path": [{"from": name(u), "to": name(w), "origin": o} for u, w, o in v.path], "ms": round(ms, 3)}


def run(sid: str) -> dict:
    sc = load(sid)
    g, idx = graph(sc)
    alerts = sc["alerts"]
    root = sc["root"]
    pm = {"root": idx[root], "chain": [[idx[a], idx[b]] for a, b in sc["postmortem"]["chain"]], "aliases": []}
    stages = []

    def stage(label, g):
        t = time.perf_counter()
        v = walk(g, alerts)
        ms = (time.perf_counter() - t) * 1000
        stages.append({"stage": label, **_view(g, v, ms, root)})
        return v
    v0 = stage("official map (the hidden dependency is missing)", g)
    ops1 = update.propose(g, pm, v0, alerts, g.seq)
    update.apply(g, ops1)
    v1 = stage("after one postmortem teaches the edge (tentative)", g)
    ops2 = update.propose(g, pm, v1, alerts, g.seq)
    update.apply(g, ops2)
    stage("after a second incident confirms it", g)
    g0, _ = graph(sc)
    deepest = simple.rank_deepest(g0, alerts, max_hops=5)
    return {"id": sid, "short": sc["short"], "title": sc["title"], "source": sc["source"], "label": sc["label"], "what_happened": sc["what_happened"], "assumptions": sc["assumptions"],
            "root": root, "hidden_edge": sc["hidden_edge"], "alerts": [a["name"] for a in alerts], "services": len(sc["services"]), "official_edges": len(sc["official_edges"]),
            "learned_ops": {"first": [o["op"] for o in ops1 if o["op"] in ("add_edge", "confirm", "reweight")], "second": [o["op"] for o in ops2 if o["op"] in ("add_edge", "confirm", "reweight")]},
            "stages": stages,
            "deepest_alert": {"ranking": [g0.components[c]["name"] for c in deepest[:5]], "top1": g0.components[deepest[0]]["name"] if deepest else None,
                              "top1_is_root": bool(deepest) and g0.components[deepest[0]]["name"] == root,
                              "root_rank": next((i + 1 for i, c in enumerate(deepest) if g0.components[c]["name"] == root), None)}}


def cached_llm(sid: str):
    f = DIR / "results.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf8")).get("llm", {}).get(sid)
    return None


def run_all(with_llm=True):
    out = []
    for sid in ids():
        r = run(sid)
        if with_llm:
            r["llm"] = cached_llm(sid)
        out.append(r)
    return out
