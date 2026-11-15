"""gwsim world: a company whose official service map lies, and a stream of outages.

Ground truth (true graph, roots, causal chains) is stored alongside, but methods
under evaluation only ever receive: the official map, the alerts of incident i,
and the postmortems of incidents 1..i-1.
"""
from __future__ import annotations
import json
from collections import deque
from dataclasses import dataclass, field, asdict
import numpy as np
from . import topology

TIER_ROOT_W = {0: 0.15, 1: 0.6, 2: 1.4, 3: 3.0}
SIGNALS = ["error_rate", "latency_p99", "saturation", "timeouts"]


@dataclass
class Knobs:
    hidden_frac: float = 0.20      # share of true edges missing from the official map
    alias_frac: float = 0.15       # share of components with extra names
    miss_rate: float = 0.15        # an affected service fails to alert
    silent_root: float = 0.20      # the root itself raises no alert
    spurious: float = 0.01         # per unaffected component, an unrelated alert
    monitor_blind: float = 0.05    # incident where monitoring itself is degraded
    wrong_pm: float = 0.10         # postmortem names the wrong root / drops the chain
    n_incidents: int = 60
    p_root_change: float = 0.5     # the true root had a deploy/config change in the 30 min before the first alert
    r_noise: float = 2.0           # Poisson rate of distractor changes (random non-root services) per incident
    change_jitter: float = 0.10    # share of change timestamps jittered by up to +-10 min


@dataclass
class Company:
    name: str
    family: str
    seed: int
    components: list
    true_edges: list
    official_edges: list
    hidden_edges: list
    aliases: dict                  # canonical id -> [alias names]
    incidents: list = field(default_factory=list)
    knobs: dict = field(default_factory=dict)

    def to_json(self):
        return json.dumps(asdict(self))


def _aliases_for(name, kind, rng):
    base = name.split("-")
    opts = [f"{ {'datastore': 'db', 'cache': 'cache', 'queue': 'mq', 'shared': 'core', 'external': 'ext'}.get(kind, 'svc') }-{rng.integers(1, 40):02d}",
            "-".join(reversed(base)) if len(base) > 1 else f"{name}-prod",
            f"{name}-prod", f"prod-{name}"]
    k = 1 + int(rng.random() < 0.4)
    return [str(a) for a in rng.choice(opts, size=k, replace=False) if a != name]


def build_company(name, family, seed, n=None, knobs: Knobs | None = None, real=None):
    knobs = knobs or Knobs()
    rng = np.random.default_rng(seed)
    if family == "real":
        comps, edges = topology.real_system(real, rng)
        # real call graphs plus the shared infrastructure every cluster has
        for nm, kind in (("dns-internal", "shared"), ("config-svc", "shared")):
            cid = len(comps)
            comps.append({"id": cid, "name": nm, "kind": kind, "tier": 3})
            users = [c["id"] for c in comps if c["tier"] in (1, 2) and rng.random() < 0.45]
            for u in users:
                edges.append({"u": u, "v": cid, "w": float(np.round(rng.uniform(0.55, 0.9), 3))})
    else:
        comps, edges = topology.generate(family, n, rng)
    kind = {c["id"]: c["kind"] for c in comps}

    # one circular dependency (Discord-style): a shared service that calls back into a domain service
    shared = [c["id"] for c in comps if c["kind"] == "shared"]
    users_of = {}
    for e in edges:
        users_of.setdefault(e["v"], []).append(e["u"])
    cyc = None
    for s in shared:
        cands = [u for u in users_of.get(s, []) if comps[u]["tier"] == 2]
        if cands:
            back = int(rng.choice(cands))
            cyc = {"u": s, "v": back, "w": float(np.round(rng.uniform(0.5, 0.8), 3))}
            edges.append(cyc)
            break

    # hidden edges: biased toward caches, shared infra and queues, plus the cycle
    pref = np.array([3.0 if kind[e["v"]] in ("cache", "shared", "queue") else 1.0 for e in edges])
    n_hidden = max(1, round(knobs.hidden_frac * len(edges)))
    hidden_idx = set(rng.choice(len(edges), size=min(n_hidden, len(edges)), replace=False, p=pref / pref.sum()).tolist())
    if cyc is not None:
        hidden_idx.add(len(edges) - 1)
    hidden = [edges[i] for i in sorted(hidden_idx)]
    official = [{"u": e["u"], "v": e["v"]} for i, e in enumerate(edges) if i not in hidden_idx]

    aliases = {}
    for c in comps:
        if rng.random() < knobs.alias_frac:
            aliases[c["id"]] = _aliases_for(c["name"], c["kind"], rng)

    co = Company(name, family, seed, comps, edges, official, hidden, aliases, knobs=asdict(knobs))
    co.incidents = [_incident(co, i, rng, knobs) for i in range(knobs.n_incidents)]
    for inc in co.incidents:       # change events use their OWN random stream, so every other field is identical to before they existed
        inc["changes"] = _changes(co, inc, knobs)
    return co


