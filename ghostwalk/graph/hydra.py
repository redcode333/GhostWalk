"""HydraDB-backed graph store. The same GraphState the in-memory backend produces is rebuilt
from the live HydraDB graph on every snapshot(); nothing about the graph is cached in Python.

Layout (one HydraDB graph shared by all companies and runs, because the local token is scoped
to a single graph). Node/edge ids are offsets:  id = run_id*RUN_SPAN + company_index*CO_SPAN + local.

  (:Component {id, name, kind, tier, co, rc, aff, miss})     rc/aff/miss: root/affected/missed counters
  (:Alias {id, name, co})-[:ALIAS_OF]->(:Component)
  (:Component)-[:DEPENDS_ON {w, cost, origin, conf, lf, cs, o}]->(:Component)
        cost = -ln(w) is always written together with w; o = insertion ordinal (keeps the edge
        order of the in-memory dict, which the engine's float summation order depends on)
  (:Component)-[:SHORTCUT {n}]->(:Component)
  (:GwMeta {id, co, seq, eo, ao})                            graph generation + id allocators
"""
from __future__ import annotations
import math
import types
import httpx
from gwsim.world import official_view
from .state import GraphState, Edge, W0_OFFICIAL

RUN_SPAN = 10_000_000
CO_SPAN = 100_000
ALIAS_BASE = 50_000       # local id space of alias nodes inside a company
META_LOCAL = 99_999       # local id of the GwMeta node
MAX_HOPS = 5


def cost_of(w):
    return -math.log(max(w, 1e-9))


class HydraError(RuntimeError):
    pass


