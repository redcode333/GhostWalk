"""Full evaluation: every method on one split, bootstrap CIs, ablations, depth sweep, poisoning, learning metrics.

    python eval/full_eval.py --split test            # `make eval`        (final run, TEST split)
    python eval/full_eval.py --split dev --quick     # `make eval-quick`  (DEV, ~2 min, writes dev_results.json)

Nothing here tunes anything. Engine settings are read from the code; PageRank settings come from
eval/pagerank_tuned.json (fitted on DEV by eval/tune_pagerank.py). Confidence intervals resample COMPANIES
(the independent unit), not incidents, and all methods share the same resamples so differences are paired.
"""
from __future__ import annotations
import argparse, datetime, json, pathlib, platform, subprocess, sys, time
import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from eval.runner import load, run_company, METHODS, pagerank_settings, TUNED
from ghostwalk.engine import walk as engine
from ghostwalk.graph.state import W_TENTATIVE
from ghostwalk.learn import update
from baselines import simple
from gwsim import cli as simcli
from gwsim.world import Knobs

EARLY, LATE = 15, 45          # incident windows (seq < EARLY, seq >= LATE)
BIN = 5                       # learning-curve bin width
SNAP_EVERY = 10               # learning metrics are read after every 10 incidents
BASELINES = ("deepest", "pagerank", "retrieval", "random")   # non-oracle comparison methods
POISON = (0.1, 0.2, 0.3)
RUN_SEED = 0

STATS = {"ac1": (1, lambda r: True), "ac3": (3, lambda r: True),
         "early": (1, lambda r: r["seq"] < EARLY), "late": (1, lambda r: r["seq"] >= LATE),
         "repeat_root": (1, lambda r: r["repeat"]), "new_root": (1, lambda r: not r["repeat"]),
         "repeat_path": (1, lambda r: r["repeat_path"]), "novel_path": (1, lambda r: not r["repeat_path"])}


def hits(rows, k=1):
    return sum(1 for r in rows if r["rank"] is not None and r["rank"] <= k)


def table(by_co, names, k=1, sel=lambda r: True):
    return np.array([[hits([r for r in by_co[c] if sel(r)], k), sum(1 for r in by_co[c] if sel(r))] for c in names],
                    dtype=float)


def summarize(by_co, names):
    """Per-company [hits, n] tables for every reported statistic."""
    return {s: table(by_co, names, k, sel) for s, (k, sel) in STATS.items()}


def pooled(tab, idx=None):
    t = tab if idx is None else tab[idx]
    n = t[:, 1].sum()
    return float(t[:, 0].sum() / n) if n else float("nan")


def _ci(v):
    return [float(np.nanpercentile(v, 2.5)), float(np.nanpercentile(v, 97.5))]


def draws_for(n, n_boot, seed):
    return np.random.default_rng(seed).integers(0, n, size=(n_boot, n))


def bootstrap(tabs, n_boot, seed, pairs=()):
    """Cluster bootstrap over companies. tabs: {label: [hits, n] table}. pairs: [(a, b)] paired differences a-b."""
    n = len(next(iter(tabs.values())))
    draws = draws_for(n, n_boot, seed)
    out = {lab: {"point": pooled(t), "ci95": _ci([pooled(t, d) for d in draws])} for lab, t in tabs.items()}
    diffs = {}
    for a, b in pairs:
        d = np.array([pooled(tabs[a], i) - pooled(tabs[b], i) for i in draws])
        diffs[f"{a} - {b}"] = {"point": pooled(tabs[a]) - pooled(tabs[b]), "ci95": _ci(d), "p_le_0": float(np.mean(d <= 0))}
    return out, diffs


def gap_closed(gw, off, orc, idx=None):
    den = pooled(orc, idx) - pooled(off, idx)
    return (pooled(gw, idx) - pooled(off, idx)) / den if den > 0 else float("nan")


def run_all(cos, label, **kw):
    t = time.time()
    by_co = {co["name"]: run_company(co, **kw) for co in cos}
    print(f"  {label:30s} {time.time() - t:5.1f}s", flush=True)
    return by_co


def git_info():
    def g(*a):
        try:
            return subprocess.check_output(["git", *a], text=True, stderr=subprocess.DEVNULL).strip()
        except Exception:
            return None
    dirty = g("status", "--porcelain", "--", ".", ":!results.json", ":!dev_results.json")
    return {"commit": g("rev-parse", "HEAD"), "short": g("rev-parse", "--short", "HEAD"), "dirty": bool(dirty)}


