"""Online evaluation: predict incident i on the graph after postmortems 1..i-1."""
from __future__ import annotations
import copy, json, pathlib, random
from gwsim.world import official_view
from ghostwalk.graph.state import GraphState
from ghostwalk.engine.walk import walk
from ghostwalk.learn import update
from baselines import simple

METHODS = ["ghostwalk", "learning_off", "oracle", "deepest", "pagerank", "retrieval", "random"]


def load(split, root="data"):
    return [json.loads(p.read_text()) for p in sorted(pathlib.Path(root, split).glob("*.json"))]


class _View:  # adapter so official_view works on the loaded dict
    def __init__(self, d):
        self.components, self.official_edges = d["components"], d["official_edges"]


def placebo_pm(co, inc, rng):
    """Control: a postmortem with a random root and random edges. Same shape, no information."""
    ids = [c["id"] for c in co["components"]]
    root = rng.choice(ids)
    chain = [[rng.choice(ids), rng.choice(ids)] for _ in inc["postmortem"]["chain"]]
    return {"root": root, "chain": [e for e in chain if e[0] != e[1]], "aliases": [], "correct": False}


def run_company(co, method, max_hops=5, steps=update.ALL_STEPS, placebo=False, seed=0, backend=None):
    """Returns per-incident rows: seq, truth, rank of truth (1-based, None if absent), top, confidence."""
    rng = random.Random(seed * 7919 + hash(co["name"]) % 10007)
    if method == "oracle":
        g = GraphState.from_truth(co)
    else:
        g = backend.fresh(co) if backend else GraphState.from_official(official_view(_View(co)))
    rows, history = [], []
    for inc in co["incidents"]:
        alerts, truth = inc["alerts"], inc["root"]
        verdict = None
        if method in ("ghostwalk", "learning_off", "oracle"):
            snap = backend.snapshot() if backend and method != "oracle" else g
            verdict = walk(snap, alerts, max_hops=max_hops, use_prior=(method == "ghostwalk"))
            ranked = [c for c, _ in verdict.ranking]
            conf = verdict.confidence
        elif method == "deepest":
            ranked, conf = simple.rank_deepest(g, alerts, max_hops=max_hops), None
        elif method == "pagerank":
            ranked, conf = simple.rank_pagerank(g, alerts), None
        elif method == "retrieval":
            ranked, conf = simple.rank_retrieval(g, alerts, history), None
        else:
            ranked, conf = simple.rank_random(g, alerts, rng), None
        rank = ranked.index(truth) + 1 if truth in ranked else None
        rows.append({"company": co["name"], "family": co["family"], "seq": inc["seq"], "truth": truth,
                     "top": ranked[0] if ranked else None, "rank": rank, "confidence": conf,
                     "repeat": any(h["root"] == truth for h in history), "graph_seq": g.seq})
        # learning happens only after the prediction, from this incident's postmortem
        if method == "ghostwalk":
            pm = placebo_pm(co, inc, rng) if placebo else inc["postmortem"]
            ops = update.propose(snap if backend else g, pm, verdict, alerts, inc["seq"], steps)
            backend.apply(ops) if backend else update.apply(g, ops)
        elif method == "retrieval":
            pass
        history.append({"alerts": alerts, "postmortem": inc["postmortem"], "root": truth})
    return rows


def acc(rows, k=1):
    return sum(1 for r in rows if r["rank"] is not None and r["rank"] <= k) / max(1, len(rows))
