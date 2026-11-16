"""The cumulative learning curves in results.json: they end at the whole-run numbers, and the stored per-incident correctness reproduces the declared totals."""
import json, pathlib
ROOT = pathlib.Path(__file__).resolve().parent.parent
R = json.loads((ROOT / "results.json").read_text(encoding="utf8"))
LC = R["learning_curve"]


def test_final_cumulative_gains_equal_the_whole_run_numbers_to_a_tenth_of_a_point():
    g = LC["cumulative_gain"]["series"]
    whole_gw = R["paired"]["ac1"]["ghostwalk - learning_off"]["point"]
    whole_pl = R["methods"]["placebo"]["ac1"]["point"] - R["methods"]["learning_off"]["ac1"]["point"]
    assert g["ghostwalk_minus_learning_off"][-1]["n"] == 60 and g["placebo_minus_learning_off"][-1]["n"] == 60
    assert abs(g["ghostwalk_minus_learning_off"][-1]["gain"] - whole_gw) < 0.001
    assert abs(g["placebo_minus_learning_off"][-1]["gain"] - whole_pl) < 0.001


def test_bands_bracket_the_point_and_the_cumulative_accuracy_ends_at_the_whole_run_value():
    for series in LC["cumulative_gain"]["series"].values():
        assert all(p["lo"] <= p["gain"] <= p["hi"] for p in series)
    for lab, s in LC["cumulative_acc"]["series"].items():
        assert abs(s[-1]["ac1"] - R["methods"][lab]["ac1"]["point"]) < 0.001 and all(p["lo"] <= p["ac1"] <= p["hi"] for p in s)


def test_stored_per_incident_correctness_reproduces_the_declared_totals():
    pi = LC["per_incident"]
    n = R["meta"]["incidents"]
    for lab in ("ghostwalk", "learning_off", "placebo", "oracle"):
        hits = sum(s.count("1") for s in pi["arms"][lab].values())
        assert hits == round(R["methods"][lab]["ac1"]["point"] * n)
    assert sum(s.count("1") for s in pi["arms"]["ghostwalk"].values()) == R["meta"]["ac1_history"][-1]["hits"] == 1376
