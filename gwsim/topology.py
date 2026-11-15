"""Topology families for gwsim.

Every generator returns (components, edges):
  components: list of dicts {id, name, kind, tier}
  edges:      list of dicts {u, v, w}  meaning  u DEPENDS_ON v, and a failure of v
              reaches u with probability w (the true propagation weight).
Tiers: 0 gateway, 1 api, 2 domain service, 3 shared infrastructure.
"""
from __future__ import annotations
import numpy as np

GATEWAYS = ["edge-gateway", "web-bff", "mobile-bff", "partner-gateway"]
APIS = ["checkout-api", "orders-api", "search-api", "account-api", "catalog-api", "payments-api",
        "shipping-api", "reviews-api", "inventory-api", "notify-api", "pricing-api", "promo-api",
        "support-api", "media-api", "loyalty-api", "admin-api", "reports-api", "auth-api",
        "booking-api", "feeds-api", "export-api", "geo-api"]
NOUNS = ["cart", "order", "payment", "fraud", "ledger", "user", "session", "recommend", "catalog",
         "inventory", "shipping", "tax", "email", "sms", "loyalty", "coupon", "search", "media",
         "geo", "billing", "invoice", "refund", "rating", "feed", "audit", "report", "export",
         "pricing", "quote", "warehouse", "profile", "wishlist", "returns", "label", "tracking",
         "consent", "kyc", "payout", "dispute", "fx", "subscription", "trial", "seat", "license",
         "webhook", "scheduler", "importer", "thumbnail", "transcode", "chat", "presence",
         "moderation", "ranking", "ads", "bidding", "attribution", "experiment", "survey"]
INFRA = [  # (name, kind, hubness)
    ("auth-svc", "shared", 3.0), ("config-svc", "shared", 2.5), ("redis-sessions", "cache", 2.5),
    ("feature-flags", "shared", 2.0), ("dns-internal", "shared", 2.0), ("kafka-events", "queue", 2.0),
    ("secrets-vault", "shared", 1.5), ("rate-limiter", "shared", 1.2), ("service-mesh", "shared", 1.5),
    ("orders-db", "datastore", 1.2), ("users-db", "datastore", 1.2), ("payments-db", "datastore", 1.0),
    ("catalog-db", "datastore", 1.0), ("inventory-db", "datastore", 1.0), ("ledger-db", "datastore", 0.8),
    ("redis-cart", "cache", 1.0), ("redis-catalog", "cache", 1.0), ("memcache-feed", "cache", 0.8),
    ("rabbit-orders", "queue", 0.8), ("sqs-email", "queue", 0.7), ("analytics-db", "datastore", 0.6),
    ("stripe-api", "external", 0.6), ("twilio-api", "external", 0.5), ("maps-api", "external", 0.5),
    ("s3-media", "external", 0.6), ("search-index", "datastore", 0.8), ("redis-ratelimit", "cache", 0.7),
]
STRONG = {"datastore", "cache", "shared"}


def _weight(rng, kind_of_target: str) -> float:
    lo, hi = (0.55, 0.95) if kind_of_target in STRONG else (0.35, 0.8)
    return float(np.round(rng.uniform(lo, hi), 3))


def _pick(rng, pool_ids, weights, k):
    k = min(k, len(pool_ids))
    p = np.asarray(weights, dtype=float)
    p = p / p.sum()
    return list(rng.choice(pool_ids, size=k, replace=False, p=p))


def _extend(pool, need):
    """Beyond the built-in name pools (only for the scale benchmark, n > 120): repeat the pool with numeric suffixes."""
    out = list(pool)
    k = 2
    while len(out) < need:
        out += [(f"{x[0]}-{k}", *x[1:]) if isinstance(x, tuple) else f"{x}-{k}" for x in pool]
        k += 1
    return out[:need]


