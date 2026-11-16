"""The learning-curve series for the proof charts, written to results.json under learning_curve.paired_gain and learning_curve.cumulative.

    python scripts/learning_series.py                   uses ONLY what is already stored in results.json (no engine, no TEST run)
    python scripts/learning_series.py --replay-test     adds the paired 95% band; this replays the frozen engine on the TEST incidents once, so it must be approved first

What the stored data supports exactly:
  * paired gain per bin (point): pooled AC@1(method) minus pooled AC@1(learning off) in the same bin. Every company has the same number of incidents in every bin, so these are exact paired differences.
  * the paired 95% CIs that were stored for the whole run, for the first incidents (early) and for the last ones (late): shown as reference markers, not as a band.
  * cumulative AC@1 up to incident n: the mean of the stored per-bin accuracies up to that bin (equal bin sizes make this exact).
What it does not support: a paired bootstrap band per bin. That needs per-company per-bin hits, which were never stored (results.json kept only pooled values). --replay-test derives them by replaying the
frozen engine on the same TEST incidents (deterministic, no tuning), verifies that the replay reproduces every stored per-bin accuracy and the total top-1 hits exactly (else it writes nothing), and stores the per-company
tables so no later run needs the engine."""
from __future__ import annotations
import json, pathlib, sys
import numpy as np
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
LABS = ("ghostwalk", "learning_off", "placebo", "oracle")


def stored_series(res):
    st, BIN = res["learning_curve"]["series"], res["learning_curve"]["bin"]
    nb = len(st["ghostwalk"])
    gain = {}
    for lab, key in (("ghostwalk", "ghostwalk_minus_learning_off"), ("placebo", "placebo_minus_learning_off")):
        gain[key] = [{"from": b * BIN, "to": b * BIN + BIN - 1, "x": b * BIN + (BIN + 1) / 2, "gain": st[lab][b]["ac1"] - st["learning_off"][b]["ac1"], "ci95": None} for b in range(nb)]
    P = res["paired"]
    ref = {}
    for key, pair in (("ghostwalk_minus_learning_off", "ghostwalk - learning_off"), ("placebo_minus_learning_off", None)):
        ref[key] = {}
        if pair:
            for part, stat in (("overall", "ac1"), ("early", "early"), ("late", "late")):
                if pair in P[stat]:
                    ref[key][part] = {"gain": P[stat][pair]["point"], "ci95": P[stat][pair]["ci95"]}
    cum = {lab: [{"n": (k + 1) * BIN, "ac1": float(np.mean([st[lab][b]["ac1"] for b in range(k + 1)])), "ci95": None} for k in range(nb)] for lab in LABS}
    return gain, ref, cum


