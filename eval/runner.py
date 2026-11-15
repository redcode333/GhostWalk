"""Online evaluation: predict incident i on the graph after postmortems 1..i-1."""
from __future__ import annotations
import json, pathlib, random, time, zlib
from gwsim.world import official_view
from ghostwalk.graph.state import GraphState
from ghostwalk.engine.walk import walk, changes_before
from ghostwalk.learn import update
from baselines import simple

CHANGES_TUNED = pathlib.Path(__file__).with_name("changes_tuned.json")
METHODS = ["ghostwalk", "learning_off", "oracle", "deepest", "pagerank", "retrieval", "random"]
TUNED = pathlib.Path(__file__).with_name("pagerank_tuned.json")


def load(split, root="data"):
    return [json.loads(p.read_text()) for p in sorted(pathlib.Path(root, split).glob("*.json"))]


class _View:  # adapter so official_view works on the loaded dict
    def __init__(self, d):
        self.components, self.official_edges = d["components"], d["official_edges"]


def pagerank_settings():
    """DEV-tuned personalized-PageRank settings (eval/tune_pagerank.py). Falls back to the textbook default."""
    if TUNED.exists():
        return json.loads(TUNED.read_text())["chosen"]
    return dict(simple.PR_DEFAULT)


def changes_settings():
    """DEV-tuned (gamma, tau) for --use-changes. gamma=0 when change evidence did not beat the engine on DEV."""
    if CHANGES_TUNED.exists():
        c = json.loads(CHANGES_TUNED.read_text())["chosen"]
        return c["gamma"], c["tau"]
    return 0.0, 15.0


def placebo_pm(co, inc, rng):
    """Control: a postmortem with a random root and random edges. Same shape, no information."""
    ids = [c["id"] for c in co["components"]]
    root = rng.choice(ids)
    chain = [[rng.choice(ids), rng.choice(ids)] for _ in inc["postmortem"]["chain"]]
    return {"root": root, "chain": [e for e in chain if e[0] != e[1]], "aliases": [], "correct": False}


def run_company(co, method, max_hops=5, steps=update.ALL_STEPS, placebo=False, seed=0, backend=None, trace=None,
                pr=None, snap_every=10, use_changes=False, gamma=None, tau=None):
    """Returns per-incident rows: seq, truth, rank of truth (1-based, None if absent), top, confidence, latency.

    backend: object with fresh(co) / snapshot() / apply(ops) (HydraGraph and the eval/stores.py stores).
             Optional attributes: max_hops (query depth the store supports), reach (store-side reachability).
    trace:   dict filled with rankings, per-incident ops and learned-edge snapshots (every `snap_every`)."""
    rng = random.Random(seed * 7919 + zlib.crc32(co["name"].encode()) % 10007)
    if method == "oracle":
        g = GraphState.from_truth(co)
    else:
        g = backend.fresh(co) if backend else GraphState.from_official(official_view(_View(co)))
    if backend is not None:
        max_hops = min(max_hops, getattr(backend, "max_hops", max_hops))
    reach = getattr(backend, "reach", None) if backend is not None else None
    pr = pr or pagerank_settings()
    rows, history, seen_pairs = [], [], set()
    if trace is not None:
        trace.update(rankings=[], ops=[], snaps=[])
    for inc in co["incidents"]:
        alerts, truth = inc["alerts"], inc["root"]
        verdict = None
        t0 = time.perf_counter()
        if method in ("ghostwalk", "learning_off", "oracle"):
            snap = backend.snapshot() if backend and method != "oracle" else g
            ch = changes_before(snap, inc.get("changes"), min(a["t"] for a in alerts)) if use_changes and alerts else None
            verdict = walk(snap, alerts, max_hops=max_hops, use_prior=(method == "ghostwalk"), reach=reach, changes=ch, gamma=gamma, tau=tau)
            ranked = [c for c, _ in verdict.ranking]
            conf = verdict.confidence
            if trace is not None:
                trace["rankings"].append(verdict.ranking)
        elif method == "deepest":
            ranked, conf = simple.rank_deepest(g, alerts, max_hops=max_hops), None
        elif method == "pagerank":
            ranked, conf = simple.rank_pagerank(g, alerts, **pr), None
        elif method == "retrieval":
            ranked, conf = simple.rank_retrieval(g, alerts, history), None
        else:
            ranked, conf = simple.rank_random(g, alerts, rng), None
        ms = (time.perf_counter() - t0) * 1000
        rank = ranked.index(truth) + 1 if truth in ranked else None
        pair = (truth, inc["entry"])          # the root -> alert path of this incident
        rows.append({"company": co["name"], "family": co["family"], "seq": inc["seq"], "truth": truth,
                     "top": ranked[0] if ranked else None, "rank": rank, "n_ranked": len(ranked),
                     "confidence": conf, "ms": ms,
                     "repeat": any(h["root"] == truth for h in history),
                     "repeat_path": pair in seen_pairs,
                     "graph_seq": (snap if verdict is not None else g).seq})
        seen_pairs.add(pair)
        # learning happens only after the prediction, from this incident's postmortem
        if method == "ghostwalk":
            pm = placebo_pm(co, inc, rng) if placebo else inc["postmortem"]
            ops = update.propose(snap if backend else g, pm, verdict, alerts, inc["seq"], steps)
            backend.apply(ops) if backend else update.apply(g, ops)
            if trace is not None:
                trace["ops"].append(ops)
                if (inc["seq"] + 1) % snap_every == 0:
                    cur = backend.snapshot() if backend else g
                    trace["snaps"].append({"after": inc["seq"] + 1,
                                           "learned": {k: e.w for k, e in cur.edges.items() if e.origin == "learned"}})
        history.append({"alerts": alerts, "postmortem": inc["postmortem"], "root": truth})
    if trace is not None:  # final graph state (read back from the backend when there is one)
        trace["final"] = backend.snapshot() if backend and method in ("ghostwalk", "learning_off") else g
    return rows


def acc(rows, k=1):
    return sum(1 for r in rows if r["rank"] is not None and r["rank"] <= k) / max(1, len(rows))