def generate(family: str, n: int, rng: np.random.Generator):
    """family: 'layered' or 'hub'. n = total components (30..120)."""
    hub_power = 1.0 if family == "layered" else 2.2
    n_gw, n_api = 2, max(3, round(0.16 * n))
    big = n > 120                                   # the 30-120 service benchmark path is untouched
    APIS_L = _extend(APIS, n_api) if big else APIS
    INFRA_L = _extend(INFRA, round(0.28 * n)) if big else INFRA
    n_infra = max(8, min(len(INFRA_L), round(0.28 * n)))
    n_dom = max(5, n - n_gw - n_api - n_infra)
    comps, edges = [], []

    def add(name, kind, tier):
        comps.append({"id": len(comps), "name": name, "kind": kind, "tier": tier})
        return len(comps) - 1

    gws = [add(nm, "service", 0) for nm in GATEWAYS[:n_gw]]
    apis = [add(nm, "service", 1) for nm in rng.permutation(APIS_L)[:n_api]]
    nouns = list(rng.permutation(NOUNS))
    doms = [add(f"{nouns[i % len(nouns)]}-svc" + ("" if i < len(nouns) else f"-{i // len(nouns) + 1}"),
                "service", 2) for i in range(n_dom)]
    infra_sorted = sorted(INFRA_L, key=lambda t: -t[2])
    chosen = infra_sorted[:6] + list(rng.permutation(np.array(infra_sorted[6:], dtype=object))[: n_infra - 6])
    infra = [add(nm, kind, 3) for nm, kind, _ in chosen]
    hub = {c: float(h) ** hub_power for c, (_, _, h) in zip(infra, chosen)}
    kind = {c["id"]: c["kind"] for c in comps}
    seen = set()

    def link(u, v):
        if u != v and (u, v) not in seen:
            seen.add((u, v))
            edges.append({"u": int(u), "v": int(v), "w": _weight(rng, kind[v])})

    for a in apis:  # every API behind >= 1 gateway
        for g in gws:
            if rng.random() < 0.7:
                link(g, a)
        if not any(e["v"] == a and e["u"] in gws for e in edges):
            link(gws[0], a)
    indeg = {d: 1.0 for d in doms}
    for a in apis:
        for d in _pick(rng, doms, [indeg[d] for d in doms], int(rng.integers(1, 4))):
            link(a, d); indeg[d] += 1
    for i, d in enumerate(doms):
        lower = doms[i + 1:]
        if lower and rng.random() < 0.55:
            for d2 in _pick(rng, lower, [indeg[x] for x in lower], int(rng.integers(1, 3))):
                link(d, d2); indeg[d2] += 1
        for inf in _pick(rng, infra, [hub[x] for x in infra], int(rng.integers(1, 4))):
            link(d, inf)
    for a in apis:  # APIs talk to auth / rate limiting directly
        for inf in _pick(rng, infra, [hub[x] for x in infra], int(rng.integers(0, 2)) + 1):
            link(a, inf)
    return comps, edges


# Real open-source microservice systems (call graphs from their public source).
REAL = {
    "online-boutique": {
        "components": [("frontend", "service", 0), ("checkoutservice", "service", 1),
                       ("recommendationservice", "service", 2), ("cartservice", "service", 2),
                       ("productcatalogservice", "service", 2), ("currencyservice", "service", 2),
                       ("shippingservice", "service", 2), ("paymentservice", "service", 2),
                       ("emailservice", "service", 2), ("adservice", "service", 2),
                       ("redis-cart", "cache", 3)],
        "edges": [("frontend", "checkoutservice"), ("frontend", "recommendationservice"),
                  ("frontend", "cartservice"), ("frontend", "productcatalogservice"),
                  ("frontend", "currencyservice"), ("frontend", "shippingservice"),
                  ("frontend", "adservice"), ("checkoutservice", "productcatalogservice"),
                  ("checkoutservice", "shippingservice"), ("checkoutservice", "currencyservice"),
                  ("checkoutservice", "cartservice"), ("checkoutservice", "paymentservice"),
                  ("checkoutservice", "emailservice"), ("recommendationservice", "productcatalogservice"),
                  ("cartservice", "redis-cart")],
    },
    "sock-shop": {
        "components": [("front-end", "service", 0), ("orders", "service", 1), ("catalogue", "service", 2),
                       ("carts", "service", 2), ("user", "service", 2), ("payment", "service", 2),
                       ("shipping", "service", 2), ("queue-master", "service", 2),
                       ("catalogue-db", "datastore", 3), ("carts-db", "datastore", 3),
                       ("orders-db", "datastore", 3), ("user-db", "datastore", 3),
                       ("rabbitmq", "queue", 3)],
        "edges": [("front-end", "catalogue"), ("front-end", "carts"), ("front-end", "orders"),
                  ("front-end", "user"), ("orders", "carts"), ("orders", "user"), ("orders", "payment"),
                  ("orders", "shipping"), ("orders", "orders-db"), ("catalogue", "catalogue-db"),
                  ("carts", "carts-db"), ("user", "user-db"), ("shipping", "rabbitmq"),
                  ("queue-master", "rabbitmq")],
    },
}


def real_system(name: str, rng: np.random.Generator):
    spec = REAL[name]
    comps = [{"id": i, "name": nm, "kind": k, "tier": t} for i, (nm, k, t) in enumerate(spec["components"])]
    idx = {c["name"]: c["id"] for c in comps}
    kind = {c["id"]: c["kind"] for c in comps}
    edges = [{"u": idx[a], "v": idx[b], "w": _weight(rng, kind[idx[b]])} for a, b in spec["edges"]]
    return comps, edges
