"""HydraDB-backed graph store. The same GraphState the in-memory backend produces is rebuilt from the live HydraDB graph on every
snapshot(); nothing about the graph is cached in Python.

Written against HydraDB v0.4.0's documented dialect (USING-HYDRADB.md) and checked against a live node:
  - every request needs cell_id; responses are {"columns", "rows": [[typed cells]], ...} or {"error": {...}} (or a bare 422 body);
  - writes accept only one-hop edge patterns (an edgeless node needs the node batch), `MERGE` cannot be followed by another clause,
    so property changes are `MATCH ... SET`; there is NO batch shape that writes edge properties, so edges are written one request each;
  - the node batch needs exactly one `SET n:Label` and its values must be row fields (no literals);
  - RETURN items need aliases; reads of ids come back as `vertex_id`, a null cell has no `value`;
  - algo.SPpaths minimises weightProp and reports costProp, so both are 'cost' = -ln w (always written together with w).

Layout (one HydraDB graph shared by all companies and runs; ids are offsets: id = run_id*RUN_SPAN + company_index*CO_SPAN + local):
  (:Component {id, name, kind, tier, co, rc, aff, miss})     rc/aff/miss: root / affected / missed counters
  (:Alias {id, name, co})-[:ALIAS_OF]->(:Component)
  (:Component)-[:DEPENDS_ON {w, cost, origin, conf, lf, cs, o}]->(:Component)    o = insertion ordinal (keeps the in-memory edge order)
  (:Component)-[:SHORTCUT {n}]->(:Component)
  (:GwMeta {id, co, seq, eo, ao})                              graph generation + id allocators
"""
from __future__ import annotations
import math
import types
import httpx
from gwsim.world import official_view
from ..engine.walk import walk, resolve
from .state import GraphState, Edge, W0_OFFICIAL

RUN_SPAN = 10_000_000
CO_SPAN = 100_000
ALIAS_BASE = 50_000       # local id space of alias nodes inside a company
META_LOCAL = 99_999       # local id of the GwMeta node
MAX_HOPS = 5
BATCH = 1000              # HydraDB caps a batch at 1024 items
PAGE_SIZE = 4096          # largest page HydraDB allows; results are always read to the last page
PATH_LIMIT = 100_000      # HydraDB caps one path response at 100,000 results (native_path_result_limit)

EDGE_PROPS = "{w: $w, cost: $cost, origin: $origin, conf: $conf, lf: $lf, cs: $cs, o: $o}"


def cost_of(w):
    return -math.log(max(w, 1e-9))


class HydraError(RuntimeError):
    pass


def decode_cell(cell):
    """A typed cell -> a Python value. vertex_id/integer -> int, float -> float, null -> None (no `value` key), list -> list, path -> dict."""
    t = cell.get("type")
    if t == "null":
        return None
    v = cell.get("value")
    if t == "list":
        return [decode_cell(x) for x in v]
    if t == "path":
        return _path_value(v)
    if t == "float":
        return float(v)
    return v


def _prop(p):
    """Path properties use a third encoding: {"Integer": 3}, {"String": "x"}, {"Float": 0.5}."""
    return next(iter(p.values())) if isinstance(p, dict) and len(p) == 1 else p


def _path_value(v):
    return {"nodes": [n["id"] for n in v["nodes"]],
            "edges": [{"src": r["src"], "dst": r["dst"], "type": r["edge_type"], "props": {k: _prop(x) for k, x in r["properties"].items()}}
                      for r in v["relationships"]]}


def _tabulate(resp):
    """A query response -> list of rows of decoded values. Raises HydraError on the error envelope or an unexpected body."""
    if "error" in resp:
        e = resp["error"]
        raise HydraError(f"{e.get('code')}: {e.get('message')}")
    if "rows" not in resp:
        raise HydraError(f"unexpected response (no rows, no error): {str(resp)[:300]}")      # e.g. the bare 422 envelope
    return [[decode_cell(c) for c in row] for row in resp["rows"]]


def _parse_path(resp, base):
    """algo.SPpaths ... YIELD path, pathCost -> ([local node ids], cost), or None when nothing is reachable within maxLen."""
    rows = _tabulate(resp)
    if not rows:
        return None
    path, cost = rows[0]
    return [n - base for n in path["nodes"]], float(cost)


