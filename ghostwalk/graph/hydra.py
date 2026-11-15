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
  (:GwMeta {id, co, seq, eo, ao, mo})                          graph generation + id allocators

The learner's memory is part of the same graph (every node carries the company `co` and a `key`); Components also carry the label Service:
  (:Incident {id, name, seq, ts})-[:RAISED]->(:Alert {ts, name, signal})-[:ON]->(:Service)
  (:Postmortem {incident_id, root, root_name, path, missed})-[:ABOUT]->(:Incident)
  (:Lesson {src, dst, src_name, dst_name, w, state: tentative|confirmed|decayed, created_seq})-[:TAUGHT_BY]->(:Postmortem)
  (:Lesson)-[:CONFIRMED_BY]->(:Incident)
A Lesson is a learned DEPENDS_ON edge made into a node; its w follows the edge's w (written in the same apply()).
"""
from __future__ import annotations
import copy
import math
import types
from concurrent.futures import ThreadPoolExecutor
import httpx
from gwsim.world import official_view
from ..engine.walk import walk, resolve
from ..learn import update as learner
from .state import GraphState, Edge, W0_OFFICIAL
from .fasthttp import FastClient

RUN_SPAN = 10_000_000
CO_SPAN = 100_000
ALIAS_BASE = 50_000       # local id space of alias nodes inside a company
META_LOCAL = 99_999       # local id of the GwMeta node
INC_BASE = 60_000         # Incident: INC_BASE + seq            (seq < 1,000)
PM_BASE = 61_000          # Postmortem: PM_BASE + seq           (seq < 1,000)
ALERT_BASE = 62_000       # Alert: ALERT_BASE + running counter (< 5,000 alerts)
LESSON_BASE = 67_000      # Lesson: LESSON_BASE + the edge's insertion ordinal (< 32,000)
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


class _Memory:
    """Collects one apply()'s memory writes (the incident, its alerts, the postmortem, lesson changes) and writes them in few requests."""
    def __init__(self, hg, base, names, incident):
        self.hg, self.base, self.names, self.inc = hg, base, names, incident
        self.lesson_of = {}                  # (u, v) -> global Lesson id, for lessons that are not decayed
        self.new, self.upd, self.taught, self.confirmed_by = {}, {}, [], []

    def _lid(self, ordinal):
        return self.base + LESSON_BASE + ordinal if 0 <= ordinal < 32_000 else None

    def proposed(self, o, ordinal):
        if self.inc is None or (lid := self._lid(ordinal)) is None:
            return
        comps = self.hg.snapshot().components
        self.lesson_of[(o["u"], o["v"])] = lid
        self.new[lid] = {"id": lid, "co": self.base, "key": f"{self.base}:lesson:{ordinal}", "src": self.base + o["u"], "dst": self.base + o["v"],
                         "src_name": comps[o["u"]]["name"], "dst_name": comps[o["v"]]["name"], "w": o["w"], "state": "tentative", "created_seq": o["seq"]}
        self.taught.append(lid)

    def _change(self, o, **kw):
        lid = self.lesson_of.get((o["u"], o["v"])) if self.inc is not None else None
        if lid is not None:
            (self.new[lid] if lid in self.new else self.upd.setdefault(lid, {"id": lid})).update(kw)
        return lid

    def confirmed(self, o, conf):
        lid = self._change(o, w=o["w"], state="confirmed" if conf >= 2 else "tentative")
        if lid is not None:
            self.confirmed_by.append(lid)

    def reweighted(self, o):
        self._change(o, w=o["w"])

    def decayed(self, o):
        if self._change(o, w=0.0, state="decayed") is not None:
            self.lesson_of.pop((o["u"], o["v"]), None)

    def _nodes(self, label, items):
        for chunk in self.hg._batches(items):
            self.hg._q(f"UNWIND $rows AS row MERGE (n {{id: row.id}}) SET n:{label}, " + ", ".join(f"n.{k} = row.{k}" for k in chunk[0] if k != "id"), rows=chunk)

    def write(self, ops, mo):
        inc = self.inc
        if inc is None:
            return mo
        q, b, seq = self.hg._q, self.base, inc["seq"]
        if not (0 <= seq < 1000):
            return mo
        iid, pid = b + INC_BASE + seq, b + PM_BASE + seq
        alerts = inc.get("alerts", [])[:max(0, 5000 - mo)]
        pm = inc.get("postmortem") or {}
        comps = self.hg.snapshot().components
        nm = lambda c: comps[c]["name"] if c in comps else str(c)
        t0 = min((a.get("t", 0.0) for a in alerts), default=0.0)
        self._nodes("Incident", [{"id": iid, "co": b, "key": f"{b}:incident:{seq}", "seq": seq, "name": inc.get("name") or f"incident-{seq}", "ts": float(t0)}])
        if alerts:
            self._nodes("Alert", [{"id": b + ALERT_BASE + mo + i, "co": b, "key": f"{b}:alert:{mo + i}", "ts": float(a.get("t", 0.0)), "name": a["name"],
                                   "signal": a.get("signal") or ""} for i, a in enumerate(alerts)])
        silent = sorted({nm(o["id"]) for o in ops if o["op"] == "observe" and o["silent"]})
        chain = [tuple(e) for e in pm.get("chain", []) if e[0] in comps and e[1] in comps]
        root = pm.get("root")
        self._nodes("Postmortem", [{"id": pid, "co": b, "key": f"{b}:postmortem:{seq}", "incident_id": seq, "root": b + root if root in comps else -1,
                                    "root_name": nm(root) if root in comps else "", "path": ";".join(f"{nm(u)}>{nm(v)}" for u, v in chain), "missed": ",".join(silent)}])
        if self.new:
            self._nodes("Lesson", list(self.new.values()))
        upd = [u for u in self.upd.values() if u["id"] not in self.new]
        for kinds in (("state", "w"), ("w",)):                          # property sets differ per row shape: one batch per shape
            grp = [u for u in upd if set(u) - {"id"} == set(kinds)]
            if grp:
                q("UNWIND $rows AS row MERGE (n {id: row.id}) SET n:Lesson, " + ", ".join(f"n.{k} = row.{k}" for k in kinds), rows=grp)
        for i, a in enumerate(alerts):
            aid = b + ALERT_BASE + mo + i
            q("MERGE (a:Incident {id: $a})-[:RAISED]->(b:Alert {id: $b})", a=iid, b=aid)
            sid = self.names.get(a["name"])
            if sid is not None:
                q("MERGE (a:Alert {id: $a})-[:ON]->(b:Service {id: $b})", a=aid, b=b + sid)
        q("MERGE (a:Postmortem {id: $a})-[:ABOUT]->(b:Incident {id: $b})", a=pid, b=iid)
        for lid in self.taught:
            q("MERGE (a:Lesson {id: $a})-[:TAUGHT_BY]->(b:Postmortem {id: $b})", a=lid, b=pid)
        for lid in dict.fromkeys(self.confirmed_by):
            q("MERGE (a:Lesson {id: $a})-[:CONFIRMED_BY]->(b:Incident {id: $b})", a=lid, b=iid)
        return mo + len(alerts)


