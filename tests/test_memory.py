"""The learner's memory lives in HydraDB: lessons are nodes linked to the postmortems that taught them and the incidents that confirmed them,
and a restarted process reads the learned graph back. Skips cleanly when HydraDB is down (see conftest)."""
import pytest
from eval.runner import run_company
from ghostwalk.api.workspace import Workspace
from ghostwalk.graph.hydra import HydraGraph
from tests.test_parity import dev_picks, state_equal


def _ranking(inc):
    return [(r["id"], r["confidence"]) for r in inc["verdict"]["ranking"]]


def test_every_lesson_is_linked_to_its_postmortem_and_confirmations(make_hydra):
    co = dev_picks()[1]
    co = {**co, "incidents": co["incidents"][:30]}
    hg = make_hydra()
    run_company(co, "ghostwalk", backend=hg)
    # the schema: one Incident and one Postmortem per incident, alerts on services
    n = lambda q: hg._rows(q, co=hg.co)[0][0]
    assert n("MATCH (i:Incident {co: $co}) RETURN count(*) AS c") == 30
    assert n("MATCH (p:Postmortem {co: $co})-[:ABOUT]->(i:Incident) RETURN count(*) AS c") == 30
    assert n("MATCH (i:Incident {co: $co})-[:RAISED]->(a:Alert) RETURN count(*) AS c") == n("MATCH (a:Alert {co: $co}) RETURN count(*) AS c")
    lessons = hg.lessons()
    assert lessons, "30 incidents with hidden edges must teach at least one lesson"
    g = HydraGraph(run_id=hg.run_id, mode="cold")
    g.co = hg.co
    graph = g.snapshot()
    for les in lessons:
        why = hg.why_edge(les["src"], les["dst"])
        mine = next(x for x in why["lessons"] if x["id"] == les["id"])
        assert len(mine["taught_by"]) == 1                      # proposed by exactly one postmortem
        assert mine["taught_by"][0]["seq"] == mine["created_seq"]
        if mine["state"] == "confirmed":
            assert mine["confirmed_by"], "a confirmed lesson names the incident that confirmed it"
        if mine["state"] != "decayed":                          # the Lesson's w follows the DEPENDS_ON edge
            e = graph.edges[(graph.names[les["src"]], graph.names[les["dst"]])]
            assert abs(e.w - mine["w"]) < 1e-9 and e.origin == "learned"
        else:
            assert (graph.names[les["src"]], graph.names[les["dst"]]) not in graph.edges
    # impact: the incidents that taught or confirmed a lesson are among the past incidents whose paths use it
    les = next((x for x in lessons if x["state"] == "confirmed"), lessons[0])
    why = hg.why_edge(les["src"], les["dst"])
    mine = next(x for x in why["lessons"] if x["id"] == les["id"])
    impact = hg.lesson_impact(les["id"])
    seen = {x["seq"] for x in impact["incidents"]}
    assert {x["seq"] for x in mine["taught_by"]} <= seen and impact["services"]
    assert les["src"] in impact["services"]


def test_why_edge_for_an_official_edge_has_no_lesson(make_hydra):
    co = dev_picks()[0]
    hg = make_hydra()
    g = hg.fresh(co)
    (u, v), _ = next(iter(g.edges.items()))
    r = hg.why_edge(g.components[u]["name"], g.components[v]["name"])
    assert r["edge"]["origin"] == "official" and r["lessons"] == []


def test_a_restarted_process_ranks_incident_21_identically(make_hydra):
    """20 incidents with learning through the workspace, then a brand-new Workspace (no state file) attaches to HydraDB:
    its ranking for incident 21 equals the one the first process gave and the in-memory learner's."""
    hg1 = make_hydra()
    ws1 = Workspace(None, demo_incidents=20, store="hydradb", hydra=hg1)
    twin = Workspace(None, demo_incidents=20, store="memory")
    nxt = ws1.company["incidents"][20]["alerts"]
    before = _ranking(ws1.ingest_alerts(nxt, source="test"))
    twin_rank = _ranking(twin.ingest_alerts(nxt, source="test"))
    assert before == twin_rank                                           # parity with the in-memory learner
    base = hg1.co
    del ws1                                                              # the process dies; HydraDB keeps everything
    hg2 = HydraGraph(run_id=hg1.run_id, mode="cached")
    hg2._next_company = 1
    ws2 = Workspace(None, demo=False, store="hydradb", hydra=hg2)        # new process: no state file, same HydraDB
    assert hg2.co == base and hg2.full_reads == 1                        # one full read at startup
    after = _ranking(ws2.ingest_alerts(nxt, source="test"))
    assert after == before
    assert len(ws2.hy.lessons()) > 0
    state_equal(ws2.g, twin.g)                                           # the whole learned graph came back


def test_graph_retrieval_finds_past_incidents_by_neighbourhood(make_hydra):
    co = dev_picks()[1]
    co = {**co, "incidents": co["incidents"][:12]}
    hg = make_hydra()
    run_company(co, "ghostwalk", backend=hg)
    cur = co["incidents"][5]["alerts"]
    got = hg.similar_incidents(cur, k=5)
    assert 1 <= len(got) <= 5 and all(0 <= seq < 12 for seq, _ in got)
    scores = [sc for _, sc in got]
    assert scores == sorted(scores, reverse=True) and 5 in [seq for seq, _ in got]      # the incident with exactly these alerts overlaps fully
    assert hg.similar_incidents([{"name": "no-such-service", "t": 0.0}]) == []
    assert hg.index_rebuilds == 0                                   # the index followed the write-through path; nothing was scanned
    for inc in co["incidents"]:                                     # the fast path returns exactly what the HydraDB traversal returns
        assert hg.similar_incidents(inc["alerts"]) == hg.similar_incidents_traversal(inc["alerts"])
    cold = HydraGraph(run_id=hg.run_id, mode="cached")              # a new process: the index is rebuilt once from HydraDB, same answers
    cold.attach(hg.co)
    assert cold.similar_incidents(cur) == got and cold.index_rebuilds == 1