# ---- learning metrics --------------------------------------------------------------------------
def learning_metrics(cos, traces):
    """Hidden-edge recall/precision of the learned edges after every SNAP_EVERY incidents, and the fate of false edges."""
    points = {}
    created = confirmed = dropped = alive = alive_conf = 0
    for co in cos:
        tr = traces[co["name"]]
        true_e = {(e["u"], e["v"]) for e in co["true_edges"]}
        hidden = {(e["u"], e["v"]) for e in co["hidden_edges"]}
        for s in tr["snaps"]:
            learned = set(s["learned"])
            p = points.setdefault(s["after"], {"tp": 0, "learned": 0, "hidden": 0, "co": 0})
            p["tp"] += len(learned & true_e)
            p["learned"] += len(learned)
            p["hidden"] += len(hidden)
            p["co"] += 1
        fa, fc, fd = set(), set(), set()      # false = learned edge that is not in the true graph
        for ops in tr["ops"]:
            for o in ops:
                k = (o.get("u"), o.get("v"))
                if o["op"] == "add_edge" and k not in true_e:
                    fa.add(k)
                elif o["op"] == "confirm" and k in fa:
                    fc.add(k)
                elif o["op"] == "drop_edge" and k in fa:
                    fd.add(k)
        final = {k: e for k, e in tr["final"].edges.items() if e.origin == "learned" and k not in true_e}
        created += len(fa)
        confirmed += len(fc)
        dropped += len(fd)
        alive += len(final)
        alive_conf += sum(1 for e in final.values() if e.confirmations >= 2)
    series = [{"after": a, "recall": p["tp"] / p["hidden"] if p["hidden"] else None,
               "precision": p["tp"] / p["learned"] if p["learned"] else None,
               "learned_edges": p["learned"], "hidden_edges": p["hidden"], "companies": p["co"]}
              for a, p in sorted(points.items())]
    return {"every": SNAP_EVERY, "pooled_over_companies": True, "series": series,
            "false_edges": {"created": created, "ever_confirmed": confirmed, "decayed_dropped": dropped,
                            "alive_at_end": alive, "alive_and_confirmed_at_end": alive_conf,
                            "note": "false = learned edge absent from the true graph (comes from a wrong postmortem); "
                                    "confirmed = got a second confirmation; decayed = dropped by the reweight rule"}}


def ops_metrics(runs):
    out = {"backend": "in-memory", "hydradb": None,
           "note": "single-process wall-clock per verdict (graph snapshot + walk); HydraDB latency is measured by the "
                   "store-swap run when a HydraDB node is reachable"}
    for lab in ("ghostwalk", "learning_off", "deepest", "pagerank", "retrieval"):
        rows = [r for rs in runs[lab].values() for r in rs]
        ms = np.array([r["ms"] for r in rows])
        checks = np.array([r["rank"] if r["rank"] is not None else r["n_ranked"] + 1 for r in rows], dtype=float)
        out[lab] = {"verdict_ms_p50": float(np.percentile(ms, 50)), "verdict_ms_p95": float(np.percentile(ms, 95)),
                    "mean_checks_to_root": float(checks.mean()), "n": len(rows)}
    out["checks_definition"] = "1-based rank of the true root in the ranked list (absent from the list = list length + 1)"
    return out


