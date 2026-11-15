"""Real storage backends behind the same interface the runner uses:

    fresh(co) -> GraphState      load the OFFICIAL view of one company
    snapshot() -> GraphState     read the current graph back from the store (nothing cached in Python)
    apply(ops)                   write the learner's diff ops
    max_hops (optional)          deepest traversal the store can answer
    reach(v, 'out'|'in', h)      (optional) store-side reachability; the engine uses it instead of its own search

KVGraph        Redis. Only 1-hop adjacency lookups (a hash per node), so the engine is limited to max_hops=1.
PgCteGraph     Postgres. Edges in a table, multi-hop reach computed by a recursive CTE.
PgVectorStore  Postgres + pgvector. No graph: postmortem text is embedded and the nearest past postmortem names the root.
The in-memory graph (runner without a backend) is the reference.
"""
from __future__ import annotations
import hashlib, json, re, time, types
from collections import Counter
import numpy as np
from gwsim.world import official_view
from ghostwalk.graph.state import GraphState, Edge
from baselines import simple


def _official(co):
    return GraphState.from_official(official_view(types.SimpleNamespace(components=co["components"], official_edges=co["official_edges"])))


# ---------------------------------------------------------------------------------------------- Redis
class KVGraph:
    """Key-value store: `comp` hash, `names` hash, one `adj:<u>` hash per node (field v -> edge json). Nothing richer than
    GET/HSET/HGETALL, so the best the engine can do is 1-hop adjacency."""
    max_hops = 1

    def __init__(self, url="redis://127.0.0.1:6380/0", prefix="gw"):
        import redis
        self.r = redis.Redis.from_url(url, decode_responses=True)
        self.p = prefix
        self.k = None

    def _key(self, *parts):
        return ":".join([self.p, self.k, *map(str, parts)])

    def fresh(self, co):
        self.k = co["name"]
        for key in self.r.scan_iter(f"{self.p}:{self.k}:*"):
            self.r.delete(key)
        g = _official(co)
        pipe = self.r.pipeline()
        for i, c in g.components.items():
            pipe.hset(self._key("comp"), i, json.dumps(c))
            pipe.hset(self._key("names"), c["name"], i)
        for o, ((u, v), e) in enumerate(g.edges.items()):
            pipe.hset(self._key("adj", u), v, json.dumps({"w": e.w, "origin": "official", "conf": 0, "lf": -1, "cs": -1, "o": o}))
        pipe.set(self._key("eo"), len(g.edges))
        pipe.set(self._key("seq"), 0)
        pipe.execute()
        return g

    def snapshot(self):
        g = GraphState(components={})
        for i, c in sorted(self.r.hgetall(self._key("comp")).items(), key=lambda t: int(t[0])):
            g.components[int(i)] = json.loads(c)
        for name, i in self.r.hgetall(self._key("names")).items():
            g.names[name] = int(i)
        edges = []
        for key in self.r.scan_iter(self._key("adj", "*")):
            u = int(key.rsplit(":", 1)[1])
            for v, js in self.r.hgetall(key).items():
                e = json.loads(js)
                edges.append((e["o"], u, int(v), e))
        for _, u, v, e in sorted(edges, key=lambda t: t[0]):
            g.edges[(u, v)] = Edge(e["w"], e["origin"], e["conf"], e["lf"], e["cs"])
        for name, h in (("rc", g.root_counts), ("aff", g.affected), ("miss", g.missed)):
            for i, n in self.r.hgetall(self._key("cnt", name)).items():
                h[int(i)] = int(n)
        for f, n in self.r.hgetall(self._key("sc")).items():
            a, b = f.split(":")
            g.shortcuts[(int(a), int(b))] = int(n)
        g.seq = int(self.r.get(self._key("seq")) or 0)
        return g

    def _edge(self, u, v):
        js = self.r.hget(self._key("adj", u), v)
        return json.loads(js) if js else None

    def apply(self, ops):
        eo = int(self.r.get(self._key("eo")) or 0)
        for o in ops:
            k = o["op"]
            if k == "alias":
                self.r.hset(self._key("names"), o["name"], o["id"])
            elif k == "add_edge":
                prev = self._edge(o["u"], o["v"])
                ordinal = prev["o"] if prev else eo
                eo += 0 if prev else 1
                self.r.hset(self._key("adj", o["u"]), o["v"], json.dumps(
                    {"w": o["w"], "origin": "learned", "conf": 1, "lf": o["seq"], "cs": o["seq"], "o": ordinal}))
            elif k in ("confirm", "reweight"):
                e = self._edge(o["u"], o["v"])
                e["w"] = o["w"]
                if k == "confirm":
                    e["conf"] += 1
                self.r.hset(self._key("adj", o["u"]), o["v"], json.dumps(e))
            elif k == "drop_edge":
                self.r.hdel(self._key("adj", o["u"]), o["v"])
            elif k == "root":
                self.r.hincrby(self._key("cnt", "rc"), o["id"], 1)
            elif k == "shortcut":
                self.r.hincrby(self._key("sc"), f"{o['entry']}:{o['root']}", 1)
            elif k == "observe":
                self.r.hincrby(self._key("cnt", "aff"), o["id"], 1)
                if o["silent"]:
                    self.r.hincrby(self._key("cnt", "miss"), o["id"], 1)
        self.r.set(self._key("eo"), eo)
        self.r.incr(self._key("seq"))


