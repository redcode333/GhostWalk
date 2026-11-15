"""Tune the personalized-PageRank baseline on DEV only, so it gets the same treatment as the engine.

    python eval/tune_pagerank.py            # writes eval/pagerank_tuned.json

Grid: restart probability x edge direction x edge weighting x onset-weighted restart = 72 settings.
The engine's own dev search is not recorded in the repo (HANDOFF.md lists only the fitted values), so the
budget here is a stated choice, not a copy of it. Selection: highest dev AC@1, ties -> higher AC@3, then grid order.
Nothing in this file reads data/test.
"""
from __future__ import annotations
import itertools, json, pathlib, sys, time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from eval.runner import load, run_company, acc, TUNED
from baselines import simple

GRID = {"restart": [0.05, 0.10, 0.15, 0.25, 0.35, 0.50], "direction": ["dep", "rev", "both"],
        "weighted": [True, False], "onset": [False, True]}


def tune(split="dev", root="data"):
    assert split != "test", "PageRank tuning must never touch the TEST split"
    cos = load(split, root)
    results = []
    for vals in itertools.product(*GRID.values()):
        cfg = dict(zip(GRID, vals))
        rows = [r for co in cos for r in run_company(co, "pagerank", pr=cfg)]
        results.append({**cfg, "ac1": acc(rows), "ac3": acc(rows, 3)})
    best = max(enumerate(results), key=lambda t: (t[1]["ac1"], t[1]["ac3"], -t[0]))[1]
    chosen = {k: best[k] for k in GRID}
    default = next(r for r in results if all(r[k] == simple.PR_DEFAULT[k] for k in GRID)) if all(
        any(r[k] == simple.PR_DEFAULT[k] for r in results) for k in GRID) else None
    return {"split": split, "budget": len(results), "grid": GRID, "chosen": chosen,
            "dev_ac1_chosen": best["ac1"], "dev_ac1_untuned_default": default["ac1"] if default else None,
            "untuned_default": simple.PR_DEFAULT, "all": results}


if __name__ == "__main__":
    t = time.time()
    out = tune()
    TUNED.write_text(json.dumps(out, indent=1))
    print(f"{out['budget']} settings in {time.time()-t:.0f}s  chosen {out['chosen']}  dev AC@1 {out['dev_ac1_chosen']:.3f} "
          f"(untuned default {out['dev_ac1_untuned_default']:.3f})")
