"""Baselines B0 (random), B1 (deepest alerting service), B2 (personalized PageRank, MicroRCA-style),
B3 (retrieval over past postmortems). Each exposes rank(g, alerts, history) -> [component ids]."""
from __future__ import annotations
import math, random
import numpy as np
from collections import Counter
from ghostwalk.engine.walk import resolve, _limited_best


def rank_random(g, alerts, rng: random.Random, **_):
    A, _, _ = resolve(g, alerts)
    xs = list(A)
    rng.shuffle(xs)
    return xs


def rank_deepest(g, alerts, max_hops=5, **_):
    """Textbook rule: an alerting service none of whose (official) dependencies is alerting,
    preferring deeper tiers, then the earliest onset."""
    A, _, onset = resolve(g, alerts)
    out_adj = g.out_adj()
    def has_alerting_dep(v):
        best, _ = _limited_best(out_adj, v, max_hops)
        return any(x in A and x != v for x in best)
    return sorted(A, key=lambda v: (has_alerting_dep(v), -g.components[v]["tier"], onset[v]))


# Tunable settings (fitted on DEV only, see eval/tune_pagerank.py -> eval/pagerank_tuned.json)
PR_DEFAULT = {"restart": 0.15, "direction": "dep", "weighted": True, "onset": False}
_PR_CACHE: dict = {}


def _pr_matrix(g, direction, weighted):
    """Row-stochastic transition matrix. direction: 'dep' (service -> what it depends on),
    'rev' (dependency -> its dependents) or 'both'. Dangling nodes keep their mass (self loop)."""
    key = (id(g), direction, weighted, len(g.edges))
    hit = _PR_CACHE.get(key)
    if hit is not None and hit[0] is g:      # the graph object is pinned in the cache, so its id cannot be reused
        return hit[1:]
    ids = sorted(g.components)
    ix = {c: i for i, c in enumerate(ids)}
    M = np.zeros((len(ids), len(ids)))
    for (u, v), e in g.edges.items():
        w = e.w if weighted else 1.0
        if direction in ("dep", "both"):
            M[ix[u], ix[v]] += w
        if direction in ("rev", "both"):
            M[ix[v], ix[u]] += w
    tot = M.sum(1)
    for i in range(len(ids)):
        if tot[i] == 0:
            M[i, i] = 1.0
        else:
            M[i] /= tot[i]
    if len(_PR_CACHE) > 64:
        _PR_CACHE.clear()
    _PR_CACHE[key] = (g, ids, ix, M)
    return ids, ix, M


def rank_pagerank(g, alerts, restart=None, direction=None, weighted=None, onset=None, iters=60, **_):
    """Personalized PageRank (MicroRCA-style): the walker restarts at alerting services.
    Settings: restart probability, edge direction, edge weighting, and whether the restart
    mass favours earlier alerts. The score is the stationary mass; ties break to the earliest alert."""
    cfg = {**PR_DEFAULT, **{k: v for k, v in (("restart", restart), ("direction", direction),
                                               ("weighted", weighted), ("onset", onset)) if v is not None}}
    A, _, t = resolve(g, alerts)
    if not A:
        return []
    ids, ix, M = _pr_matrix(g, cfg["direction"], cfg["weighted"])
    p = np.zeros(len(ids))
    if cfg["onset"]:
        t0 = min(t.values())
        for v in A:
            p[ix[v]] = 1.0 / (1.0 + (t[v] - t0) / 30.0)
    else:
        for v in A:
            p[ix[v]] = 1.0
    p /= p.sum()
    pr = p.copy()
    for _ in range(iters):
        pr = cfg["restart"] * p + (1 - cfg["restart"]) * (pr @ M)
    order = sorted(range(len(ids)), key=lambda i: (-round(pr[i], 12), t.get(ids[i], 1e9)))
    return [ids[i] for i in order]


def _tokens(alerts):
    return Counter(f"{a['name']}|{a['signal']}" for a in alerts) + Counter(a["name"] for a in alerts)


def rank_retrieval(g, alerts, history, k=5, **_):
    """B3: vector retrieval. TF-IDF vectors of alert sets, cosine top-k past incidents,
    vote with their postmortem roots. Falls back to alerting services when history is empty."""
    q = _tokens(alerts)
    if not history:
        return rank_deepest(g, alerts)
    df = Counter()
    for h in history:
        df.update(set(_tokens(h["alerts"])))
    n = len(history)
    idf = lambda t: math.log((1 + n) / (1 + df[t])) + 1
    def vec(c):
        return {t: c[t] * idf(t) for t in c}
    qv = vec(q)
    qn = math.sqrt(sum(x * x for x in qv.values())) or 1
    sims = []
    for h in history:
        hv = vec(_tokens(h["alerts"]))
        dot = sum(qv.get(t, 0) * x for t, x in hv.items())
        hn = math.sqrt(sum(x * x for x in hv.values())) or 1
        sims.append((dot / (qn * hn), h["postmortem"]["root"]))
    sims.sort(key=lambda t: -t[0])
    votes = Counter()
    for s, r in sims[:k]:
        votes[r] += s
    ranked = [r for r, _ in votes.most_common()]
    rest = [c for c in rank_deepest(g, alerts) if c not in ranked]
    return ranked + rest