class HydraGraph:
    def __init__(self, base_url="http://127.0.0.1:8443", token="local-development-token-32-bytes",
                 run_id=1, graph="default", namespace="default", cell_id="cell-0", batch=400, timeout=60):
        self.run_id = run_id
        self.cell_id = cell_id
        self.batch = batch
        self._url = f"{base_url.rstrip('/')}/v1/graphs/{graph}/query"
        self._http = httpx.Client(timeout=timeout, headers={"Authorization": f"Bearer {token}",
                                                            "X-Graph-Namespace": namespace})
        self._next_company = 0
        self.co = None            # id offset of the current company (the only per-company state kept)

    # ---- plumbing -------------------------------------------------------------------------
    def close(self):
        self._http.close()

    def _q(self, query, **params):
        r = self._http.post(self._url, json={"cell_id": self.cell_id, "query": query, "parameters": params})
        if r.status_code != 200:
            raise HydraError(f"{r.status_code}: {r.text[:500]}\n{query}")
        return r.json()

    def _rows(self, query, **params):
        return _tabulate(self._q(query, **params))

    def _batches(self, rows):
        for i in range(0, len(rows), self.batch):
            yield rows[i:i + self.batch]

    def _need_co(self):
        if self.co is None:
            raise HydraError("no company loaded: call fresh(co) first")
        return self.co

    # ---- loading --------------------------------------------------------------------------
    def fresh(self, co, index=None):
        """Load one company (the OFFICIAL view only: names, kinds, the official map, every edge
        at w=0.7) into HydraDB and return the GraphState that was written."""
        if index is None:
            index = self._next_company
        self._next_company = max(self._next_company, index) + 1
        base = self.run_id * RUN_SPAN + index * CO_SPAN
        self.co = base
        view = official_view(types.SimpleNamespace(components=co["components"], official_edges=co["official_edges"]))
        g = GraphState.from_official(view)
        comps = [{"id": base + i, "name": c["name"], "kind": c["kind"], "tier": c["tier"], "co": base}
                 for i, c in g.components.items()]
        for chunk in self._batches(comps):
            self._q("UNWIND $rows AS r CREATE (:Component {id: r.id, name: r.name, kind: r.kind, "
                    "tier: r.tier, co: r.co, rc: 0, aff: 0, miss: 0})", rows=chunk)
        edges = [{"u": base + u, "v": base + v, "w": e.w, "cost": cost_of(e.w), "o": o}
                 for o, ((u, v), e) in enumerate(g.edges.items())]
        for chunk in self._batches(edges):
            self._q("UNWIND $rows AS r MERGE (a:Component {id: r.u}) MERGE (b:Component {id: r.v}) "
                    "MERGE (a)-[e:DEPENDS_ON]->(b) SET e.w = r.w, e.cost = r.cost, e.origin = 'official', "
                    "e.conf = 0, e.lf = -1, e.cs = -1, e.o = r.o", rows=chunk)
        self._q("CREATE (:GwMeta {id: $id, co: $co, seq: 0, eo: $eo, ao: 0})",
                id=base + META_LOCAL, co=base, eo=len(edges))
        return g

    # ---- reading --------------------------------------------------------------------------
    def snapshot(self) -> GraphState:
        """Read the whole company back from HydraDB (no caching) into a GraphState with local ids."""
        base = self._need_co()
        loc = lambda x: int(x) - base
        g = GraphState(components={})
        rc, aff, miss = {}, {}, {}
        comps = self._rows("MATCH (c:Component {co: $co}) RETURN c.id, c.name, c.kind, c.tier, c.rc, c.aff, c.miss",
                           co=base)
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
        edges = self._rows("MATCH (a:Component {co: $co})-[e:DEPENDS_ON]->(b:Component) "
                           "RETURN a.id, b.id, e.w, e.origin, e.conf, e.lf, e.cs, e.o", co=base)
        for r in sorted(edges, key=lambda r: r[7]):
            g.edges[(loc(r[0]), loc(r[1]))] = Edge(r[2], r[3], r[4], r[5], r[6])
        aliases = self._rows("MATCH (a:Alias {co: $co})-[:ALIAS_OF]->(c:Component) RETURN a.id, a.name, c.id", co=base)
        for r in sorted(aliases, key=lambda r: r[0]):
            g.names[r[1]] = loc(r[2])
        for r in self._rows("MATCH (a:Component {co: $co})-[s:SHORTCUT]->(b:Component) RETURN a.id, b.id, s.n", co=base):
            g.shortcuts[(loc(r[0]), loc(r[1]))] = r[2]
        meta = self._rows("MATCH (m:GwMeta {co: $co}) RETURN m.seq", co=base)
        g.seq = meta[0][0] if meta else 0
        return g

    def best_path(self, src, dst):
        """Cheapest (max-product) path src -> dst over DEPENDS_ON, at most MAX_HOPS edges, from HydraDB's
        own shortest-path algorithm. Returns ([local node ids], cost) or None when unreachable."""
        base = self._need_co()
        resp = self._q("CALL algo.SPpaths({sourceNode: $s, targetNode: $t, relTypes: ['DEPENDS_ON'], "
                       f"maxLen: {MAX_HOPS}, costProp: 'cost', pathCount: 1}}) YIELD path, pathCost "
                       "RETURN path, pathCost", s=base + src, t=base + dst)
        return _parse_path(resp, base)

    # ---- writing --------------------------------------------------------------------------
    def apply(self, ops):
        """Translate learner ops into Cypher. Mirrors ghostwalk.learn.update.apply() op by op."""
        base = self._need_co()
        gid = lambda x: base + x
        # current counters/ordinals of what these ops touch, read from HydraDB (absolute-value writes)
        seq, eo, ao = self._rows("MATCH (m:GwMeta {co: $co}) RETURN m.seq, m.eo, m.ao", co=base)[0]
        comp_ids = sorted({o[k] for o in ops for k in ("id", "entry", "root") if k in o})
        counters = {}
        if comp_ids:
            for r in self._rows("UNWIND $ids AS i MATCH (c:Component {id: i}) RETURN c.id, c.rc, c.aff, c.miss",
                                ids=[gid(i) for i in comp_ids]):
                counters[r[0] - base] = {"rc": r[1], "aff": r[2], "miss": r[3]}
        edge_keys = [(o["u"], o["v"]) for o in ops if o["op"] in ("add_edge", "confirm")]
        existing = {}
        if edge_keys:
            rows = [{"u": gid(u), "v": gid(v)} for u, v in edge_keys]
            for r in self._rows("UNWIND $rows AS r MATCH (a:Component {id: r.u})-[e:DEPENDS_ON]->(b:Component {id: r.v}) "
                                "RETURN a.id, b.id, e.conf, e.o", rows=rows):
                existing[(r[0] - base, r[1] - base)] = {"conf": r[2], "o": r[3]}
        shortcuts = {}
        sc_keys = [(o["entry"], o["root"]) for o in ops if o["op"] == "shortcut"]
        if sc_keys:
            rows = [{"u": gid(u), "v": gid(v)} for u, v in sc_keys]
            for r in self._rows("UNWIND $rows AS r MATCH (a:Component {id: r.u})-[s:SHORTCUT]->(b:Component {id: r.v}) "
                                "RETURN a.id, b.id, s.n", rows=rows):
                shortcuts[(r[0] - base, r[1] - base)] = r[2]

        dirty_counters, dirty_shortcuts = set(), set()
        for o in ops:  # sequential, so repeated keys behave exactly like the in-memory loop
            k = o["op"]
            if k == "alias":
                aid = base + ALIAS_BASE + ao
                ao += 1
                self._q("MERGE (a:Alias {id: $aid}) SET a.name = $name, a.co = $co", aid=aid, name=o["name"], co=base)
                self._q("MATCH (a:Alias {id: $aid}) MERGE (c:Component {id: $c}) MERGE (a)-[:ALIAS_OF]->(c)",
                        aid=aid, c=gid(o["id"]))
            elif k == "add_edge":
                key = (o["u"], o["v"])
                prev = existing.get(key)
                if prev is None:
                    ordinal, eo = eo, eo + 1
                else:
                    ordinal = prev["o"]
                existing[key] = {"conf": 1, "o": ordinal}
                self._set_edge(o["u"], o["v"], w=o["w"], origin="learned", conf=1, lf=o["seq"], cs=o["seq"], o=ordinal)
            elif k == "confirm":
                prev = existing[(o["u"], o["v"])]
                prev["conf"] += 1
                self._set_edge(o["u"], o["v"], w=o["w"], conf=prev["conf"])
            elif k == "reweight":
                self._set_edge(o["u"], o["v"], w=o["w"])
            elif k == "drop_edge":
                self._q("MATCH (a:Component {id: $u})-[e:DEPENDS_ON]->(b:Component {id: $v}) DELETE e",
                        u=gid(o["u"]), v=gid(o["v"]))
                existing.pop((o["u"], o["v"]), None)
            elif k == "root":
                counters[o["id"]]["rc"] += 1
                dirty_counters.add(o["id"])
            elif k == "shortcut":
                key = (o["entry"], o["root"])
                shortcuts[key] = shortcuts.get(key, 0) + 1
                dirty_shortcuts.add(key)
            elif k == "observe":
                c = counters[o["id"]]
                c["aff"] += 1
                c["miss"] += 1 if o["silent"] else 0
                dirty_counters.add(o["id"])
        if dirty_counters:
            rows = [{"id": gid(i), **counters[i]} for i in sorted(dirty_counters)]
            self._q("UNWIND $rows AS r MATCH (c:Component {id: r.id}) SET c.rc = r.rc, c.aff = r.aff, c.miss = r.miss",
                    rows=rows)
        for (u, v) in sorted(dirty_shortcuts):
            self._q("MERGE (a:Component {id: $u}) MERGE (b:Component {id: $v}) MERGE (a)-[s:SHORTCUT]->(b) SET s.n = $n",
                    u=gid(u), v=gid(v), n=shortcuts[(u, v)])
        self._q("MATCH (m:GwMeta {co: $co}) SET m.seq = $seq, m.eo = $eo, m.ao = $ao", co=base, seq=seq + 1, eo=eo, ao=ao)

    def _set_edge(self, u, v, w, **props):
        base = self._need_co()
        props = {"w": w, "cost": cost_of(w), **props}
        sets = ", ".join(f"e.{k} = ${k}" for k in props)
        self._q("MERGE (a:Component {id: $u}) MERGE (b:Component {id: $v}) MERGE (a)-[e:DEPENDS_ON]->(b) SET " + sets,
                u=base + u, v=base + v, **props)

    # ---- cleanup --------------------------------------------------------------------------
    def drop(self):
        """DETACH DELETE everything of the current company (components, aliases, meta)."""
        if self.co is None:
            return
        for label in ("Alias", "Component", "GwMeta"):
            self._q(f"MATCH (n:{label} {{co: $co}}) DETACH DELETE n", co=self.co)


def _tabulate(resp):
    raise NotImplementedError("response shape not verified yet")


def _parse_path(resp, base):
    raise NotImplementedError("response shape not verified yet")
