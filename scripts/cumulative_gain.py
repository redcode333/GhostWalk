"""Cumulative learning curves from per-incident TEST correctness, written to results.json under learning_curve.

    python scripts/cumulative_gain.py --replay-test    replays the frozen engine and config once on the TEST incidents to get per-incident correctness (no parameter changes), then computes the curves
    python scripts/cumulative_gain.py                  recomputes the curves from the stored per-incident correctness (no engine)

HARD GUARD (replay): the replay must give exactly the top-1 totals in results.json for GhostWalk, learning off, placebo and the perfect-map oracle, and every stored per-bin accuracy.
On any mismatch it stops, prints the difference and writes nothing.

Definitions (incident index n = 1..60 within each company, 30 companies, equal incident counts):
  cumulative AC@1(n)        mean correctness over incidents 1..n, all companies
  cumulative paired gain(n) mean over companies of [mean(arm, 1..n) - mean(learning off, 1..n)]; for GhostWalk and for the placebo
  95% band                  resample companies with replacement, bootstrap draws and seed from results.json meta, percentile interval
Checks: gain(60) for both lines equals the whole-run numbers in results.json to 0.1 point (also asserted in tests/test_learning_curve.py)."""
from __future__ import annotations
import json, pathlib, sys
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
LABS = ("ghostwalk", "learning_off", "placebo", "oracle")
BIN = 5


def replay(res):
    from eval.runner import load, run_company
    cos = load("test")
    names = [c["name"] for c in cos]
    runs = {"ghostwalk": {c["name"]: run_company(c, "ghostwalk") for c in cos}, "learning_off": {c["name"]: run_company(c, "learning_off") for c in cos},
            "placebo": {c["name"]: run_company(c, "ghostwalk", placebo=True) for c in cos}, "oracle": {c["name"]: run_company(c, "oracle") for c in cos}}
    flags = {lab: {c: [1 if r["rank"] == 1 else 0 for r in sorted(runs[lab][c], key=lambda r: r["seq"])] for c in names} for lab in LABS}
    n_all = res["meta"]["incidents"]
    for lab in LABS:
        hits, want = sum(map(sum, flags[lab].values())), round(res["methods"][lab]["ac1"]["point"] * n_all)
        print(f"replay {lab}: {hits} of {n_all} top-1 (results.json: {want})")
        if hits != want:
            raise SystemExit(f"GUARD FAILED: replay top-1 for {lab} is {hits}, results.json has {want}; nothing written")
    if sum(map(sum, flags["ghostwalk"].values())) != res["meta"]["ac1_history"][-1]["hits"]:
        raise SystemExit("GUARD FAILED: replay total differs from the declared TEST total; nothing written")
    stored = res["learning_curve"]["series"]
    for lab in LABS:
        for b, s in enumerate(stored[lab]):
            got = sum(sum(flags[lab][c][b * BIN:(b + 1) * BIN]) for c in names) / (len(names) * BIN)
            if abs(got - s["ac1"]) > 1e-12:
                raise SystemExit(f"GUARD FAILED: replay differs from the stored per-bin accuracy ({lab}, bin {b}); nothing written")
    return names, flags


def curves(res, names, flags):
    n_boot, seed = res["meta"]["seeds"]["bootstrap_draws"], res["meta"]["seeds"]["bootstrap"]
    arr = {lab: np.array([flags[lab][c] for c in names], dtype=float) for lab in LABS}        # companies x incidents
    n_inc = arr["ghostwalk"].shape[1]
    ns = np.arange(1, n_inc + 1)
    cum = {lab: np.cumsum(arr[lab], axis=1) / ns for lab in LABS}                              # companies x n: mean correctness over incidents 1..n
    draws = np.random.default_rng(seed).integers(0, len(names), size=(n_boot, len(names)))
    ci = lambda m: (np.percentile(m, 2.5, axis=0), np.percentile(m, 97.5, axis=0))            # m: draws x n
    acc, gain = {}, {}
    for lab in LABS:
        point = cum[lab].mean(axis=0)
        lo, hi = ci(np.stack([cum[lab][d].mean(axis=0) for d in draws]))
        acc[lab] = [{"n": int(n), "ac1": float(point[i]), "lo": float(lo[i]), "hi": float(hi[i])} for i, n in enumerate(ns)]
    for lab, key in (("ghostwalk", "ghostwalk_minus_learning_off"), ("placebo", "placebo_minus_learning_off")):
        diff = cum[lab] - cum["learning_off"]
        point = diff.mean(axis=0)
        lo, hi = ci(np.stack([diff[d].mean(axis=0) for d in draws]))
        gain[key] = [{"n": int(n), "gain": float(point[i]), "lo": float(lo[i]), "hi": float(hi[i])} for i, n in enumerate(ns)]
    return acc, gain, n_boot, seed


def check_against_results(res, gain):
    want = {"ghostwalk_minus_learning_off": res["paired"]["ac1"]["ghostwalk - learning_off"]["point"],
            "placebo_minus_learning_off": res["methods"]["placebo"]["ac1"]["point"] - res["methods"]["learning_off"]["ac1"]["point"]}
    for k, w in want.items():
        if abs(gain[k][-1]["gain"] - w) > 0.001:
            raise SystemExit(f"CHECK FAILED: gain(60) for {k} is {gain[k][-1]['gain'] * 100:.2f} pts, results.json has {w * 100:.2f} pts; nothing written")


def main():
    p = ROOT / "results.json"
    res = json.loads(p.read_text(encoding="utf8"))
    lc = res["learning_curve"]
    if "--replay-test" in sys.argv:
        names, flags = replay(res)
        lc["per_incident"] = {"note": "top-1 correctness (1 or 0) of each TEST incident in order, per company, per arm; recovered once by replaying the frozen engine and config, verified identical to the declared totals and every stored per-bin accuracy",
                              "companies": names, "arms": {lab: {c: "".join(map(str, flags[lab][c])) for c in names} for lab in LABS}}
    elif "per_incident" in lc:
        names = lc["per_incident"]["companies"]
        flags = {lab: {c: [int(ch) for ch in lc["per_incident"]["arms"][lab][c]] for c in names} for lab in LABS}
    else:
        raise SystemExit("no stored per-incident correctness: run with --replay-test (approved, once)")
    acc, gain, n_boot, seed = curves(res, names, flags)
    check_against_results(res, gain)
    band = f"95% bootstrap by company ({n_boot} draws, seed {seed})"
    lc["cumulative_acc"] = {"x_label": "Incidents seen per company", "y_label": "Cumulative AC@1", "band": band, "series": acc}
    lc["cumulative_gain"] = {"x_label": "Incidents seen per company", "y_label": "Accuracy gain over no learning (pts)", "band": band,
                             "note": "mean over companies of the arm minus learning off on incidents 1..n; the last point equals the whole-run paired gain", "series": gain}
    lc.pop("cumulative", None)                                                                  # superseded by cumulative_acc
    p.write_text(json.dumps(res, indent=2), encoding="utf8")
    g, pl = gain["ghostwalk_minus_learning_off"][-1], gain["placebo_minus_learning_off"][-1]
    print(f"cumulative gain at n=60: GhostWalk {g['gain'] * 100:+.2f} pts [{g['lo'] * 100:+.1f}, {g['hi'] * 100:+.1f}], placebo {pl['gain'] * 100:+.2f} pts [{pl['lo'] * 100:+.1f}, {pl['hi'] * 100:+.1f}]")


if __name__ == "__main__":
    main()