def _lit(names):
    """Cypher string-list literal (MSpaths takes string lists and rejects list parameters). Backslashes first, then quotes."""
    return "[" + ", ".join("'" + n.replace("\\", "\\\\").replace("'", "\\'") + "'" for n in names) + "]"


class HydraGraph:
    """Read modes (HydraDB is always the source of truth):
      cold    snapshot() reads the whole graph back every time
      cached  snapshot() reads one number (the revision, GwMeta.seq) and re-reads the graph only when it changed; every learner write bumps it
      in_db   verdict_in_db(): the walk's reach comes from two algo.MSpaths queries, the graph's edges are never read back
    """
    def __init__(self, base_url="http://127.0.0.1:8443", token="local-development-token-32-bytes",
                 run_id=1, graph="default", namespace="default", cell_id="cell-0", batch=BATCH, timeout=60, mode="cached"):
        assert mode in ("cold", "cached"), "in_db is a method (verdict_in_db), not a snapshot mode"
        self.mode = mode
        self._cache = None
        self.hits = self.misses = 0
        self.mspaths_requests = 0
        self.run_id = run_id
        self.cell_id = cell_id
        self.batch = min(batch, BATCH)
        self._url = f"{base_url.rstrip('/')}/v1/graphs/{graph}/query"
        self._http = httpx.Client(timeout=timeout, headers={"Authorization": f"Bearer {token}", "X-Graph-Namespace": namespace})
        self._next_company = 0
        self.co = None            # id offset of the current company (the only per-company state kept)

    # ---- plumbing -------------------------------------------------------------------------
    def close(self):
        self._http.close()

    def _q(self, query, **params):
        """One request, following pagination to the end: HydraDB pages results (default 1024 rows, max 4096) and a client that ignores `next_cursor`
        silently truncates. Every page re-sends the whole request with page_size, cursor and query_id; a page is fetched exactly once."""
        body = {"cell_id": self.cell_id, "query": query, "parameters": params, "page_size": PAGE_SIZE}
        first = None
        rows = []
        for _ in range(100_000):
            r = self._http.post(self._url, json=body)
            try:
                page = r.json()
            except ValueError:
                raise HydraError(f"{r.status_code}: {r.text[:300]}\n{query}")
            if "error" in page or "rows" not in page:
                raise HydraError(f"{r.status_code}: {str(page)[:500]}\n{query}")
            first = first or page
            rows += page["rows"]
            if page.get("next_cursor") is None:
                break
            body = {**body, "cursor": page["next_cursor"], "query_id": page["query_id"]}
        else:
            raise HydraError("pagination did not finish")
        return {**first, "rows": rows}

    def _rows(self, query, **params):
        return _tabulate(self._q(query, **params))

    def _batches(self, rows):
        for i in range(0, len(rows), self.batch):
            yield rows[i:i + self.batch]

    def revision(self):
        """The graph revision: GwMeta.seq, bumped by every apply()."""
        r = self._rows("MATCH (m:GwMeta {co: $co}) RETURN m.seq AS seq", co=self._need_co())
        return r[0][0] if r else 0

    def _need_co(self):
        if self.co is None:
            raise HydraError("no company loaded: call fresh(co) first")
        return self.co

    # ---- loading --------------------------------------------------------------------------
    def fresh(self, co, index=None):
        """Load one company (the OFFICIAL view only: names, kinds, the official map, every edge at w=0.7) and return the GraphState written."""
        if index is None:
            index = self._next_company
        self._next_company = max(self._next_company, index) + 1
        base = self.run_id * RUN_SPAN + index * CO_SPAN
        self.co = base
        self._cache = None
        view = official_view(types.SimpleNamespace(components=co["components"], official_edges=co["official_edges"]))
        g = GraphState.from_official(view)
        nodes = [{"id": base + i, "name": c["name"], "kind": c["kind"], "tier": c["tier"], "co": base, "rc": 0, "aff": 0, "miss": 0, "key": f"{base}:{c['name']}"}
                 for i, c in g.components.items()]
        for chunk in self._batches(nodes):      # labels and properties first, then the edges
            self._q("UNWIND $rows AS row MERGE (n {id: row.id}) SET n:Component, n.name = row.name, n.kind = row.kind, n.tier = row.tier, "
                    "n.co = row.co, n.rc = row.rc, n.aff = row.aff, n.miss = row.miss, n.key = row.key", rows=chunk)
        for o, ((u, v), e) in enumerate(g.edges.items()):
            self._q(f"MERGE (a:Component {{id: $u}})-[:DEPENDS_ON {EDGE_PROPS}]->(b:Component {{id: $v}})",
                    u=base + u, v=base + v, w=e.w, cost=cost_of(e.w), origin="official", conf=0, lf=-1, cs=-1, o=o)
        self._write_meta(0, len(g.edges), 0)
        return g

    def _write_meta(self, seq, eo, ao):
        self._q("UNWIND $rows AS row MERGE (n {id: row.id}) SET n:GwMeta, n.co = row.co, n.seq = row.seq, n.eo = row.eo, n.ao = row.ao",
                rows=[{"id": self.co + META_LOCAL, "co": self.co, "seq": seq, "eo": eo, "ao": ao}])

    # ---- reading --------------------------------------------------------------------------
    def snapshot(self) -> GraphState:
        if self.mode == "cold":
            return self._read_graph()
        rev = self.revision()
        if self._cache is not None and self._cache[0] == (self.co, rev):
            self.hits += 1
            return self._cache[1]
        g = self._read_graph()
        self.misses += 1
        self._cache = ((self.co, g.seq), g)
        return g

    def _read_graph(self, with_edges=True) -> GraphState:
        """Read the whole company back from HydraDB into a GraphState with local ids (edges optional: the in-DB verdict never needs them)."""
        base = self._need_co()
        loc = lambda x: int(x) - base
        g = GraphState(components={})
        rc, aff, miss = {}, {}, {}
        comps = self._rows("MATCH (c:Component {co: $co}) RETURN c.id AS id, c.name AS name, c.kind AS kind, c.tier AS tier, "
                           "c.rc AS rc, c.aff AS aff, c.miss AS miss", co=base)
        for r in sorted(comps, key=lambda r: r[0]):
            i = loc(r[0])
            g.components[i] = {"name": r[1], "kind": r[2], "tier": r[3]}
            g.names[r[1]] = i
            if r[4]:
                rc[i] = r[4]
            if r[5]:
                aff[i] = r[5]
            if r[6]:
                miss[i] = r[6]
        g.root_counts, g.affected, g.missed = rc, aff, miss
        if with_edges:
            edges = self._rows("MATCH (a:Component {co: $co})-[e:DEPENDS_ON]->(b:Component) "
                               "RETURN a.id AS u, b.id AS v, e.w AS w, e.origin AS origin, e.conf AS conf, e.lf AS lf, e.cs AS cs, e.o AS o", co=base)
            for r in sorted(edges, key=lambda r: r[7]):
                g.edges[(loc(r[0]), loc(r[1]))] = Edge(float(r[2]), r[3], r[4], r[5], r[6])
        aliases = self._rows("MATCH (a:Alias {co: $co})-[:ALIAS_OF]->(c:Component) RETURN a.id AS aid, a.name AS name, c.id AS cid", co=base)
        for r in sorted(aliases, key=lambda r: r[0]):
            g.names[r[1]] = loc(r[2])
        for r in self._rows("MATCH (a:Component {co: $co})-[s:SHORTCUT]->(b:Component) RETURN a.id AS u, b.id AS v, s.n AS n", co=base):
            g.shortcuts[(loc(r[0]), loc(r[1]))] = r[2]
        meta = self._rows("MATCH (m:GwMeta {co: $co}) RETURN m.seq AS seq", co=base)
        g.seq = meta[0][0] if meta else 0
        return g

    def best_path(self, src, dst):
        """Cheapest (max-product) path src -> dst over DEPENDS_ON, at most MAX_HOPS edges, from HydraDB's own shortest-path algorithm.
        Returns ([local node ids], cost) or None when unreachable."""
        base = self._need_co()
        resp = self._q("CALL algo.SPpaths({sourceNode: $s, targetNode: $t, relTypes: ['DEPENDS_ON'], relDirection: 'outgoing', "
                       "maxLen: $m, weightProp: 'cost', costProp: 'cost', pathCount: 1}) YIELD path, pathCost RETURN path, pathCost",
                       s=base + src, t=base + dst, m=MAX_HOPS)
        return _parse_path(resp, base)

    def _mspaths(self, sources, targets, g):
        """algo.MSpaths: the best (min -ln w) path for every (source, target) pair within MAX_HOPS. -> {(src, dst): cost}, local ids.
        One request answers up to 100,000 paths. A response that comes back full may be truncated, so the sources are halved and re-asked until none is."""
        base = self._need_co()
        nm = lambda c: f"{base}:{g.components[c]['name']}"      # MSpaths selects by property, and every company shares one graph: select by a per-company key
        tl = _lit(nm(c) for c in sorted(targets))
        out = {}

        def ask(srcs):
            try:
                body = self._q("CALL algo.MSpaths({sourceLabel: 'Component', sourceProperty: 'key', sourceValues: " + _lit(nm(c) for c in srcs) +
                               ", targetValues: " + tl + ", relTypes: ['DEPENDS_ON'], relDirection: 'outgoing', maxLen: "
                               f"{MAX_HOPS}, weightProp: 'cost', costProp: 'cost', pathCount: 1, pairwise: false, resultLimit: {PATH_LIMIT}}}) YIELD path, pathCost RETURN path, pathCost")
            except HydraError as e:
                if "client_cursor_buffer_bytes" in str(e) and len(srcs) > 1:       # the 64 MB result buffer: ask for half the sources at a time
                    h = len(srcs) // 2
                    ask(srcs[:h]); ask(srcs[h:])
                    return
                raise
            self.mspaths_requests += 1
            rows = _tabulate(body)
            if len(rows) >= PATH_LIMIT and len(srcs) > 1:           # resultLimit reached: split the sources and ask again
                h = len(srcs) // 2
                ask(srcs[:h]); ask(srcs[h:])
                return
            for path, cost in rows:
                out[(path["nodes"][0] - base, path["nodes"][-1] - base)] = cost
        ask(sorted(sources))
        return out

    def verdict_in_db(self, alerts):
        """The verdict with HydraDB doing the path work: two MSpaths requests give the walk every reach it needs, and the edges are never read back.
          1) alerting services -> every component   (what alerts can see: the candidate set, and q(c, v) for alerting v)
          2) every component -> every candidate     (who would feel a candidate failing, including the services that stayed silent)
        Python only scores. Rankings and scores equal the in-memory engine's (checked by tests/test_parity.py).
        The returned verdict has no `path` (that needs the edges); use it for ranking, not for driving the learner."""
        g = self._read_graph(with_edges=False)
        A, _, _ = resolve(g, alerts)
        if not A:
            return walk(g, alerts)
        down_cost = self._mspaths(A, g.components, g)
        down = {v: {v: 1.0} for v in A}
        cands = set(A)
        for (v, c), cost in down_cost.items():
            down[v][c] = math.exp(-cost)
            cands.add(c)
        up_cost = self._mspaths(g.components, cands, g)
        up = {c: {c: 1.0} for c in cands}
        for (v, c), cost in up_cost.items():
            up[c][v] = math.exp(-cost)
        reach = lambda x, d, h: ((down if d == "out" else up)[x], {})
        return walk(g, alerts, max_hops=MAX_HOPS, reach=reach)

    # ---- writing --------------------------------------------------------------------------
    def apply(self, ops):
        """Translate learner ops into Cypher. Mirrors ghostwalk.learn.update.apply() op by op."""
        base = self._need_co()
        gid = lambda x: base + x
        seq, eo, ao = self._rows("MATCH (m:GwMeta {co: $co}) RETURN m.seq AS seq, m.eo AS eo, m.ao AS ao", co=base)[0]
        counters = {}
        if any(o["op"] in ("root", "observe") for o in ops):          # current counters of the whole company in one read
            for r in self._rows("MATCH (c:Component {co: $co}) RETURN c.id AS id, c.rc AS rc, c.aff AS aff, c.miss AS miss", co=base):
                counters[r[0] - base] = {"rc": r[1], "aff": r[2], "miss": r[3]}
        existing = {}
        if any(o["op"] in ("add_edge", "confirm") for o in ops):
            for r in self._rows("MATCH (a:Component {co: $co})-[e:DEPENDS_ON]->(b:Component) RETURN a.id AS u, b.id AS v, e.conf AS conf, e.o AS o", co=base):
                existing[(r[0] - base, r[1] - base)] = {"conf": r[2], "o": r[3]}
        shortcuts = {}
        if any(o["op"] == "shortcut" for o in ops):
            for r in self._rows("MATCH (a:Component {co: $co})-[s:SHORTCUT]->(b:Component) RETURN a.id AS u, b.id AS v, s.n AS n", co=base):
                shortcuts[(r[0] - base, r[1] - base)] = r[2]

        dirty_counters = set()
        for o in ops:  # sequential, so repeated keys behave exactly like the in-memory loop
            k = o["op"]
            if k == "alias":
                aid = base + ALIAS_BASE + ao
                ao += 1
                self._q("MERGE (a:Alias {id: $aid, name: $name, co: $co})-[:ALIAS_OF]->(c:Component {id: $c})", aid=aid, name=o["name"], co=base, c=gid(o["id"]))
            elif k == "add_edge":
                key = (o["u"], o["v"])
                prev = existing.get(key)
                ordinal = prev["o"] if prev else eo
                eo += 0 if prev else 1
                existing[key] = {"conf": 1, "o": ordinal}
                props = dict(w=o["w"], cost=cost_of(o["w"]), origin="learned", conf=1, lf=o["seq"], cs=o["seq"], o=ordinal)
                if prev:
                    self._set_edge(o["u"], o["v"], **props)
                else:
                    self._q(f"MERGE (a:Component {{id: $u}})-[:DEPENDS_ON {EDGE_PROPS}]->(b:Component {{id: $v}})", u=gid(o["u"]), v=gid(o["v"]), **props)
            elif k == "confirm":
                prev = existing[(o["u"], o["v"])]
                prev["conf"] += 1
                self._set_edge(o["u"], o["v"], w=o["w"], cost=cost_of(o["w"]), conf=prev["conf"])
            elif k == "reweight":
                self._set_edge(o["u"], o["v"], w=o["w"], cost=cost_of(o["w"]))
            elif k == "drop_edge":
                self._q("MATCH (a {id: $u})-[e:DEPENDS_ON]->(b {id: $v}) DELETE e", u=gid(o["u"]), v=gid(o["v"]))
                existing.pop((o["u"], o["v"]), None)
            elif k == "root":
                counters[o["id"]]["rc"] += 1
                dirty_counters.add(o["id"])
            elif k == "shortcut":
                key = (o["entry"], o["root"])
                if key in shortcuts:
                    shortcuts[key] += 1
                    self._q("MATCH (a {id: $u})-[s:SHORTCUT]->(b {id: $v}) SET s.n = $n", u=gid(key[0]), v=gid(key[1]), n=shortcuts[key])
                else:
                    shortcuts[key] = 1
                    self._q("MERGE (a:Component {id: $u})-[:SHORTCUT {n: $n}]->(b:Component {id: $v})", u=gid(key[0]), v=gid(key[1]), n=1)
            elif k == "observe":
                c = counters[o["id"]]
                c["aff"] += 1
                c["miss"] += 1 if o["silent"] else 0
                dirty_counters.add(o["id"])
        if dirty_counters:
            rows = [{"id": gid(i), **counters[i]} for i in sorted(dirty_counters)]
            for chunk in self._batches(rows):
                self._q("UNWIND $rows AS row MERGE (n {id: row.id}) SET n:Component, n.rc = row.rc, n.aff = row.aff, n.miss = row.miss", rows=chunk)
        self._write_meta(seq + 1, eo, ao)

    def _set_edge(self, u, v, **props):
        base = self._need_co()
        sets = ", ".join(f"e.{k} = ${k}" for k in props)
        self._q("MATCH (a {id: $u})-[e:DEPENDS_ON]->(b {id: $v}) SET " + sets, u=base + u, v=base + v, **props)

    # ---- cleanup --------------------------------------------------------------------------
    def drop(self):
        """Delete everything of the current company (components, aliases, meta), in batches of at most 1024 ids."""
        if self.co is None:
            return
        self._cache = None                      # the revision cache must not outlive the data it describes
        ids = [r[0] for r in self._rows("MATCH (n:Component {co: $co}) RETURN n.id AS id", co=self.co)]
        ids += [r[0] for r in self._rows("MATCH (n:Alias {co: $co}) RETURN n.id AS id", co=self.co)]
        ids += [r[0] for r in self._rows("MATCH (n:GwMeta {co: $co}) RETURN n.id AS id", co=self.co)]
        for chunk in self._batches([{"id": i} for i in ids]):
            self._q("UNWIND $rows AS row MATCH (n {id: row.id}) DETACH DELETE n", rows=chunk)