# ---------------------------------------------------------------------------------------------- Postgres
SCHEMA = [
    "CREATE TABLE IF NOT EXISTS gw_comp (co text, id int, name text, kind text, tier int, rc int DEFAULT 0, aff int DEFAULT 0, miss int DEFAULT 0, PRIMARY KEY (co, id))",
    "CREATE TABLE IF NOT EXISTS gw_alias (co text, name text, id int, PRIMARY KEY (co, name))",
    "CREATE TABLE IF NOT EXISTS gw_edge (co text, u int, v int, w double precision, origin text, conf int, lf int, cs int, o int, PRIMARY KEY (co, u, v))",
    "CREATE INDEX IF NOT EXISTS gw_edge_v ON gw_edge (co, v)",
    "CREATE TABLE IF NOT EXISTS gw_shortcut (co text, u int, v int, n int, PRIMARY KEY (co, u, v))",
    "CREATE TABLE IF NOT EXISTS gw_meta (co text PRIMARY KEY, seq int, eo int)",
]

REACH_SQL = """
WITH RECURSIVE r(node, p, depth, path) AS (
  SELECT %(src)s::int, 1.0::double precision, 0, ARRAY[%(src)s::int]
  UNION ALL
  SELECT e.{to}, r.p * e.w, r.depth + 1, r.path || e.{to}
  FROM r JOIN gw_edge e ON e.co = %(co)s AND e.{frm} = r.node
  WHERE r.depth < %(h)s AND NOT (e.{to} = ANY (r.path))
)
SELECT node, max(p) FROM r GROUP BY node
"""


def _connect(url):
    import psycopg
    return psycopg.connect(url, autocommit=True)


class PgCteGraph:
    """Postgres tables + recursive-CTE reachability: the engine's q(c, v) comes straight from SQL."""
    max_hops = 5

    def __init__(self, url="postgresql://gw:gw@127.0.0.1:5433/gw"):
        self.db = _connect(url)
        for stmt in SCHEMA:
            self.db.execute(stmt)
        self.k = None

    def fresh(self, co):
        self.k = co["name"]
        for t in ("gw_comp", "gw_alias", "gw_edge", "gw_shortcut", "gw_meta"):
            self.db.execute(f"DELETE FROM {t} WHERE co = %s", (self.k,))
        g = _official(co)
        with self.db.cursor() as cur:
            cur.executemany("INSERT INTO gw_comp (co,id,name,kind,tier) VALUES (%s,%s,%s,%s,%s)",
                            [(self.k, i, c["name"], c["kind"], c["tier"]) for i, c in g.components.items()])
            cur.executemany("INSERT INTO gw_edge VALUES (%s,%s,%s,%s,'official',0,-1,-1,%s)",
                            [(self.k, u, v, e.w, o) for o, ((u, v), e) in enumerate(g.edges.items())])
            cur.execute("INSERT INTO gw_meta VALUES (%s,0,%s)", (self.k, len(g.edges)))
        return g

    def snapshot(self):
        g = GraphState(components={})
        c = self.db.execute
        for i, name, kind, tier, rc, aff, miss in c("SELECT id,name,kind,tier,rc,aff,miss FROM gw_comp WHERE co=%s ORDER BY id", (self.k,)):
            g.components[i] = {"name": name, "kind": kind, "tier": tier}
            g.names[name] = i
            if rc:
                g.root_counts[i] = rc
            if aff:
                g.affected[i] = aff
            if miss:
                g.missed[i] = miss
        for u, v, w, origin, conf, lf, cs in c("SELECT u,v,w,origin,conf,lf,cs FROM gw_edge WHERE co=%s ORDER BY o", (self.k,)):
            g.edges[(u, v)] = Edge(w, origin, conf, lf, cs)
        for name, i in c("SELECT name,id FROM gw_alias WHERE co=%s", (self.k,)):
            g.names[name] = i
        for u, v, n in c("SELECT u,v,n FROM gw_shortcut WHERE co=%s", (self.k,)):
            g.shortcuts[(u, v)] = n
        g.seq = c("SELECT seq FROM gw_meta WHERE co=%s", (self.k,)).fetchone()[0]
        return g

    def reach(self, v, direction, h):
        frm, to = ("u", "v") if direction == "out" else ("v", "u")
        rows = self.db.execute(REACH_SQL.format(frm=frm, to=to), {"src": v, "co": self.k, "h": h}).fetchall()
        return {n: p for n, p in rows}, {}

    def apply(self, ops):
        x, k = self.db.execute, self.k
        eo = x("SELECT eo FROM gw_meta WHERE co=%s", (k,)).fetchone()[0]
        for o in ops:
            op = o["op"]
            if op == "alias":
                x("INSERT INTO gw_alias VALUES (%s,%s,%s) ON CONFLICT DO NOTHING", (k, o["name"], o["id"]))
            elif op == "add_edge":
                prev = x("SELECT o FROM gw_edge WHERE co=%s AND u=%s AND v=%s", (k, o["u"], o["v"])).fetchone()
                ordinal = prev[0] if prev else eo
                eo += 0 if prev else 1
                x("INSERT INTO gw_edge VALUES (%s,%s,%s,%s,'learned',1,%s,%s,%s) ON CONFLICT (co,u,v) DO UPDATE "
                  "SET w=EXCLUDED.w, origin='learned', conf=1, lf=EXCLUDED.lf, cs=EXCLUDED.cs",
                  (k, o["u"], o["v"], o["w"], o["seq"], o["seq"], ordinal))
            elif op == "confirm":
                x("UPDATE gw_edge SET w=%s, conf=conf+1 WHERE co=%s AND u=%s AND v=%s", (o["w"], k, o["u"], o["v"]))
            elif op == "reweight":
                x("UPDATE gw_edge SET w=%s WHERE co=%s AND u=%s AND v=%s", (o["w"], k, o["u"], o["v"]))
            elif op == "drop_edge":
                x("DELETE FROM gw_edge WHERE co=%s AND u=%s AND v=%s", (k, o["u"], o["v"]))
            elif op == "root":
                x("UPDATE gw_comp SET rc=rc+1 WHERE co=%s AND id=%s", (k, o["id"]))
            elif op == "shortcut":
                x("INSERT INTO gw_shortcut VALUES (%s,%s,%s,1) ON CONFLICT (co,u,v) DO UPDATE SET n=gw_shortcut.n+1",
                  (k, o["entry"], o["root"]))
            elif op == "observe":
                x("UPDATE gw_comp SET aff=aff+1, miss=miss+%s WHERE co=%s AND id=%s", (1 if o["silent"] else 0, k, o["id"]))
        x("UPDATE gw_meta SET seq=seq+1, eo=%s WHERE co=%s", (eo, k))


