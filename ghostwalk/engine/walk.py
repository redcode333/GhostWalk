"""The GhostWalk root-cause engine: noisy-OR likelihood over a dependency graph.

For each candidate root c and component v, reach q(c, v) is the best product of edge
weights on a path v -> ... -> c of at most `max_hops` edges. Score:
  log P(A | r=c) = log prior(c)
     + sum_{v in A}     log[1 - (1-eps)(1 - q(c,v)(1-m_v))]
     + sum_{v not in A} log[(1-eps)(1 - q(c,v)(1-m_v))]      (over v upstream of c)
"""
from __future__ import annotations
import math
from dataclasses import dataclass, field

EPS = 0.04          # spurious-alert rate      (fitted on dev companies)
SILENT_ROOT = 0.20  # root raises no alert
PRIOR_ROOT = 0.3    # weight of past confirmed roots
PRIOR_SHORTCUT = 0.6
BETA = 0.6         # weight of onset-order evidence (fitted on dev)
LAM = 0.3          # weight of the "expected but silent" terms (fitted on dev)


@dataclass
class Verdict:
    ranking: list                   # [(component id, log score)] best first
    confidence: float
    path: list                      # [(u, v, origin)] from entry service down to the root
    entry: int | None
    unresolved: list = field(default_factory=list)
    candidates: int = 0


def _limited_best(adj, src, max_hops):
    """Best product reach from src within max_hops edges (Bellman-Ford limited to k rounds)."""
    best = {src: 1.0}
    prev = {src: None}
    frontier = {src: 1.0}
    for _ in range(max_hops):
        nxt = {}
        for x, px in frontier.items():
            for y, w in adj.get(x, ()):
                p = px * w
                if p > best.get(y, 0.0) and p > nxt.get(y, 0.0):
                    nxt[y] = p
                    prev[y] = x
        for y, p in nxt.items():
            best[y] = p
        frontier = nxt
        if not frontier:
            break
    return best, prev


def resolve(g, alerts):
    seen, unresolved, onset = set(), [], {}
    for a in alerts:
        cid = g.names.get(a["name"])
        if cid is None:
            unresolved.append(a["name"])
            continue
        if cid not in seen:
            seen.add(cid)
            onset[cid] = a["t"]
    return seen, unresolved, onset


def walk(g, alerts, max_hops=5, eps=None, use_prior=True):
    eps = EPS if eps is None else eps
    A, unresolved, onset = resolve(g, alerts)
    if not A:
        return Verdict([], 0.0, [], None, unresolved, 0)
    out_adj, in_adj = g.out_adj(), g.in_adj()
    down = {v: _limited_best(out_adj, v, max_hops) for v in A}     # reach from each alerting service
    cands = set(A)
    for best, _ in down.values():
        cands.update(best)
    scores = []
    for c in cands:
        up, _ = _limited_best(in_adj, c, max_hops)                 # everything that would feel c failing
        s = 0.0
        for v in set(up) | A:
            if v == c:
                p_alert = 1 - (1 - eps) * SILENT_ROOT
            else:
                q = up.get(v, 0.0)
                p_alert = 1 - (1 - eps) * (1 - q * (1 - g.miss_rate(v)))
            s += math.log(max(p_alert, 1e-12)) if v in A else LAM * math.log(max(1 - p_alert, 1e-12))
        if BETA:  # failures spread in time order: dependents alert after the root
            for v in A:
                if v != c and up.get(v, 0.0) > 0:
                    s += BETA * (math.log(0.9 if onset[v] >= onset[c] else 0.1) if c in A else math.log(0.5))
        if use_prior:
            s += math.log1p(PRIOR_ROOT * g.root_counts.get(c, 0))
        scores.append((c, s))
    scores.sort(key=lambda t: -t[1])
    top = scores[0][1]
    z = sum(math.exp(s - top) for _, s in scores)
    entry = min(A, key=lambda v: (g.components[v]["tier"], onset[v]))
    root = scores[0][0]
    if use_prior and g.shortcuts:  # recurring entry->root pairs nudge the ranking
        bumped = [(c, s + math.log1p(PRIOR_SHORTCUT * g.shortcuts.get((entry, c), 0))) for c, s in scores]
        bumped.sort(key=lambda t: -t[1])
        scores, root = bumped, bumped[0][0]
        top = scores[0][1]
        z = sum(math.exp(s - top) for _, s in scores)
    return Verdict(scores, 1.0 / z, explain(g, entry, root, max_hops, out_adj), entry, unresolved, len(cands))


def explain(g, entry, root, max_hops, out_adj=None):
    out_adj = out_adj or g.out_adj()
    best, prev = _limited_best(out_adj, entry, max_hops)
    if root not in best or root == entry:
        return []
    path, x = [], root
    while prev[x] is not None:
        u = prev[x]
        path.append((u, x, g.edges[(u, x)].origin))
        x = u
    return list(reversed(path))
