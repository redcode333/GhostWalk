import numpy as np
import pytest
from gwsim.cli import make
from gwsim.world import Knobs
from ghostwalk.engine.walk import walk, changes_before
from ghostwalk.graph.state import GraphState, Edge
from eval import tune_changes


def company(**kw):
    import json
    return json.loads(make("layered", 1000, 40, Knobs(n_incidents=30, **kw)).to_json())


def test_change_events_never_alter_existing_fields():
    a, b = company(p_root_change=0.0, r_noise=0.0), company(p_root_change=1.0, r_noise=5.0)
    for x, y in zip(a["incidents"], b["incidents"]):
        assert {k: v for k, v in x.items() if k != "changes"} == {k: v for k, v in y.items() if k != "changes"}
    assert all(i["changes"] == [] for i in a["incidents"])


def test_root_change_probability_and_window():
    co = company(p_root_change=1.0, r_noise=0.0)
    names = {c["id"]: c["name"] for c in co["components"]}
    for inc in co["incidents"]:
        t0 = min(al["t"] for al in inc["alerts"])
        (ch,) = inc["changes"]
        assert ch["service"] == names[inc["root"]]
        assert -1800 - 600 <= ch["ts"] - t0 <= -60 + 600          # 1-30 min before the first alert, plus up to 10 min of jitter
    none = company(p_root_change=0.0, r_noise=0.0)
    assert all(i["changes"] == [] for i in none["incidents"])


def test_distractors_are_poisson_and_not_on_the_root():
    co = company(p_root_change=0.0, r_noise=2.0)
    n = [len(i["changes"]) for i in co["incidents"]]
    assert 1.0 < np.mean(n) < 3.2
    names = {c["id"]: c["name"] for c in co["components"]}
    assert all(ch["service"] != names[i["root"]] for i in co["incidents"] for ch in i["changes"])
    assert all(set(ch) == {"service", "ts", "kind", "ref"} for i in co["incidents"] for ch in i["changes"])   # no label field


def tiny():
    g = GraphState(components={0: {"name": "front", "kind": "service", "tier": 0}, 1: {"name": "a", "kind": "service", "tier": 1}, 2: {"name": "b", "kind": "service", "tier": 1}})
    g.names = {"front": 0, "a": 1, "b": 2}
    g.edges = {(0, 1): Edge(0.7), (0, 2): Edge(0.7)}
    return g


def test_changes_before_ignores_later_changes_and_unknown_services():
    g = tiny()
    out = changes_before(g, [{"service": "a", "ts": -600}, {"service": "a", "ts": -60}, {"service": "b", "ts": 30}, {"service": "zzz", "ts": -10}], first_ts=0)
    assert out == {1: 1.0}


def test_change_evidence_breaks_a_tie_and_gamma_zero_is_the_old_engine():
    g = tiny()
    alerts = [{"name": "front", "signal": "e", "t": 0.0}, {"name": "a", "signal": "e", "t": 5.0}, {"name": "b", "signal": "e", "t": 5.0}]
    base = walk(g, alerts)
    assert walk(g, alerts, changes={2: 1.0}, gamma=0.0).ranking == base.ranking
    boosted = walk(g, alerts, changes={2: 1.0}, gamma=1.0, tau=15)
    assert boosted.ranking[0][0] == 2
    far = dict(walk(g, alerts, changes={2: 120.0}, gamma=1.0, tau=5).ranking)
    near = dict(walk(g, alerts, changes={2: 1.0}, gamma=1.0, tau=5).ranking)
    assert near[2] > far[2]                      # f = exp(-dt/tau) decays with age


def test_tuning_refuses_test():
    with pytest.raises(AssertionError):
        tune_changes.tune("test")
