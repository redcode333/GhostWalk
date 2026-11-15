"""The optimised walk() must rank exactly like the implementation it replaced (tests/reference_walk.py is a verbatim copy of it),
on every incident of every dev and TEST company, through the whole online learning loop. Inference only: nothing here tunes anything."""
import pathlib
import pytest
from eval import runner
from eval.runner import load, run_company
import reference_walk

DATA = pathlib.Path("data")
SPLITS = [s for s in ("dev", "test") if (DATA / s).exists()]
pytestmark = pytest.mark.skipif(not SPLITS, reason="run `make data` first")


def rankings(co, walk_fn, monkeypatch):
    monkeypatch.setattr(runner, "walk", walk_fn)
    tr = {}
    run_company(co, "ghostwalk", trace=tr)
    return tr["rankings"]


@pytest.mark.parametrize("split", SPLITS)
def test_identical_rankings_on_every_incident(split, monkeypatch):
    from ghostwalk.engine.walk import walk as fast
    n = 0
    for co in load(split):
        new = rankings(co, fast, monkeypatch)
        old = rankings(co, reference_walk.walk, monkeypatch)
        assert len(new) == len(old)
        for a, b in zip(new, old):
            assert {c for c, _ in a} == {c for c, _ in b}, co["name"]
            for (ca, sa), (cb, sb) in zip(a, b):
                assert abs(sa - sb) < 1e-9, co["name"]               # same score at every rank ...
                assert ca == cb or abs(sa - sb) < 1e-9               # ... and the same candidate unless two scores tie to ~1e-14 (summation order)
            assert not a or a[0][0] == b[0][0] or abs(a[0][1] - b[0][1]) < 1e-9
            n += 1
    assert n >= 600


def test_adjacency_is_cached_per_revision_and_invalidated_by_learning():
    from ghostwalk.graph.state import GraphState, Edge
    from ghostwalk.learn import update
    g = GraphState(components={0: {"name": "a", "kind": "service", "tier": 0}, 1: {"name": "b", "kind": "service", "tier": 1}})
    g.edges[(0, 1)] = Edge(0.7)
    first = g.out_adj()
    assert g.out_adj() is first and g.in_adj() is g._adj[2]               # built once, reused
    update.apply(g, [{"op": "reweight", "u": 0, "v": 1, "w": 0.9, "seq": 0}])
    assert g.out_adj() is not first and g.out_adj()[0] == [(1, 0.9)]      # a weight change rebuilds it
    g.edges[(1, 0)] = Edge(0.5)
    assert (1, 0) in [(1, v) for v, _ in g.out_adj()[1]]                  # a changed edge count is noticed too
