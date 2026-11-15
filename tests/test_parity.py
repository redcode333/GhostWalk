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


def test_in_db_verdict_matches_in_memory(make_hydra):
    """Two MSpaths requests supply every reach the walk needs; the edges are never read back. Same ranking and scores as the in-memory engine."""
    from ghostwalk.engine.walk import walk
    co = dev_picks()[0]
    hg = make_hydra()
    g0 = hg.fresh(co)
    mem = GraphState.from_official(official_view(_View(co)))
    n = 0
    for inc in co["incidents"][:25]:
        want = walk(mem, inc["alerts"]).ranking
        got = hg.verdict_in_db(inc["alerts"]).ranking
        assert [c for c, _ in got] == [c for c, _ in want] or all(abs(a - b) < 1e-9 for (_, a), (_, b) in zip(got, want)), inc["seq"]
        assert len(got) == len(want) and max((abs(a - b) for (_, a), (_, b) in zip(got, want)), default=0) < 1e-9
        n += 1
    assert n == 25


def test_cached_mode_is_write_through_and_checks_the_revision(make_hydra):
    co = dev_picks()[0]
    hg = make_hydra()
    hg.fresh(co)                                                              # seeds the cache with the graph it just wrote (revision 0)
    a = hg.snapshot()
    assert hg.snapshot() is a and hg.full_reads == 0 and hg.hits == 2         # same revision: served from the cache, never re-read
    from ghostwalk.learn import update
    inc = co["incidents"][0]
    ops = update.propose(a, inc["postmortem"], None, inc["alerts"], a.seq)
    hg.apply(ops)                                                             # the write bumps the revision AND is applied to the cached graph
    b = hg.snapshot()
    assert b is not a and b.seq == a.seq + 1 and hg.full_reads == 0           # a new graph object (callers' copies are untouched), still no re-read
    assert a.seq == 0                                                         # the graph the caller held was not mutated
    cold = make_hydra()
    cold.mode = "cold"
    cold.co = hg.co
    assert cold.snapshot() is not cold.snapshot()                             # cold mode never caches
    state_equal(cold.snapshot(), b)                                           # ... and what HydraDB holds equals the write-through graph


def test_write_through_cache_60_incidents_rankings_equal_in_memory_and_no_full_reread(make_hydra):
    """While learning, every write is also applied to the cached graph, so every verdict is served from the cache (a revision check only):
    identical rankings and final state vs the in-memory engine, and no full graph re-read at all."""
    co = dev_picks()[1]
    assert len(co["incidents"]) >= 60
    tm, th = {}, {}
    mem = run_company(co, "ghostwalk", trace=tm)
    hg = make_hydra()
    hy = run_company(co, "ghostwalk", backend=hg, trace=th)
    for rm, rh, km, kh in zip(mem, hy, tm["rankings"], th["rankings"]):
        assert [c for c, _ in km] == [c for c, _ in kh], rm["seq"]
        assert max(abs(x - y) for (_, x), (_, y) in zip(km, kh)) <= CONF_TOL if km else True
        assert abs(rm["confidence"] - rh["confidence"]) <= CONF_TOL and rm["rank"] == rh["rank"]
    assert len(hy) >= 60
    assert hg.full_reads == 0 and hg.disagreements == 0, (hg.full_reads, hg.disagreements)      # no re-read, not even at startup: fresh() seeded the cache
    assert hg.hits >= len(hy)                                                                     # every verdict was a revision-checked cache hit
    cached = hg.snapshot()
    state_equal(cached, tm["final"])
    cold = make_hydra()
    cold.mode, cold.co = "cold", hg.co
    state_equal(cold.snapshot(), cached)                                                          # the write-through graph equals what HydraDB really holds


def test_cache_is_never_served_when_hydradb_is_ahead(make_hydra):
    """Another writer bumps the revision: the next verdict must re-read the whole graph instead of serving the stale cache."""
    from ghostwalk.learn import update
    co = dev_picks()[0]
    a = make_hydra()
    a.fresh(co)
    base_graph = a.snapshot()
    b = make_hydra()
    b.co, b.mode = a.co, "cached"                                   # a second client on the same company
    inc = co["incidents"][0]
    b.apply(update.propose(b.snapshot(), inc["postmortem"], None, inc["alerts"], inc["seq"]))
    assert a.full_reads == 0
    fresh_view = a.snapshot()                                       # a's cache is behind HydraDB's revision
    assert a.full_reads == 1 and fresh_view.seq == base_graph.seq + 1
    state_equal(fresh_view, b.snapshot())
    # a write whose revision HydraDB does not confirm drops the cache rather than extending it
    a._cache = ((a.co, 0), a._copy(base_graph))                     # pretend a cache stuck at an old revision
    a.apply(update.propose(fresh_view, co["incidents"][1]["postmortem"], None, co["incidents"][1]["alerts"], 1))
    assert a._cache is None
