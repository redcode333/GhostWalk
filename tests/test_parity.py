"""HydraDB backend parity: every walk reads the live graph from HydraDB and must give the
same answers as the in-memory backend. Skips cleanly when HydraDB is down (see conftest)."""
import math
import pytest
from eval.runner import load, run_company, _View
from gwsim.world import official_view
from ghostwalk.graph.state import GraphState, Edge
from ghostwalk.engine.walk import _limited_best

CONF_TOL = 1e-9


def dev_picks():
    """Three dev companies by size (smallest, median, largest) - chosen by code, not by hand."""
    cos = sorted(load("dev"), key=lambda c: (len(c["components"]), c["name"]))
    return [cos[0], cos[len(cos) // 2], cos[-1]]


def state_equal(a: GraphState, b: GraphState):
    assert a.components == b.components
    assert list(a.edges) == list(b.edges), "edge insertion order differs"
    for k in a.edges:
        ea, eb = a.edges[k], b.edges[k]
        assert (ea.w, ea.origin, ea.confirmations, ea.learned_from, ea.created_seq) == \
               (eb.w, eb.origin, eb.confirmations, eb.learned_from, eb.created_seq), k
    assert a.names == b.names
    assert a.root_counts == b.root_counts
    assert a.shortcuts == b.shortcuts
    assert a.affected == b.affected
    assert a.missed == b.missed
    assert a.seq == b.seq


@pytest.mark.parametrize("method", ["ghostwalk", "learning_off"])
def test_walks_identical_to_in_memory(make_hydra, method):
    for co in dev_picks():
        tm, th = {}, {}
        mem = run_company(co, method, trace=tm)
        hy = run_company(co, method, backend=make_hydra(), trace=th)
        assert len(mem) == len(hy) == len(co["incidents"])
        for rm, rh, km, kh in zip(mem, hy, tm["rankings"], th["rankings"]):
            assert [c for c, _ in km] == [c for c, _ in kh], (co["name"], rm["seq"])
            assert max(abs(x - y) for (_, x), (_, y) in zip(km, kh)) <= CONF_TOL if km else True
            assert rm["top"] == rh["top"] and rm["rank"] == rh["rank"] and rm["truth"] == rh["truth"]
            assert abs(rm["confidence"] - rh["confidence"]) <= CONF_TOL
            assert rm["graph_seq"] == rh["graph_seq"]
        state_equal(tm["final"], th["final"])


def test_round_trip_fresh_snapshot_equals_official(make_hydra):
    for co in dev_picks():
        hg = make_hydra()
        fresh = hg.fresh(co)
        expected = GraphState.from_official(official_view(_View(co)))
        state_equal(hg.snapshot(), expected)
        state_equal(fresh, expected)


def maxprod_cost(g, src, dst, max_hops=5):
    best, _ = _limited_best(g.out_adj(), src, max_hops)
    return None if dst not in best else -math.log(best[dst])


def test_best_path_cost_matches_in_memory(make_hydra):
    co = dev_picks()[1]
    hg = make_hydra()
    hg.fresh(co)
    # learn a few postmortems so weights are no longer uniform, then compare against the snapshot
    run = {}
    hg_run = make_hydra()
    run_company(co, "ghostwalk", backend=hg_run, trace=run)
    g = run["final"]
    checked = 0
    for src in list(g.components)[:12]:
        best, _ = _limited_best(g.out_adj(), src, 5)
        for dst in list(best)[:8]:
            if dst == src:
                continue
            nodes, cost = hg_run.best_path(src, dst)
            assert nodes[0] == src and nodes[-1] == dst
            assert abs(cost - maxprod_cost(g, src, dst)) <= 1e-6, (src, dst)
            checked += 1
    assert checked > 20


def test_best_path_unreachable_returns_none(make_hydra):
    hg = make_hydra()
    co = dev_picks()[0]
    hg.fresh(co)
    g = hg.snapshot()
    for src in g.components:
        best, _ = _limited_best(g.out_adj(), src, 5)
        missing = [d for d in g.components if d not in best]
        if missing:
            assert hg.best_path(src, missing[0]) is None
            return
    pytest.skip("graph fully reachable")


def test_drop_removes_company(make_hydra):
    hg = make_hydra()
    hg.fresh(dev_picks()[0])
    assert hg.snapshot().components
    hg.drop()
    assert hg.snapshot().components == {}
