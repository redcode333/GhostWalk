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
GAMMA = 0.0        # weight of change evidence (--use-changes); fitted on dev by eval/tune_changes.py, 0 = off
TAU = 15.0         # minutes: a change this long before the first alert counts 1/e as much


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


def walk(g, alerts, max_hops=5, eps=None, use_prior=True, reach=None, changes=None, gamma=None, tau=None):
    """reach(node, 'out'|'in', max_hops) -> (best, prev) lets a store answer the reachability itself
    (e.g. a Postgres recursive CTE); the default is the in-process limited Bellman-Ford."""
    eps = EPS if eps is None else eps
    gamma = GAMMA if gamma is None else gamma
    tau = TAU if tau is None else tau
    A, unresolved, onset = resolve(g, alerts)
    if not A:
        return Verdict([], 0.0, [], None, unresolved, 0)
    out_adj, in_adj = g.out_adj(), g.in_adj()
    if reach is None:
        reach = lambda v, d, h: _limited_best(out_adj if d == "out" else in_adj, v, h)
    keep_memo = {}
    def keep(v):                       # 1 - miss rate: looked up for every (candidate, service) pair, so memoised per verdict
        k = keep_memo.get(v)
        if k is None:
            k = keep_memo[v] = 1.0 - g.miss_rate(v)
        return k
    down = {v: reach(v, "out", max_hops) for v in A}     # reach from each alerting service
    cands = set(A)
    for best, _ in down.values():
        cands.update(best)
    # Constants hoisted out of the candidate loop. The maths is unchanged; the loop now walks only the services a candidate can
    # reach (up) and charges every alerting service OUTSIDE that reach the same closed-form term ln(eps), instead of visiting all of A.
    om, ln = 1.0 - eps, math.log
    ln_eps = ln(max(eps, 1e-12))
    silent_p = 1.0 - om * SILENT_ROOT
    ln_silent, ln_not_silent = ln(max(silent_p, 1e-12)), ln(max(1.0 - silent_p, 1e-12))
    l_late, l_early, l_half = ln(0.9), ln(0.1), ln(0.5)
    nA = len(A)
    scores = []
    for c in cands:
        up, _ = reach(c, "in", max_hops)                          # everything that would feel c failing
        c_alerts = c in A
        oc = onset.get(c)
        s = 0.0
        in_reach = 0
        for v, q in up.items():
            if v == c:
                continue
            pa = 1.0 - om * (1.0 - q * keep(v))
            if v in A:
                in_reach += 1
                s += ln(pa if pa > 1e-12 else 1e-12)
                if BETA and q > 0:      # failures spread in time order: dependents alert after the root
                    s += BETA * ((l_late if onset[v] >= oc else l_early) if c_alerts else l_half)
            else:
                r = 1.0 - pa
                s += LAM * ln(r if r > 1e-12 else 1e-12)
        s += ln_silent if c_alerts else LAM * ln_not_silent               # the candidate itself
        s += (nA - in_reach - (1 if c_alerts else 0)) * ln_eps           # alerting services c cannot reach (q = 0)
        if changes and gamma and c in changes:       # what changed shortly before the first alert is a likelier cause
            s += gamma * math.exp(-changes[c] / tau)
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


def tuned_changes():
    """(gamma, tau) fitted on DEV (eval/changes_tuned.json); gamma 0 when change evidence did not beat the engine on DEV."""
    import json, pathlib
    f = pathlib.Path(__file__).resolve().parents[2] / "eval" / "changes_tuned.json"
    try:
        c = json.loads(f.read_text())["chosen"]
        return float(c["gamma"]), float(c["tau"])
    except Exception:
        return 0.0, TAU


def change_note(g, change_events, root, first_ts, window_min=120):
    """'config-svc changed 1 min before the first alert (deploy #482)' for the verdict's root, or None."""
    best = None
    for ch in change_events or ():
        if g.names.get(ch["service"]) != root:
            continue
        dm = (first_ts - ch["ts"]) / 60.0
        if 0 <= dm <= window_min and (best is None or dm < best[0]):
            best = (dm, ch)
    if best is None:
        return None
    dm, ch = best
    mins = max(1, round(dm))
    ref = " ".join(x for x in (ch.get("kind"), ch.get("ref")) if x)
    return f"{g.components[root]['name']} changed {mins} min before the first alert" + (f" ({ref})" if ref else "")


def changes_before(g, change_events, first_ts):
    """{component id: minutes between its latest change and the first alert}, only changes at or before the first alert.
    change_events: [{service, ts}] with ts on the same axis as first_ts (seconds)."""
    out = {}
    for ch in change_events or ():
        cid = g.names.get(ch["service"])
        dm = (first_ts - ch["ts"]) / 60.0
        if cid is not None and dm >= 0 and dm < out.get(cid, 1e18):
            out[cid] = dm
    return out


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
