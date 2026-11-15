"""Fit the change-evidence weight on DEV only: GAMMA in {0, .25, .5, 1} x TAU in {5, 15, 30} minutes.

    python eval/tune_changes.py       # writes eval/changes_tuned.json

Selection: highest DEV AC@1 of ghostwalk with changes. If nothing beats gamma=0 (the current engine) the chosen gamma is 0
and the result is reported as "tried, no gain". Never reads data/test.
"""
from __future__ import annotations
import itertools, json, pathlib, sys, time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from eval.runner import load, run_company, acc, CHANGES_TUNED

GAMMAS, TAUS = (0.0, 0.25, 0.5, 1.0), (5.0, 15.0, 30.0)


def tune(split="dev", root="data"):
    assert split != "test", "change-evidence tuning must never touch the TEST split"
    cos = load(split, root)
    base = acc([r for co in cos for r in run_company(co, "ghostwalk")])
    grid = []
    for g, t in itertools.product(GAMMAS, TAUS):
        rows = [r for co in cos for r in run_company(co, "ghostwalk", use_changes=True, gamma=g, tau=t)]
        grid.append({"gamma": g, "tau": t, "ac1": acc(rows), "ac3": acc(rows, 3)})
    best = max(enumerate(grid), key=lambda x: (x[1]["ac1"], -x[1]["gamma"], -x[0]))[1]
    gain = best["ac1"] - base
    chosen = {"gamma": best["gamma"], "tau": best["tau"]} if gain > 0.002 else {"gamma": 0.0, "tau": 15.0}
    return {"split": split, "grid": grid, "dev_ac1_without_changes": base, "dev_ac1_best": best["ac1"], "dev_gain": gain,
            "chosen": chosen, "beats_current_engine_on_dev": gain > 0.002,
            "verdict": "kept: beats the current engine on DEV" if gain > 0.002 else "tried, no gain: stays off"}


if __name__ == "__main__":
    t = time.time()
    out = tune()
    CHANGES_TUNED.write_text(json.dumps(out, indent=1))
    print(f"{len(out['grid'])} settings in {time.time()-t:.0f}s; dev AC@1 without {out['dev_ac1_without_changes']:.3f}, best {out['dev_ac1_best']:.3f} "
          f"(gamma={out['chosen']['gamma']}, tau={out['chosen']['tau']}); {out['verdict']}")
    for g in out["grid"]:
        print(f"  gamma {g['gamma']:<4} tau {g['tau']:<4} AC@1 {g['ac1']:.3f}")