# ---------------------------------------------------------------------------------------------- pgvector
DIM = 512
_TOK = re.compile(r"[A-Za-z0-9_-]+")


def embed(text, dim=DIM):
    """Feature-hashing bag-of-words embedding (no model download, deterministic, L2-normalised)."""
    v = np.zeros(dim)
    for tok in _TOK.findall(text.lower()):
        h = int.from_bytes(hashlib.blake2b(tok.encode(), digest_size=8).digest(), "big")
        v[h % dim] += 1.0 if (h >> 63) & 1 else -1.0
        v[(h >> 20) % dim] += 0.5
    n = np.linalg.norm(v)
    return v / n if n else v


def _vec(a):
    return "[" + ",".join(f"{x:.6f}" for x in a) + "]"


class PgVectorStore:
    """Retrieval store: embed each past postmortem's text, answer a new incident with the roots of the nearest ones."""

    def __init__(self, url="postgresql://gw:gw@127.0.0.1:5433/gw", k=5):
        self.db = _connect(url)
        self.db.execute("CREATE EXTENSION IF NOT EXISTS vector")
        self.db.execute(f"CREATE TABLE IF NOT EXISTS gw_pm (co text, seq int, root int, body text, emb vector({DIM}))")
        self.k, self.co, self.g = k, None, None

    def fresh(self, co):
        self.co = co["name"]
        self.db.execute("DELETE FROM gw_pm WHERE co=%s", (self.co,))
        self.g = _official(co)

    def diagnose(self, alerts):
        q = _vec(embed("alerts: " + " ".join(a["name"] for a in alerts)))
        rows = self.db.execute("SELECT root, 1 - (emb <=> %s::vector) FROM gw_pm WHERE co=%s ORDER BY emb <=> %s::vector LIMIT %s",
                               (q, self.co, q, self.k)).fetchall()
        votes = Counter()
        for root, sim in rows:
            votes[root] += max(sim, 0.0)
        ranked = [r for r, _ in votes.most_common()]
        return ranked + [c for c in simple.rank_deepest(self.g, alerts) if c not in ranked]

    def learn(self, inc):
        body = inc["postmortem_text"]
        self.db.execute("INSERT INTO gw_pm VALUES (%s,%s,%s,%s,%s::vector)",
                        (self.co, inc["seq"], inc["postmortem"]["root"], body, _vec(embed(body))))


def run_vector_company(co, store: PgVectorStore):
    store.fresh(co)
    rows, seen = [], set()
    for inc in co["incidents"]:
        t0 = time.perf_counter()
        ranked = store.diagnose(inc["alerts"])
        ms = (time.perf_counter() - t0) * 1000
        truth = inc["root"]
        rank = ranked.index(truth) + 1 if truth in ranked else None
        pair = (truth, inc["entry"])
        rows.append({"company": co["name"], "family": co["family"], "seq": inc["seq"], "truth": truth,
                     "top": ranked[0] if ranked else None, "rank": rank, "n_ranked": len(ranked), "confidence": None,
                     "ms": ms, "repeat": False, "repeat_path": pair in seen, "graph_seq": 0})
        seen.add(pair)
        store.learn(inc)
    return rows
