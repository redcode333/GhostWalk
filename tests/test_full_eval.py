import numpy as np
from eval.full_eval import pooled, bootstrap, summarize


def rows(ranks, seq0=0):
    return [{"rank": r, "seq": seq0 + i, "repeat": False, "repeat_path": False} for i, r in enumerate(ranks)]


def test_pooled_counts_hits_over_companies():
    tab = np.array([[3.0, 4.0], [1.0, 4.0]])
    assert pooled(tab) == 0.5
    assert pooled(tab, [0]) == 0.75


def test_summarize_ac1_ac3():
    t = summarize({"a": rows([1, 2, None, 3]), "b": rows([1, 1])}, ["a", "b"])
    assert t["ac1"].tolist() == [[1, 4], [2, 2]]
    assert t["ac3"].tolist() == [[3, 4], [2, 2]]


def test_bootstrap_ci_brackets_point_and_is_seeded():
    tabs = {"x": np.array([[8.0, 10.0]] * 6 + [[4.0, 10.0]] * 4), "y": np.array([[5.0, 10.0]] * 10)}
    a, d = bootstrap(tabs, 300, seed=1, pairs=[("x", "y")])
    b, _ = bootstrap(tabs, 300, seed=1, pairs=[("x", "y")])
    assert a == b
    assert a["x"]["ci95"][0] <= a["x"]["point"] <= a["x"]["ci95"][1]
    assert d["x - y"]["point"] > 0 and d["x - y"]["ci95"][0] > 0