def _incident(co: Company, seq: int, rng, k: Knobs):
    comps = co.components
    dependents = {}
    for e in co.true_edges:
        dependents.setdefault(e["v"], []).append((e["u"], e["w"]))
    if not hasattr(co, "_fragility"):
        co._fragility = rng.lognormal(0, 0.9, size=len(comps))
    w = np.array([TIER_ROOT_W[c["tier"]] for c in comps]) * co._fragility
    while True:
        root = int(rng.choice(len(comps), p=w / w.sum()))
        onset = {root: 0.0}
        parent = {root: None}
        q = deque([root])
        while q:  # independent cascade over reverse dependencies
            x = q.popleft()
            for u, pw in dependents.get(x, []):
                if u not in onset and rng.random() < pw:
                    onset[u] = onset[x] + float(rng.uniform(5, 60))
                    parent[u] = x
                    q.append(u)
        blind = rng.random() < k.monitor_blind
        alerts = []
        for c, t in onset.items():
            p_miss = k.silent_root if c == root else k.miss_rate
            if blind:
                p_miss = max(p_miss, 0.5)
            if rng.random() >= p_miss:
                alerts.append((c, t))
        for c in range(len(comps)):
            if c not in onset and rng.random() < k.spurious:
                alerts.append((c, float(rng.uniform(0, 120))))
        affected_alerting = [c for c, _ in alerts if c in onset]
        if len(affected_alerting) >= 2 or (len(affected_alerting) >= 1 and len(onset) >= 2):
            break

    def shown_name(cid):  # monitoring sometimes uses an alias
        al = co.aliases.get(cid)
        return str(rng.choice(al)) if al and rng.random() < 0.5 else comps[cid]["name"]

    alert_rows = sorted(({"name": shown_name(c), "signal": str(rng.choice(SIGNALS)), "t": round(t, 1)}
                         for c, t in alerts), key=lambda a: a["t"])
    # causal chain: from the highest-tier alerting affected service down to the root
    entry = min(affected_alerting, key=lambda c: (comps[c]["tier"], onset[c]))
    chain, x = [], entry
    while parent.get(x) is not None:
        chain.append([x, parent[x]])
        x = parent[x]
    pm = {"root": root, "chain": chain, "correct": True,
          "aliases": [[a, cid] for cid in {root, *[c for e in chain for c in e]} for a in co.aliases.get(cid, [])]}
    if rng.random() < k.wrong_pm:  # a wrong or incomplete postmortem
        nbrs = [e["v"] for e in co.true_edges if e["u"] == root] + [u for u, _ in dependents.get(root, [])]
        pm = {"root": int(rng.choice(nbrs)) if nbrs else root, "chain": chain[:1], "correct": False, "aliases": []}
    return {"seq": seq, "alerts": alert_rows, "root": root, "affected": sorted(onset), "entry": entry,
            "chain": chain, "postmortem": pm, "postmortem_text": _pm_text(co, root, chain, pm, rng)}


def _changes(co: Company, inc: dict, k: Knobs):
    """'What changed recently': deploy/config events on the same time axis as the alerts (seconds, first alert = reference).
    The root's change is drawn with probability p_root_change independently of everything else; distractors land on random
    non-root services. Nothing marks which event is the real one. A change on an alerting-but-innocent service is a distractor."""
    rng = np.random.default_rng([co.seed, 4242, inc["seq"]])
    t0 = min(a["t"] for a in inc["alerts"])
    events = []
    if rng.random() < k.p_root_change:
        events.append((inc["root"], t0 - float(rng.uniform(60, 1800))))
    others = [c["id"] for c in co.components if c["id"] != inc["root"]]
    for _ in range(int(rng.poisson(k.r_noise))):
        events.append((int(rng.choice(others)), t0 - float(rng.uniform(0, 3600))))
    out = []
    for svc, ts in events:
        if rng.random() < k.change_jitter:
            ts += float(rng.uniform(-600, 600))
        out.append({"service": co.components[svc]["name"], "ts": round(ts, 1), "kind": str(rng.choice(["deploy", "config"])),
                    "ref": f"#{int(rng.integers(100, 999))}"})
    return sorted(out, key=lambda e: e["ts"])


def _pm_text(co, root, chain, pm, rng):
    nm = lambda c: co.components[c]["name"]
    if not chain:
        return f"{nm(pm['root'])} failed and caused the alerts. Restarted it; recovered."
    steps = "; ".join(f"{nm(u)} depends on {nm(v)}" for u, v in pm["chain"])
    opener = rng.choice(["Customers saw errors on", "Pages fired for", "Elevated 5xx on"])
    return (f"{opener} {nm(chain[0][0])}. Root cause: {nm(pm['root'])} degraded. "
            f"How it spread: {steps}. Mitigated by failing over {nm(pm['root'])}.")


def official_view(co: Company):
    """Exactly what a method is allowed to see at the start: names, kinds, the official map."""
    return {"components": [{k: c[k] for k in ("id", "name", "kind", "tier")} for c in co.components],
            "edges": co.official_edges}
