"""Full held-out evaluation: every method on the TEST split, bootstrap CIs, ablations, depth sweep.

    python eval/full_eval.py [--split test] [--out results.json] [--boot 2000]

Nothing here tunes anything: engine settings are read from the code and recorded in the output.
Confidence intervals resample COMPANIES (the independent unit), not incidents.
"""
from __future__ import annotations
import argparse, json, pathlib, subprocess, sys, time
import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from eval.runner import load, run_company, METHODS
from ghostwalk.engine import walk as engine
from ghostwalk.learn import update

EARLY, LATE = 15, 45          # incident windows used throughout (seq < EARLY, seq >= LATE)
WINDOW = 10                   # learning-curve bucket size


def hits(rows, k=1):
    return sum(1 for r in rows if r["rank"] is not None and r["rank"] <= k)


def summarize(by_co, names):
    """Per-company count table -> {stat: array over companies of (hits, n)}."""
    stats = {"ac1": (1, lambda r: True), "ac3": (3, lambda r: True),
             "early": (1, lambda r: r["seq"] < EARLY), "late": (1, lambda r: r["seq"] >= LATE),
             "repeat_root": (1, lambda r: r["repeat"]), "new_root": (1, lambda r: not r["repeat"])}
    out = {}
    for s, (k, sel) in stats.items():
        out[s] = np.array([[hits([r for r in by_co[c] if sel(r)], k), sum(1 for r in by_co[c] if sel(r))]
                           for c in names], dtype=float)
    return out


def pooled(tab, idx=None):
    t = tab if idx is None else tab[idx]
    n = t[:, 1].sum()
    return float(t[:, 0].sum() / n) if n else float("nan")


def bootstrap(tabs, n_boot, seed, pairs=()):
    """Cluster bootstrap over companies. tabs: {label: count table}. pairs: [(a, b)] paired differences a-b."""
    rng = np.random.default_rng(seed)
    n = len(next(iter(tabs.values())))
    draws = rng.integers(0, n, size=(n_boot, n))
    ci = lambda v: [float(np.nanpercentile(v, 2.5)), float(np.nanpercentile(v, 97.5))]
    out = {lab: {"point": pooled(t), "ci95": ci([pooled(t, d) for d in draws])} for lab, t in tabs.items()}
    diffs = {}
    for a, b in pairs:
        d = [pooled(tabs[a], i) - pooled(tabs[b], i) for i in draws]
        diffs[f"{a} - {b}"] = {"point": pooled(tabs[a]) - pooled(tabs[b]), "ci95": ci(d),
                               "p_le_0": float(np.mean(np.array(d) <= 0))}
    return out, diffs


def run_all(cos, label, **kw):
    t = time.time()
    by_co = {co["name"]: run_company(co, **kw) for co in cos}
    print(f"  {label:28s} {time.time() - t:5.1f}s", flush=True)
    return by_co


