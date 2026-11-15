"""In-memory graph state. HydraGraph (hydra.py) produces the same object from HydraDB,
so the engine and learner are backend-agnostic and a parity test can compare them."""
from __future__ import annotations
import math
from dataclasses import dataclass, field

W0_OFFICIAL = 0.7       # prior weight for every edge on the official map
W_TENTATIVE = 0.35      # a learned edge seen once
W_CONFIRMED = 0.7       # a learned edge seen twice


@dataclass
class Edge:
    w: float
    origin: str = "official"      # official | learned
    confirmations: int = 0
    learned_from: int = -1
    created_seq: int = -1

    @property
    def cost(self):
        return -math.log(max(self.w, 1e-9))


@dataclass
class GraphState:
    components: dict                     # id -> {name, kind, tier}
    edges: dict = field(default_factory=dict)          # (u, v) -> Edge
    names: dict = field(default_factory=dict)          # name or alias -> id
    root_counts: dict = field(default_factory=dict)    # id -> times confirmed root
    shortcuts: dict = field(default_factory=dict)      # (entry, root) -> count
    affected: dict = field(default_factory=dict)       # id -> times on a causal chain
    missed: dict = field(default_factory=dict)         # id -> times it stayed silent while on a chain
    seq: int = 0

    @classmethod
    def from_official(cls, view):
        comps = {c["id"]: {"name": c["name"], "kind": c["kind"], "tier": c["tier"]} for c in view["components"]}
        g = cls(components=comps)
        g.names = {c["name"]: i for i, c in comps.items()}
        for e in view["edges"]:
            g.edges[(e["u"], e["v"])] = Edge(W0_OFFICIAL)
        return g

    @classmethod
    def from_truth(cls, co):
        comps = {c["id"]: {"name": c["name"], "kind": c["kind"], "tier": c["tier"]} for c in co["components"]}
        g = cls(components=comps)
        g.names = {c["name"]: i for i, c in comps.items()}
        for cid, al in co["aliases"].items():
            for a in al:
                g.names[a] = int(cid)
        for e in co["true_edges"]:
            g.edges[(e["u"], e["v"])] = Edge(e["w"])
        return g

    def out_adj(self):
        adj = {}
        for (u, v), e in self.edges.items():
            adj.setdefault(u, []).append((v, e.w))
        return adj

    def in_adj(self):
        adj = {}
        for (u, v), e in self.edges.items():
            adj.setdefault(v, []).append((u, e.w))
        return adj

    def miss_rate(self, cid, prior=0.15, strength=10.0):
        return (self.missed.get(cid, 0) + prior * strength) / (self.affected.get(cid, 0) + strength)