class HydraGraph:
    """Read modes (HydraDB is always the source of truth):
      cold    snapshot() reads the whole graph back every time
      cached  a revision-checked WRITE-THROUGH cache. snapshot() reads one number (the revision, GwMeta.seq) and serves the cached graph only if it equals HydraDB's;
              apply() writes to HydraDB and applies the identical change to the cached graph in the same step (the learner's own update.apply), then confirms
              the revision HydraDB reports. The graph is re-read in full only when the revisions disagree (another writer, a failed write) or when nothing is cached yet.
      in_db   verdict_in_db(): the walk's reach comes from two algo.MSpaths queries, the graph's edges are never read back
    """
    def __init__(self, base_url="http://127.0.0.1:8443", token="local-development-token-32-bytes",
                 run_id=1, graph="default", namespace="default", cell_id="cell-0", batch=BATCH, timeout=120, mode="cached", transport="fast"):
        assert mode in ("cold", "cached"), "in_db is a method (verdict_in_db), not a snapshot mode"
        self.mode = mode
        self._cache = None
        self.hits = self.misses = 0
        self.full_reads = 0            # full graph re-reads done by snapshot() (the write-through cache should make this 0 while learning)
        self.timeouts = 0              # requests that stalled past the timeout and were re-sent
        self.disagreements = 0         # writes after which HydraDB's revision was not the one the cache expected
        self.mspaths_requests = 0
        self._pool = None
        self.run_id = run_id
        self.cell_id = cell_id
        self.batch = min(batch, BATCH)
        self._url = f"{base_url.rstrip('/')}/v1/graphs/{graph}/query"
        headers = {"Authorization": f"Bearer {token}", "X-Graph-Namespace": namespace}
        # "fast": a persistent connection that sends each request in one write (see fasthttp.py: httpx's split writes cost ~45 ms per request through
        # Docker Desktop's published port). https and transport="httpx" use httpx.
        self._http = FastClient(base_url, headers, timeout) if transport == "fast" and base_url.startswith("http://") else httpx.Client(timeout=timeout, headers=headers)
        self._next_company = 0
        self.co = None            # id offset of the current company (the only per-company state kept)

    # ---- plumbing -------------------------------------------------------------------------
    # ---- memory queries: answered by traversal of the graph the learner wrote -----------------
    def similar_incidents(self, alerts, k=5, hops=2):
        """Graph memory: past incidents with an alert on a service within `hops` of the current alerting services, ranked by neighbourhood overlap.
        The neighbourhood N is found by traversal (DEPENDS_ON in both directions; HydraDB's variable-length match needs a fixed source, so the reverse
        direction is walked one level per query). The past incidents come from Incident-[:RAISED]->Alert-[:ON]->Service.
        score = |alerting services of the past incident that lie in N| / |its alerting services + the current ones|, ties to the more recent incident."""
        base = self._need_co()
        names = self.snapshot().names
        S = {base + names[a["name"]] for a in alerts if a["name"] in names}
        if not S:
            return []
        jobs = {f"f{s}": (f"MATCH (a:Service {{id: $s}})-[:DEPENDS_ON*1..{int(hops)}]->(b:Service) RETURN DISTINCT b.id AS id", {"s": s}) for s in S}
        N, frontier = set(S), set(S)
        for r in self._par(jobs).values():
            N.update(x[0] for x in r)
        for _ in range(hops):                                   # reverse direction: who depends on the frontier
            got = self._par({f"r{x}": ("MATCH (a:Service {co: $co})-[:DEPENDS_ON]->(b:Service {id: $b}) RETURN a.id AS id", {"co": base, "b": x}) for x in frontier})
            frontier = {y[0] for rows in got.values() for y in rows} - N
            N |= frontier
        past = {}
        for iid, seq, sid in self._rows("MATCH (i:Incident {co: $co})-[:RAISED]->(a:Alert)-[:ON]->(s:Service) RETURN i.id AS i, i.seq AS seq, s.id AS s", co=base):
            past.setdefault((iid, seq), set()).add(sid)
        scored = [((len(a & N) / len(a | S)), seq) for (iid, seq), a in past.items() if a & N]
        return [(seq, round(sc, 6)) for sc, seq in sorted(scored, key=lambda t: (-t[0], -t[1]))[:k]]
    def lessons(self, src=None, dst=None):
        """Lessons (learned edges as nodes), optionally filtered to one edge by service name; newest first."""
        base = self._need_co()
        rows = self._rows("MATCH (l:Lesson {co: $co}) RETURN l.id AS id, l.src_name AS s, l.dst_name AS d, l.w AS w, l.state AS state, l.created_seq AS cs", co=base)
        out = [{"id": r[0] - base - LESSON_BASE, "src": r[1], "dst": r[2], "w": r[3], "state": r[4], "created_seq": r[5]} for r in rows
               if (src is None or r[1] == src) and (dst is None or r[2] == dst)]
        return sorted(out, key=lambda x: -x["id"])

    def why_edge(self, src, dst):
        """Why does the graph believe `src depends on dst`? The lessons for that edge, the postmortems that taught each one and the incidents that confirmed it."""
        base = self._need_co()
        edge = self._rows("MATCH (a:Service {co: $co, name: $s})-[e:DEPENDS_ON]->(b:Service {co: $co, name: $d}) RETURN e.w AS w, e.origin AS origin, e.conf AS conf", co=base, s=src, d=dst)
        out = {"src": src, "dst": dst, "edge": None if not edge else {"w": edge[0][0], "origin": edge[0][1], "confirmations": edge[0][2]}, "lessons": []}
        for les in self.lessons(src, dst):
            gid = base + LESSON_BASE + les["id"]
            taught = self._rows("MATCH (l:Lesson {id: $id})-[:TAUGHT_BY]->(p:Postmortem)-[:ABOUT]->(i:Incident) RETURN p.root_name AS root, p.path AS path, p.missed AS missed, "
                                "i.name AS name, i.seq AS seq, i.ts AS ts", id=gid)
            conf = self._rows("MATCH (l:Lesson {id: $id})-[:CONFIRMED_BY]->(i:Incident) RETURN i.name AS name, i.seq AS seq, i.ts AS ts", id=gid)
            les["taught_by"] = [{"incident": r[3], "seq": r[4], "ts": r[5], "postmortem": {"root": r[0], "path": r[1], "missed": [x for x in (r[2] or "").split(",") if x]}} for r in taught]
            les["confirmed_by"] = sorted(({"incident": r[0], "seq": r[1], "ts": r[2]} for r in conf), key=lambda x: x["seq"])
            out["lessons"].append(les)
        return out

    def lesson_impact(self, lesson_id, hops=5):
        """Services and past incidents whose paths use a learned edge u->v (u depends on v). A fault at v or below reaches u and everything that depends on u,
        so: the services upstream of u (DEPENDS_ON walked backwards, level by level) and the past incidents with an alert on one of them whose postmortem
        root is v or downstream of v (a variable-length traversal from v)."""
        base = self._need_co()
        row = self._rows("MATCH (l:Lesson {id: $id}) RETURN l.src AS s, l.dst AS d, l.src_name AS sn, l.dst_name AS dn, l.w AS w, l.state AS state", id=base + LESSON_BASE + lesson_id)
        if not row:
            return None
        u, v, sn, dn, w, state = row[0]
        upstream, frontier = {u}, [u]
        for _ in range(hops):
            nxt = []
            for x in frontier:
                for (y,) in self._rows("MATCH (a:Service {co: $co})-[:DEPENDS_ON]->(b:Service {id: $b}) RETURN a.id AS id", co=base, b=x):
                    if y not in upstream:
                        upstream.add(y)
                        nxt.append(y)
            frontier = nxt
        below = {v} | {r[0] for r in self._rows(f"MATCH (a:Service {{id: $v}})-[:DEPENDS_ON*1..{int(hops)}]->(b:Service) RETURN DISTINCT b.id AS id", v=v)}
        svc = {r[0]: r[1] for r in self._rows("MATCH (s:Service {co: $co}) RETURN s.id AS id, s.name AS name", co=base)}
        roots = {r[0]: r[1] for r in self._rows("MATCH (p:Postmortem {co: $co})-[:ABOUT]->(i:Incident) RETURN i.id AS id, p.root AS root", co=base)}
        names = {r[0]: (r[1], r[2]) for r in self._rows("MATCH (i:Incident {co: $co}) RETURN i.id AS id, i.name AS name, i.seq AS seq", co=base)}
        hit = {}
        for iid, sid in self._rows("MATCH (i:Incident {co: $co})-[:RAISED]->(a:Alert)-[:ON]->(s:Service) RETURN i.id AS i, s.id AS s", co=base):
            if sid in upstream and roots.get(iid) in below:
                hit.setdefault(iid, set()).add(sid)
        return {"lesson": {"id": lesson_id, "src": sn, "dst": dn, "w": w, "state": state},
                "services": sorted(svc[x] for x in upstream if x in svc),
                "incidents": [{"incident": names[i][0], "seq": names[i][1], "alerting_services": sorted(svc[x] for x in sv if x in svc)}
                              for i, sv in sorted(hit.items(), key=lambda kv: names[kv[0]][1])]}

    def close(self):
        if self._pool is not None:
            self._pool.shutdown(wait=False)
        self._http.close()

    def _q(self, query, **params):
        """One request, following pagination to the end: HydraDB pages results (default 1024 rows, max 4096) and a client that ignores `next_cursor`
        silently truncates. Every page re-sends the whole request with page_size, cursor and query_id; a page is fetched exactly once."""
        body = {"cell_id": self.cell_id, "query": query, "parameters": params, "page_size": PAGE_SIZE}
        first = None
        rows = []
        for _ in range(100_000):
            for attempt in range(3):             # every statement the adapter sends is idempotent (MERGE / SET / DELETE / reads), so a stalled one can be re-sent
                try:
                    r = self._http.post(self._url, json=body)
                    break
                except (TimeoutError, httpx.TimeoutException):
                    self.timeouts += 1
                    if attempt == 2:
                        raise
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
        r = self._rows("MATCH (m {id: $id}) RETURN m.seq AS seq", id=self._need_co() + META_LOCAL)      # id-anchored: about 1 ms
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
        self._q("MATCH (n:Component {co: $co}) SET n:Service", co=base)       # the memory schema calls components Service
        for o, ((u, v), e) in enumerate(g.edges.items()):
            self._q(f"MERGE (a:Component {{id: $u}})-[:DEPENDS_ON {EDGE_PROPS}]->(b:Component {{id: $v}})",
                    u=base + u, v=base + v, w=e.w, cost=cost_of(e.w), origin="official", conf=0, lf=-1, cs=-1, o=o)
        self._write_meta(0, len(g.edges), 0)
        if self.mode == "cached":
            self._cache = ((base, 0), self._copy(g))          # we just wrote exactly this graph at revision 0
        return g

    def _write_meta(self, seq, eo, ao, mo=0):
        self._q("UNWIND $rows AS row MERGE (n {id: row.id}) SET n:GwMeta, n.co = row.co, n.seq = row.seq, n.eo = row.eo, n.ao = row.ao, n.mo = row.mo",
                rows=[{"id": self.co + META_LOCAL, "co": self.co, "seq": seq, "eo": eo, "ao": ao, "mo": mo}])

    def attach(self, base):
        """Re-attach to a company already in HydraDB (a restarted process): True when its GwMeta node exists. Nothing is written; the next snapshot() reads it back."""
        self.co = base
        self._cache = None
        if not self._rows("MATCH (m {id: $id}) RETURN m.seq AS seq", id=base + META_LOCAL):
            self.co = None
            return False
        self._next_company = max(self._next_company, (base % RUN_SPAN) // CO_SPAN + 1)
        return True

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
        self.full_reads += 1
        self._cache = ((self.co, g.seq), g)
        return g

    @staticmethod
    def _copy(g: GraphState) -> GraphState:
        """A copy the learner may mutate without touching what callers hold (components are never mutated, so they are shared)."""
        c = GraphState(components=g.components, edges={k: copy.copy(e) for k, e in g.edges.items()}, names=dict(g.names), root_counts=dict(g.root_counts),
                       shortcuts=dict(g.shortcuts), affected=dict(g.affected), missed=dict(g.missed), seq=g.seq)
        return c

    def _par(self, jobs):
        """Run independent reads at the same time (one connection per worker thread). {name: (query, params)} -> {name: rows}."""
        if self._pool is None:
            self._pool = ThreadPoolExecutor(5)
        futs = {n: self._pool.submit(self._rows, q, **p) for n, (q, p) in jobs.items()}
        return {n: f.result() for n, f in futs.items()}

    def _read_graph(self, with_edges=True) -> GraphState:
        """Read the whole company back from HydraDB into a GraphState with local ids (edges optional: the in-DB verdict never needs them).
        The reads are independent, so they are issued together; the revision is an id-anchored read (about 1 ms against 11 to 50 ms for a scan on `co`)."""
        base = self._need_co()
        loc = lambda x: int(x) - base
        jobs = {"comps": ("MATCH (c:Component {co: $co}) RETURN c.id AS id, c.name AS name, c.kind AS kind, c.tier AS tier, c.rc AS rc, c.aff AS aff, c.miss AS miss", {"co": base}),
                "aliases": ("MATCH (a:Alias {co: $co})-[:ALIAS_OF]->(c:Component) RETURN a.id AS aid, a.name AS name, c.id AS cid", {"co": base}),
                "shortcuts": ("MATCH (a:Component {co: $co})-[s:SHORTCUT]->(b:Component) RETURN a.id AS u, b.id AS v, s.n AS n", {"co": base}),
                "meta": ("MATCH (m {id: $id}) RETURN m.seq AS seq", {"id": base + META_LOCAL})}
        if with_edges:
            jobs["edges"] = ("MATCH (a:Component {co: $co})-[e:DEPENDS_ON]->(b:Component) "
                             "RETURN a.id AS u, b.id AS v, e.w AS w, e.origin AS origin, e.conf AS conf, e.lf AS lf, e.cs AS cs, e.o AS o", {"co": base})
        got = self._par(jobs)
        g = GraphState(components={})
        rc, aff, miss = {}, {}, {}
        for r in sorted(got["comps"], key=lambda r: r[0]):
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
            for r in sorted(got["edges"], key=lambda r: r[7]):
                g.edges[(loc(r[0]), loc(r[1]))] = Edge(float(r[2]), r[3], r[4], r[5], r[6])
        for r in sorted(got["aliases"], key=lambda r: r[0]):
            g.names[r[1]] = loc(r[2])
        for r in got["shortcuts"]:
            g.shortcuts[(loc(r[0]), loc(r[1]))] = r[2]
        g.seq = got["meta"][0][0] if got["meta"] else 0
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
    remembers = True      # apply(ops, incident=...) also writes the learner's memory (incident, alerts, postmortem, lessons)

    def apply(self, ops, incident=None):
        """Translate learner ops into Cypher. Mirrors ghostwalk.learn.update.apply() op by op.
        incident (optional): {"seq", "name", "alerts", "postmortem"}; when given, the memory graph is written in the same step (before the revision is bumped)."""
        base = self._need_co()
        gid = lambda x: base + x
        names = self.snapshot().names if incident is not None else {}          # name -> local id (the write-through cache: no read)
        jobs = {"meta": ("MATCH (m {id: $id}) RETURN m.seq AS seq, m.eo AS eo, m.ao AS ao, m.mo AS mo", {"id": base + META_LOCAL})}
        if incident is not None and any(o["op"] in ("confirm", "reweight", "drop_edge") for o in ops):
            jobs["lessons"] = ("MATCH (l:Lesson {co: $co}) RETURN l.id AS id, l.src AS src, l.dst AS dst, l.state AS state", {"co": base})
        if any(o["op"] in ("root", "observe") for o in ops):          # current counters of the whole company in one read
            jobs["counters"] = ("MATCH (c:Component {co: $co}) RETURN c.id AS id, c.rc AS rc, c.aff AS aff, c.miss AS miss", {"co": base})
        if any(o["op"] in ("add_edge", "confirm") for o in ops):
            jobs["edges"] = ("MATCH (a:Component {co: $co})-[e:DEPENDS_ON]->(b:Component) RETURN a.id AS u, b.id AS v, e.conf AS conf, e.o AS o", {"co": base})
        if any(o["op"] == "shortcut" for o in ops):
            jobs["shortcuts"] = ("MATCH (a:Component {co: $co})-[s:SHORTCUT]->(b:Component) RETURN a.id AS u, b.id AS v, s.n AS n", {"co": base})
        got = self._par(jobs)                                          # independent reads, issued together
        seq, eo, ao, mo = got["meta"][0]
        mo = mo or 0
        mem = _Memory(self, base, names, incident)
        for r in got.get("lessons", []):
            if r[3] != "decayed":
                mem.lesson_of[(r[1] - base, r[2] - base)] = r[0]
        counters = {r[0] - base: {"rc": r[1], "aff": r[2], "miss": r[3]} for r in got.get("counters", [])}
        existing = {(r[0] - base, r[1] - base): {"conf": r[2], "o": r[3]} for r in got.get("edges", [])}
        shortcuts = {(r[0] - base, r[1] - base): r[2] for r in got.get("shortcuts", [])}

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
                mem.proposed(o, ordinal)
            elif k == "confirm":
                prev = existing[(o["u"], o["v"])]
                prev["conf"] += 1
                self._set_edge(o["u"], o["v"], w=o["w"], cost=cost_of(o["w"]), conf=prev["conf"])
                mem.confirmed(o, prev["conf"])
            elif k == "reweight":
                self._set_edge(o["u"], o["v"], w=o["w"], cost=cost_of(o["w"]))
                mem.reweighted(o)
            elif k == "drop_edge":
                self._q("MATCH (a {id: $u})-[e:DEPENDS_ON]->(b {id: $v}) DELETE e", u=gid(o["u"]), v=gid(o["v"]))
                existing.pop((o["u"], o["v"]), None)
                mem.decayed(o)
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
        mo = mem.write(ops, mo)                # the learner's memory, before the revision bump (the bump stays the last write)
        self._write_meta(seq + 1, eo, ao, mo)
        self._write_through(ops, seq)

    def _write_through(self, ops, seq_before):
        """Apply the identical change to the cached graph, then check the revision HydraDB reports. Anything unexpected drops the cache (a full re-read follows)."""
        if self.mode != "cached" or self._cache is None:
            return
        (co, rev), cached = self._cache
        if co != self.co or rev != seq_before:                   # the cache was not at the revision this write started from: do not extend it
            self._cache = None
            return
        g = self._copy(cached)
        learner.apply(g, ops)                                    # the learner's own semantics; bumps seq by one
        reported = self.revision()                               # the revision HydraDB now holds
        if reported == g.seq:
            self._cache = ((co, reported), g)
        else:
            self.disagreements += 1
            self._cache = None

    def _set_edge(self, u, v, **props):
        base = self._need_co()
        sets = ", ".join(f"e.{k} = ${k}" for k in props)
        self._q("MATCH (a {id: $u})-[e:DEPENDS_ON]->(b {id: $v}) SET " + sets, u=base + u, v=base + v, **props)

    # ---- cleanup --------------------------------------------------------------------------
    def drop(self):
        """Delete everything of the current company (components, aliases, meta and the memory nodes), in batches of at most 1024 ids."""
        if self.co is None:
            return
        self._cache = None                      # the revision cache must not outlive the data it describes
        ids = [r[0] for r in self._rows("MATCH (n:Component {co: $co}) RETURN n.id AS id", co=self.co)]
        ids += [r[0] for r in self._rows("MATCH (n:Alias {co: $co}) RETURN n.id AS id", co=self.co)]
        ids += [r[0] for r in self._rows("MATCH (n:GwMeta {co: $co}) RETURN n.id AS id", co=self.co)]
        for label in ("Incident", "Alert", "Postmortem", "Lesson"):
            ids += [r[0] for r in self._rows(f"MATCH (n:{label} {{co: $co}}) RETURN n.id AS id", co=self.co)]
        for chunk in self._batches([{"id": i} for i in ids]):
            self._q("UNWIND $rows AS row MATCH (n {id: row.id}) DETACH DELETE n", rows=chunk)
