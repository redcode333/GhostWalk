"""Fast unit tests: simulator determinism, walk(), propose()/apply()."""
import copy, json
import pytest
from gwsim.cli import make
from gwsim.world import official_view
from ghostwalk.graph.state import GraphState, Edge, W0_OFFICIAL, W_TENTATIVE, W_CONFIRMED
from ghostwalk.engine.walk import walk
from ghostwalk.learn import update


def small_company(seed=1000, size=40):
    return json.loads(make("layered", seed, size).to_json())


class _View:
    def __init__(self, d):
        self.components, self.official_edges = d["components"], d["official_edges"]


def official_state(co):
    return GraphState.from_official(official_view(_View(co)))


def line_graph():
    """a -> b -> c (a depends on b depends on c); c failing makes a and b alert."""
    comps = {i: {"name": n, "kind": "service", "tier": t} for i, (n, t) in enumerate([("a", 0), ("b", 1), ("c", 2)])}
    g = GraphState(components=comps)
    g.names = {c["name"]: i for i, c in comps.items()}
    g.edges = {(0, 1): Edge(0.7), (1, 2): Edge(0.7)}
    return g


# ---- simulator determinism -------------------------------------------------
def test_simulator_same_seed_same_json():
    assert make("layered", 1000, 40).to_json() == make("layered", 1000, 40).to_json()
    assert make("hub", 2000, 40).to_json() == make("hub", 2000, 40).to_json()
    assert make("real", 5000, 13).to_json() == make("real", 5000, 13).to_json()


def test_simulator_different_seed_differs():
    assert make("layered", 1000, 40).to_json() != make("layered", 1001, 40).to_json()


# ---- walk -------------------------------------------------------------------
def test_walk_finds_downstream_root():
    g = line_graph()
    v = walk(g, [{"name": "a", "t": 0.0}, {"name": "b", "t": 1.0}, {"name": "c", "t": 2.0}])
    assert v.ranking[0][0] == 2
    assert 0.0 < v.confidence <= 1.0
    assert v.entry == 0


def test_walk_empty_and_unresolved_alerts():
    g = line_graph()
    v = walk(g, [{"name": "nope", "t": 0.0}])
    assert v.ranking == [] and v.confidence == 0.0 and v.unresolved == ["nope"]


def test_walk_is_deterministic_and_pure():
    co = small_company()
    g = official_state(co)
    before = copy.deepcopy(g)
    alerts = co["incidents"][0]["alerts"]
    a, b = walk(g, alerts), walk(g, alerts)
    assert a.ranking == b.ranking and a.confidence == b.confidence
    assert g == before


def test_walk_hop_limit_restricts_reach():
    g = line_graph()
    alerts = [{"name": "a", "t": 0.0}]
    ids1 = {c for c, _ in walk(g, alerts, max_hops=1).ranking}
    ids2 = {c for c, _ in walk(g, alerts, max_hops=2).ranking}
    assert ids1 == {0, 1} and ids2 == {0, 1, 2}


def test_walk_uses_learned_root_prior():
    g = line_graph()
    alerts = [{"name": "a", "t": 0.0}, {"name": "b", "t": 1.0}]
    with_prior = dict(walk(g, alerts).ranking)
    g.root_counts[1] = 5
    boosted = dict(walk(g, alerts).ranking)
    no_prior = dict(walk(g, alerts, use_prior=False).ranking)
    assert boosted[1] > with_prior[1]
    assert no_prior[1] == with_prior[1]


# ---- propose / apply ---------------------------------------------------------
def test_propose_adds_hidden_edge_tentatively_then_confirms():
    g = line_graph()
    pm = {"root": 2, "chain": [[0, 2]], "aliases": []}
    ops = update.propose(g, pm, None, [], seq=3)
    add = [o for o in ops if o["op"] == "add_edge"]
    assert add == [{"op": "add_edge", "u": 0, "v": 2, "w": W_TENTATIVE, "seq": 3}]
    update.apply(g, ops)
    e = g.edges[(0, 2)]
    assert (e.w, e.origin, e.confirmations, e.learned_from, e.created_seq) == (W_TENTATIVE, "learned", 1, 3, 3)
    ops2 = update.propose(g, pm, None, [], seq=4)
    assert [o for o in ops2 if o["op"] == "confirm"] == [{"op": "confirm", "u": 0, "v": 2, "w": W_CONFIRMED, "seq": 4}]
    update.apply(g, ops2)
    assert g.edges[(0, 2)].w == W_CONFIRMED and g.edges[(0, 2)].confirmations == 2


def test_propose_reweights_known_edge_up():
    g = line_graph()
    ops = update.propose(g, {"root": 2, "chain": [[1, 2]]}, None, [], seq=0)
    rw = [o for o in ops if o["op"] == "reweight"]
    assert rw and rw[0]["w"] > W0_OFFICIAL
    update.apply(g, ops)
    assert g.edges[(1, 2)].w == rw[0]["w"]


def test_propose_alias_root_and_observe():
    g = line_graph()
    pm = {"root": 2, "chain": [[1, 2]], "aliases": [["c-prod", 2]]}
    ops = update.propose(g, pm, None, [{"name": "b", "t": 0}], seq=1)
    assert {"op": "alias", "name": "c-prod", "id": 2, "seq": 1} in ops
    update.apply(g, ops)
    assert g.names["c-prod"] == 2
    assert g.root_counts[2] == 1
    assert g.affected[1] == 1 and g.missed.get(1, 0) == 0     # b alerted
    assert g.affected[2] == 1 and g.missed[2] == 1            # c stayed silent
    assert g.seq == 1


def test_apply_drop_edge_and_shortcut():
    g = line_graph()
    update.apply(g, [{"op": "drop_edge", "u": 0, "v": 1, "seq": 0}, {"op": "shortcut", "entry": 0, "root": 2, "seq": 0}])
    assert (0, 1) not in g.edges and g.shortcuts == {(0, 2): 1}


def test_learning_improves_a_hidden_edge_company():
    """After a postmortem names a hidden edge, the edge is in the graph the next walk sees."""
    co = small_company()
    g = official_state(co)
    inc = next(i for i in co["incidents"] if i["postmortem"]["correct"] and i["postmortem"]["chain"])
    for u, v in inc["postmortem"]["chain"]:
        if (u, v) not in g.edges:
            ops = update.propose(g, inc["postmortem"], None, inc["alerts"], inc["seq"])
            update.apply(g, ops)
            assert (u, v) in g.edges
            return
    pytest.skip("first correct postmortem had no hidden edge")