def poisoning(split, names_sizes, n_boot, seed, quick):
    """Regenerate the same companies (same seeds) with a worse postmortem process and re-run."""
    out = {}
    for wm in POISON:
        cos = [simcli.make(f, s, sizes_[s], Knobs(wrong_pm=wm)) for f, s, sizes_ in names_sizes]
        cos = [json.loads(c.to_json()) for c in cos]
        names = [c["name"] for c in cos]
        gw = {c["name"]: run_company(c, "ghostwalk") for c in cos}
        off = {c["name"]: run_company(c, "learning_off") for c in cos}
        tabs = {"ghostwalk": table(gw, names), "learning_off": table(off, names)}
        ci, d = bootstrap(tabs, n_boot, seed, [("ghostwalk", "learning_off")])
        wrong = float(np.mean([not i["postmortem"]["correct"] for c in cos for i in c["incidents"]]))
        out[str(wm)] = {"wrong_pm": wm, "observed_wrong_share": wrong, "ghostwalk": ci["ghostwalk"],
                        "learning_off": ci["learning_off"], "gain": d["ghostwalk - learning_off"]}
        print(f"  poison wrong_pm={wm}: gw {ci['ghostwalk']['point']:.3f} off {ci['learning_off']['point']:.3f}", flush=True)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="test")
    ap.add_argument("--out", default=None)
    ap.add_argument("--boot", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=20261116)
    ap.add_argument("--quick", action="store_true", help="skip ablations and the depth sweep; fewer bootstrap draws")
    a = ap.parse_args()
    if a.quick:
        a.boot = min(a.boot, 500)
    out_path = a.out or ("results.json" if a.split == "test" else "dev_results.json")
    t_start = time.time()

    cos = load(a.split)
    names = [c["name"] for c in cos]
    fam = {c["name"]: c["family"] for c in cos}
    print(f"{a.split}: {len(cos)} companies, {sum(len(c['incidents']) for c in cos)} incidents", flush=True)
    pr = pagerank_settings()

    runs, traces = {}, {}
    for m in METHODS:
        if m == "ghostwalk":
            t = time.time()
            traces = {c["name"]: {} for c in cos}
            runs[m] = {c["name"]: run_company(c, m, trace=traces[c["name"]], snap_every=SNAP_EVERY, pr=pr) for c in cos}
            print(f"  {m:30s} {time.time() - t:5.1f}s", flush=True)
        else:
            runs[m] = run_all(cos, m, method=m, pr=pr)
    runs["pagerank_untuned"] = run_all(cos, "pagerank (untuned default)", method="pagerank", pr=dict(simple.PR_DEFAULT))
    t = time.time()
    pl_traces = {c["name"]: {} for c in cos}
    runs["placebo"] = {c["name"]: run_company(c, "ghostwalk", placebo=True, trace=pl_traces[c["name"]], snap_every=SNAP_EVERY)
                       for c in cos}
    print(f"  {'placebo (random postmortems)':30s} {time.time() - t:5.1f}s", flush=True)
    if not a.quick:
        for step in update.ALL_STEPS:       # ablations: drop one learner step at a time
            runs[f"ablate_{step}"] = run_all(cos, f"ablate {step}", method="ghostwalk",
                                             steps=tuple(s for s in update.ALL_STEPS if s != step))
        for h in (1, 2, 3, 4, 5):
            runs[f"depth_{h}"] = run_all(cos, f"depth {h}", method="ghostwalk", max_hops=h)

    tabs = {lab: summarize(by_co, names) for lab, by_co in runs.items()}
    engine_cfg = {k: getattr(engine, k) for k in ("EPS", "BETA", "LAM", "SILENT_ROOT", "PRIOR_ROOT", "PRIOR_SHORTCUT")}
    tuned = json.loads(TUNED.read_text()) if TUNED.exists() else None
    results = {"meta": {"split": a.split, "companies": len(cos), "incidents": sum(len(c["incidents"]) for c in cos),
                        "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                        "git": git_info(), "command": " ".join(sys.argv),
                        "seeds": {"bootstrap": a.seed, "bootstrap_draws": a.boot, "run": RUN_SEED,
                                  "world": 20261115, "company_seeds": sorted(c["seed"] for c in cos)},
                        "early_lt": EARLY, "late_ge": LATE, "engine": engine_cfg,
                        "learner": {"ETA_UP": update.ETA_UP, "DECAY_WRONG": update.DECAY_WRONG, "DROP_BELOW": update.DROP_BELOW,
                                    "W_TENTATIVE": W_TENTATIVE},
                        "steps": list(update.ALL_STEPS), "quick": a.quick,
                        "python": platform.python_version(), "numpy": np.__version__},
               "methods": {}, "paired": {}, "by_family": {}, "ablations": {}, "depth": {}}

    # -- 2. baseline fairness: the PageRank settings used here were fitted on DEV only
    results["baseline_fairness"] = {
        "pagerank": {"settings": pr, "tuned_on": tuned["split"] if tuned else None, "grid_budget": tuned["budget"] if tuned else None,
                     "grid": tuned["grid"] if tuned else None, "dev_ac1_tuned": tuned["dev_ac1_chosen"] if tuned else None,
                     "dev_ac1_untuned_default": tuned["dev_ac1_untuned_default"] if tuned else None,
                     "untuned_default": simple.PR_DEFAULT, "evaluated_once_on": a.split,
                     "note": "chosen restart probability sits on the grid boundary (0.5). The engine's own dev grid size is "
                             "not recorded in the repo, so this budget is a stated choice, not a copy of it."}}

    pairs = [("ghostwalk", "learning_off"), ("ghostwalk", "deepest"), ("ghostwalk", "pagerank"),
             ("ghostwalk", "retrieval"), ("ghostwalk", "placebo"), ("oracle", "ghostwalk")]
    for stat in STATS:
        ci, diffs = bootstrap({lab: tabs[lab][stat] for lab in runs}, a.boot, a.seed,
                              pairs if stat == "ac1" else [("ghostwalk", "learning_off")])
        for lab, v in ci.items():
            results["methods"].setdefault(lab, {})[stat] = v
        results["paired"][stat] = diffs

    # -- 1. headline: paired bootstrap vs the best non-oracle baseline, and share of the oracle gap closed
    best = max(BASELINES, key=lambda b: results["methods"][b]["ac1"]["point"])
    _, d = bootstrap({lab: tabs[lab]["ac1"] for lab in ("ghostwalk", best)}, a.boot, a.seed, [("ghostwalk", best)])
    draws = draws_for(len(names), a.boot, a.seed)
    gc = np.array([gap_closed(tabs["ghostwalk"]["ac1"], tabs["learning_off"]["ac1"], tabs["oracle"]["ac1"], i) for i in draws])
    results["headline"] = {
        "best_baseline": best, "baseline_candidates": {b: results["methods"][b]["ac1"]["point"] for b in BASELINES},
        "baseline_choice_note": "best non-oracle baseline by AC@1 on this split (favours the baseline)",
        "ghostwalk_ac1": results["methods"]["ghostwalk"]["ac1"], "best_baseline_ac1": results["methods"][best]["ac1"],
        "gain_vs_best": {"baseline": best, **d[f"ghostwalk - {best}"], "method": "paired company bootstrap"},
        "gap_closed": {"point": gap_closed(tabs["ghostwalk"]["ac1"], tabs["learning_off"]["ac1"], tabs["oracle"]["ac1"]),
                       "ci95": _ci(gc[~np.isnan(gc)]), "formula": "(ghostwalk - learning_off) / (oracle - learning_off)",
                       "ghostwalk": results["methods"]["ghostwalk"]["ac1"]["point"],
                       "learning_off": results["methods"]["learning_off"]["ac1"]["point"],
                       "oracle": results["methods"]["oracle"]["ac1"]["point"]}}

    for f in sorted(set(fam.values())):
        idx = [i for i, n in enumerate(names) if fam[n] == f]
        results["by_family"][f] = {lab: {"ac1": pooled(tabs[lab]["ac1"], idx), "ac3": pooled(tabs[lab]["ac3"], idx), "companies": len(idx)}
                                   for lab in ("ghostwalk", "learning_off", "oracle", "deepest", "pagerank", "retrieval", "random")}
    if not a.quick:
        for step in update.ALL_STEPS:
            results["ablations"][step] = results["methods"][f"ablate_{step}"]["ac1"]
        for h in (1, 2, 3, 4, 5):
            results["depth"][str(h)] = results["methods"][f"depth_{h}"]["ac1"]

    # -- 3. new vs repeat incidents (a "repeat" repeats the (root, entry-alert) path seen earlier at the same company)
    rvn = {"definition": "repeat = this incident's (root, entry alerting service) pair occurred in an earlier incident at the same company",
           "share_repeat": float(sum(tabs["ghostwalk"]["repeat_path"][:, 1]) / sum(tabs["ghostwalk"]["ac1"][:, 1])), "methods": {}}
    for lab, label in (("ghostwalk", "ghostwalk"), ("learning_off", "learning_off"), ("retrieval", "tfidf")):
        rvn["methods"][label] = {"repeat": results["methods"][lab]["repeat_path"], "novel": results["methods"][lab]["novel_path"]}
    results["repeat_vs_novel"] = rvn

    # -- 4. learning metrics, 7. ops
    results["learning_metrics"] = learning_metrics(cos, traces)
    results["learning_metrics"]["placebo_stress"] = learning_metrics(cos, pl_traces)
    results["learning_metrics"]["placebo_stress"]["note"] = (
        "the simulator's wrong postmortems keep a true causal chain, so the real run creates no false edges; the placebo run "
        "(random root and random edges) is the stress case where every learned edge is a candidate false edge")
    results["ops"] = ops_metrics(runs)

    # -- 6. learning curve in bins of BIN incidents with company-bootstrap 95% CI
    n_inc = max(len(c["incidents"]) for c in cos)
    series = {}
    for lab in ("ghostwalk", "learning_off", "placebo", "oracle"):
        pts = []
        for lo in range(0, n_inc, BIN):
            t = table(runs[lab], names, 1, lambda r, lo=lo: lo <= r["seq"] < lo + BIN)
            pts.append({"from": lo, "to": lo + BIN - 1, "ac1": pooled(t), "ci95": _ci([pooled(t, d) for d in draws])})
        series[lab] = pts
    results["learning_curve"] = {"bin": BIN, "ci": "95% company bootstrap", "series": series}

    # calibration of the ghostwalk confidence (does 0.8 mean right 80% of the time?)
    rows = [r for c in names for r in runs["ghostwalk"][c] if r["confidence"] is not None]
    edges, cal = np.linspace(0, 1, 6), []
    for lo, hi in zip(edges[:-1], edges[1:]):
        sel = [r for r in rows if lo <= r["confidence"] < hi or (hi == 1 and r["confidence"] == 1)]
        cal.append({"conf_from": float(lo), "conf_to": float(hi), "n": len(sel),
                    "mean_conf": float(np.mean([r["confidence"] for r in sel])) if sel else None,
                    "ac1": hits(sel) / len(sel) if sel else None})
    results["calibration"] = cal

    # -- 5. poisoning stress: same companies, worse postmortems
    dev_items, test_items, sizes = simcli.splits()
    items = [(f, s, sizes) for f, s in (test_items if a.split == "test" else dev_items)]
    results["poisoning"] = {"split": a.split, "levels": poisoning(a.split, items, a.boot, a.seed, a.quick)}

    results["meta"]["runtime_s"] = round(time.time() - t_start, 1)
    pathlib.Path(out_path).write_text(json.dumps(results, indent=2))
    report(results, out_path)