def replay_tables(res):
    from eval.full_eval import BIN
    from eval.runner import load, run_company
    cos = load("test")
    names = [c["name"] for c in cos]
    runs = {"ghostwalk": {c["name"]: run_company(c, "ghostwalk") for c in cos}, "learning_off": {c["name"]: run_company(c, "learning_off") for c in cos},
            "placebo": {c["name"]: run_company(c, "ghostwalk", placebo=True) for c in cos}, "oracle": {c["name"]: run_company(c, "oracle") for c in cos}}
    n_inc = max(len(c["incidents"]) for c in cos)
    tables = {lab: {c: [[sum(1 for r in runs[lab][c] if r["seq"] // BIN == b and r["rank"] == 1), sum(1 for r in runs[lab][c] if r["seq"] // BIN == b)] for b in range(n_inc // BIN)] for c in names} for lab in LABS}
    stored = res["learning_curve"]["series"]
    for lab in LABS:
        arr = np.array([tables[lab][c] for c in names], dtype=float)
        for b, s in enumerate(stored[lab]):
            if abs(arr[:, b, 0].sum() / arr[:, b, 1].sum() - s["ac1"]) > 1e-12:
                raise SystemExit(f"replay differs from the stored curve ({lab}, bin {b}); nothing written")
    n_all = res["meta"]["incidents"]
    for lab, key in (("ghostwalk", "ghostwalk"), ("learning_off", "learning_off"), ("placebo", "placebo"), ("oracle", "oracle")):
        hits = sum(1 for c in names for r in runs[lab][c] if r["rank"] == 1)
        want = round(res["methods"][key]["ac1"]["point"] * n_all)
        print(f"replay {lab}: {hits} of {n_all} top-1 (results.json: {want})")
        if hits != want:
            raise SystemExit(f"replay top-1 hits for {lab} ({hits}) differ from results.json ({want}); nothing written")
    total = sum(1 for c in names for r in runs["ghostwalk"][c] if r["rank"] == 1)
    if total != res["meta"]["ac1_history"][-1]["hits"]:
        raise SystemExit("replay top-1 hits differ from the stored total; nothing written")
    return names, tables


def bands(res, names, tables, gain, cum):
    from eval.full_eval import draws_for, pooled, _ci
    n_boot, seed = res["meta"]["seeds"]["bootstrap_draws"], res["meta"]["seeds"]["bootstrap"]
    draws = draws_for(len(names), n_boot, seed)
    arr = {lab: np.array([tables[lab][c] for c in names], dtype=float) for lab in LABS}
    for lab, key in (("ghostwalk", "ghostwalk_minus_learning_off"), ("placebo", "placebo_minus_learning_off")):
        for b, pt in enumerate(gain[key]):
            pt["ci95"] = _ci([pooled(arr[lab][:, b, :], d) - pooled(arr["learning_off"][:, b, :], d) for d in draws])
    for lab in LABS:
        for k, pt in enumerate(cum[lab]):
            t = arr[lab][:, :k + 1, :].sum(axis=1)
            pt["ci95"] = _ci([pooled(t, d) for d in draws])


def main():
    p = ROOT / "results.json"
    res = json.loads(p.read_text(encoding="utf8"))
    lc = res["learning_curve"]
    gain, ref, cum = stored_series(res)
    out = {"bin": lc["bin"], "x_label": "incident number at each company (bins of five)", "y_label": "AC@1 gain over learning off, percentage points", "series": gain, "reference_paired_ci": ref,
           "band": None, "source": "stored per-bin accuracies (exact paired differences: every company has the same number of incidents in every bin); no engine was run"}
    if "--replay-test" in sys.argv:
        names, tables = replay_tables(res)
        bands(res, names, tables, gain, cum)
        out.update({"band": f"95% paired company bootstrap ({res['meta']['seeds']['bootstrap_draws']} draws, seed {res['meta']['seeds']['bootstrap']})", "tables": tables,
                    "source": "per-company per-bin tables re-derived once by replaying the frozen engine on the TEST incidents, verified identical to every stored per-bin accuracy and to the top-1 total"})
    elif "tables" in lc.get("paired_gain", {}):                                # tables stored by an earlier approved run: bands without the engine
        tables = lc["paired_gain"]["tables"]
        bands(res, list(tables["ghostwalk"]), tables, gain, cum)
        out.update({"band": lc["paired_gain"]["band"], "tables": tables, "source": lc["paired_gain"]["source"]})
    lc["paired_gain"] = out
    lc["cumulative"] = {"x_label": "incident number at each company", "y_label": "cumulative AC@1", "series": cum,
                        "note": "the mean of the stored per-bin accuracies up to that bin (equal bin sizes), points at multiples of the bin width" + ("; with 95% company-bootstrap bands" if out["band"] else "; no bands (they need per-company data)")}
    p.write_text(json.dumps(res, indent=2), encoding="utf8")
    g = gain["ghostwalk_minus_learning_off"]
    pl = gain["placebo_minus_learning_off"]
    print(f"bins: {len(g)}; last bin: GhostWalk - off {g[-1]['gain'] * 100:+.1f} pts, placebo - off {pl[-1]['gain'] * 100:+.1f} pts; paired band: {'yes' if out['band'] else 'no (not stored)'}")
    print("stored paired reference:", {k: {kk: round(vv['gain'] * 100, 1) for kk, vv in v.items()} for k, v in ref.items()})


if __name__ == "__main__":
    main()