def git_head():
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="test")
    ap.add_argument("--out", default="results.json")
    ap.add_argument("--boot", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=20261116)
    a = ap.parse_args()

    cos = load(a.split)
    names = [c["name"] for c in cos]
    fam = {c["name"]: c["family"] for c in cos}
    print(f"{a.split}: {len(cos)} companies, {sum(len(c['incidents']) for c in cos)} incidents")

    runs = {}
    for m in METHODS:
        runs[m] = run_all(cos, m, method=m)
    runs["placebo"] = run_all(cos, "placebo (random postmortems)", method="ghostwalk", placebo=True)
    # ablations: drop one learner step at a time
    for step in update.ALL_STEPS:
        steps = tuple(s for s in update.ALL_STEPS if s != step)
        runs[f"ablate_{step}"] = run_all(cos, f"ablate {step}", method="ghostwalk", steps=steps)
    # depth sweep
    depths = (1, 2, 3, 4, 5)
    for h in depths:
        runs[f"depth_{h}"] = run_all(cos, f"depth {h}", method="ghostwalk", max_hops=h)

    tabs = {lab: summarize(by_co, names) for lab, by_co in runs.items()}
    results = {"meta": {"split": a.split, "companies": len(cos), "incidents": sum(len(c["incidents"]) for c in cos),
                        "git": git_head(), "boot": a.boot, "boot_seed": a.seed, "early_lt": EARLY, "late_ge": LATE,
                        "engine": {k: getattr(engine, k) for k in ("EPS", "BETA", "LAM", "SILENT_ROOT", "PRIOR_ROOT", "PRIOR_SHORTCUT")},
                        "learner": {"ETA_UP": update.ETA_UP, "DECAY_WRONG": update.DECAY_WRONG, "DROP_BELOW": update.DROP_BELOW},
                        "steps": list(update.ALL_STEPS)},
               "methods": {}, "paired": {}, "by_family": {}, "ablations": {}, "depth": {}, "learning_curve": {}}
    pairs = [("ghostwalk", "learning_off"), ("ghostwalk", "deepest"), ("ghostwalk", "pagerank"),
             ("ghostwalk", "retrieval"), ("ghostwalk", "placebo"), ("oracle", "ghostwalk")]
    for stat in ("ac1", "ac3", "early", "late", "repeat_root", "new_root"):
        ci, diffs = bootstrap({lab: tabs[lab][stat] for lab in runs}, a.boot, a.seed, pairs if stat == "ac1" else
                              [("ghostwalk", "learning_off")])
        for lab, v in ci.items():
            results["methods"].setdefault(lab, {})[stat] = v
        results["paired"][stat] = diffs
    for f in sorted(set(fam.values())):
        idx = [i for i, n in enumerate(names) if fam[n] == f]
        results["by_family"][f] = {lab: {"ac1": pooled(tabs[lab]["ac1"], idx), "ac3": pooled(tabs[lab]["ac3"], idx),
                                         "companies": len(idx)}
                                   for lab in ("ghostwalk", "learning_off", "oracle", "deepest", "pagerank", "retrieval", "random")}
    for step in update.ALL_STEPS:
        results["ablations"][step] = results["methods"][f"ablate_{step}"]["ac1"]
    for h in depths:
        results["depth"][str(h)] = results["methods"][f"depth_{h}"]["ac1"]
    n_inc = max(len(c["incidents"]) for c in cos)
    for lab in ("ghostwalk", "learning_off", "oracle"):
        curve = []
        for lo in range(0, n_inc, WINDOW):
            rows = [r for by in (runs[lab],) for c in names for r in by[c] if lo <= r["seq"] < lo + WINDOW]
            curve.append({"from": lo, "to": lo + WINDOW - 1, "ac1": hits(rows) / max(1, len(rows))})
        results["learning_curve"][lab] = curve
    # calibration of the ghostwalk confidence (does 0.8 mean right 80% of the time?)
    rows = [r for c in names for r in runs["ghostwalk"][c] if r["confidence"] is not None]
    edges = np.linspace(0, 1, 6)
    cal = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        sel = [r for r in rows if lo <= r["confidence"] < hi or (hi == 1 and r["confidence"] == 1)]
        cal.append({"conf_from": float(lo), "conf_to": float(hi), "n": len(sel),
                    "mean_conf": float(np.mean([r["confidence"] for r in sel])) if sel else None,
                    "ac1": hits(sel) / len(sel) if sel else None})
    results["calibration"] = cal

    pathlib.Path(a.out).write_text(json.dumps(results, indent=2))
    print(f"\nwrote {a.out}")
    show = ["ghostwalk", "learning_off", "oracle", "deepest", "pagerank", "retrieval", "random", "placebo"]
    print(f"{'method':14s}{'AC@1 [95% CI]':26s}{'AC@3':8s}{'early':8s}{'late':8s}")
    for m in show:
        v = results["methods"][m]
        print(f"{m:14s}{v['ac1']['point']:.3f} [{v['ac1']['ci95'][0]:.3f}, {v['ac1']['ci95'][1]:.3f}]   "
              f"{v['ac3']['point']:.3f}   {v['early']['point']:.3f}   {v['late']['point']:.3f}")
    for k, d in results["paired"]["ac1"].items():
        print(f"  paired {k:28s} {d['point']:+.3f} [{d['ci95'][0]:+.3f}, {d['ci95'][1]:+.3f}]")
    print("ablations (AC@1 without step):", {s: round(v["point"], 3) for s, v in results["ablations"].items()})
    print("depth:", {h: round(v["point"], 3) for h, v in results["depth"].items()})


if __name__ == "__main__":
    main()
