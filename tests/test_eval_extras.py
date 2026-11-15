import pathlib, re
from eval.runner import load, run_company
from eval import tune_pagerank
from ghostwalk.engine.walk import walk, _limited_best
from ghostwalk.graph.state import GraphState
from gwsim.world import official_view
from eval.runner import _View
import pytest

DEV = pathlib.Path("data/dev")
pytestmark = pytest.mark.skipif(not DEV.exists(), reason="run `make data` first")


def test_pagerank_tuning_refuses_test_split():
    with pytest.raises(AssertionError):
        tune_pagerank.tune("test")


def test_tuning_module_never_names_the_test_split():
    src = pathlib.Path(tune_pagerank.__file__).read_text()
    assert not re.search(r"""load\(\s*['"]test""", src)


def test_repeat_path_is_causal():
    co = load("dev")[0]
    rows = run_company(co, "deepest")
    seen = set()
    for r, inc in zip(rows, co["incidents"]):
        pair = (inc["root"], inc["entry"])
        assert r["repeat_path"] == (pair in seen)
        seen.add(pair)
    assert not rows[0]["repeat_path"]


def test_reach_hook_matches_default_walk():
    co = load("dev")[0]
    g = GraphState.from_official(official_view(_View(co)))
    out_adj, in_adj = g.out_adj(), g.in_adj()
    reach = lambda v, d, h: _limited_best(out_adj if d == "out" else in_adj, v, h)
    inc = co["incidents"][3]
    assert walk(g, inc["alerts"]).ranking == walk(g, inc["alerts"], reach=reach).ranking


def test_runner_records_latency_and_snapshots():
    co = load("dev")[0]
    tr = {}
    rows = run_company(co, "ghostwalk", trace=tr, snap_every=10)
    assert all(r["ms"] >= 0 for r in rows)
    assert [s["after"] for s in tr["snaps"]] == [10, 20, 30, 40, 50, 60]
