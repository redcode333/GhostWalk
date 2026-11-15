"""Baselines B0 (random), B1 (deepest alerting service), B2 (personalized PageRank, MicroRCA-style),
B3 (retrieval over past postmortems). Each exposes rank(g, alerts, history) -> [component ids]."""
from __future__ import annotations
import math, random
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


def rank_pagerank(g, alerts, alpha=0.85, iters=50, **_):
    """Personalized PageRank: the walker restarts at alerting nodes and flows from a
    service to what it depends on, so mass gathers on shared upstream causes."""
    A, _, _ = resolve(g, alerts)
    if not A:
        return []
    out_adj = g.out_adj()
    nodes = list(g.components)
    pers = {v: (1.0 / len(A) if v in A else 0.0) for v in nodes}
    pr = dict(pers)
    for _ in range(iters):
        nxt = {v: (1 - alpha) * pers[v] for v in nodes}
        for u in nodes:
            outs = out_adj.get(u, [])
            tot = sum(w for _, w in outs)
            if tot == 0:
                nxt[u] += alpha * pr[u]           # dangling: keep mass (sink = candidate root)
                continue
            for v, w in outs:
                nxt[v] += alpha * pr[u] * w / tot
        pr = nxt
    return sorted(nodes, key=lambda v: -pr[v])


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