def report(results, out_path):
    print(f"\nwrote {out_path}")
    print(f"{'method':18s}{'AC@1 [95% CI]':26s}{'AC@3':8s}{'early':8s}{'late':8s}")
    for m in ("ghostwalk", "learning_off", "oracle", "deepest", "pagerank", "pagerank_untuned", "retrieval", "random", "placebo"):
        v = results["methods"][m]
        print(f"{m:18s}{v['ac1']['point']:.3f} [{v['ac1']['ci95'][0]:.3f}, {v['ac1']['ci95'][1]:.3f}]   "
              f"{v['ac3']['point']:.3f}   {v['early']['point']:.3f}   {v['late']['point']:.3f}")
    h = results["headline"]
    g = h["gain_vs_best"]
    print(f"\nheadline: gain vs best baseline ({g['baseline']}) {g['point']:+.3f} [{g['ci95'][0]:+.3f}, {g['ci95'][1]:+.3f}]")
    c = h["gap_closed"]
    print(f"          gap closed {c['point']:.3f} [{c['ci95'][0]:.3f}, {c['ci95'][1]:.3f}]")
    for k, r in results["repeat_vs_novel"]["methods"].items():
        print(f"  {k:13s} repeat {r['repeat']['point']:.3f}  novel {r['novel']['point']:.3f}")
    lm = results["learning_metrics"]["series"]
    print("learning (after n): " + "  ".join(f"{s['after']}: R {s['recall']:.2f} P {(s['precision'] or 0):.2f}" for s in lm))
    for k, lm_ in (("real", results["learning_metrics"]), ("placebo", results["learning_metrics"]["placebo_stress"])):
        fe = lm_["false_edges"]
        print(f"false edges ({k}): created {fe['created']} confirmed {fe['ever_confirmed']} dropped {fe['decayed_dropped']} alive {fe['alive_at_end']}")
    o = results["ops"]["ghostwalk"]
    print(f"ops: p50 {o['verdict_ms_p50']:.1f} ms  p95 {o['verdict_ms_p95']:.1f} ms  checks-to-root {o['mean_checks_to_root']:.2f}")


if __name__ == "__main__":
    main()
