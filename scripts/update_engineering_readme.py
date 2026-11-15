"""Regenerates the README Engineering section (change evidence, gw diff, Search-vs-walk numbers) from results.json."""
import json, pathlib
R = pathlib.Path(__file__).resolve().parent.parent
d = json.loads((R / "results.json").read_text(encoding="utf8"))
c = d["change_evidence"]
pts = lambda x: f"{x * 100:+.1f}"
ci = lambda g: f"{pts(g['ci95'][0])} to {pts(g['ci95'][1])}"
grid = {(s["p_root"], s["r_noise"]): s for s in c["sensitivity"]}
rows = []
for p in (0.2, 0.5, 0.8):
    cells = []
    for r in (0.5, 2.0, 5.0):
        g = grid[(p, r)]["gain"]
        cells.append(f"{pts(g['point'])} ({ci(g)})" + ("" if g["ci95"][0] > 0 else " *"))
    rows.append(f"| {int(p * 100)}% | " + " | ".join(cells) + " |")
m = c["main"]
ops = d["ops"]
text = f"""
## Engineering

All numbers below are in `results.json` (TEST split, commit `{d['meta']['git']['short']}`). Tuning happens on DEV only; TEST is run once at the end.

### Change evidence (`--use-changes`)
The simulator now emits "what changed recently" events per incident. The true root had a deploy or config change in the 30 minutes before the
first alert with probability `p_root`; distractor changes land on random non-root services at Poisson rate `r_noise`; 10% of timestamps are jittered
by up to ±10 minutes. Change events use their own random stream, so every other field of every incident is byte-identical to the benchmark before
they existed (tested). The engine adds `GAMMA * exp(-minutes_before_first_alert / TAU)` to a candidate's log score. `GAMMA ∈ {{0, .25, .5, 1}}` and
`TAU ∈ {{5, 15, 30}}` were searched on DEV only (`eval/tune_changes.py`); the optimum (GAMMA 1, TAU 30) sits on the corner of the grid.

At the defaults (`p_root` 0.5, `r_noise` 2) AC@1 goes {m['without']['point']:.3f} → {m['with']['point']:.3f}, a gain of **{pts(m['gain']['point'])} pts (95% CI {ci(m['gain'])}, paired)**.
The DEV gain was larger (+2.8 pts), so some of it was fitted. Sensitivity of the gain, in AC@1 points (`*` = 95% CI includes 0):

| root has a change \\ distractors per incident | 0.5 | 2 | 5 |
|---|---|---|---|
{chr(10).join(rows)}

**{c['helps_only_when']}** The gain does not vanish at `r_noise` 5 when `p_root` is 0.5, but it is within noise at `p_root` 0.2 with the default noise.
Change evidence is a small, conditional gain. It is off by default and is not on the landing page.

Inputs: `POST /v1/changes` `{{service, ts, kind, ref}}`, a GitHub `deployment_status` / `release` webhook, and `gw change add SERVICE --ref '#482'`.
With the flag on, the verdict explains itself: "config-svc changed 1 min before the first alert (deploy #482)", and the MCP `why` returns the same line.

### Pre-deploy blast radius: `gw diff`
```
gw export > graph.json                       # official + learned graph and incident roots
gw diff --base main --head HEAD --graph graph.json [--format markdown|json]
```
It parses compose, k8s, Helm and `*_URL` / `*_HOST` evidence at both refs with the onboarding parser, lists added and removed edges, and for each added
edge asks the current graph how many services sit upstream of the new dependency, whether a learned edge already touches it, and which incidents it caused.
Read-only and offline: with a graph export file it needs no token or network.

![gw diff](docs/gw-diff.png)

GitHub Action (`.github/actions/ghostwalk-diff`), one comment updated in place and never duplicated (the extra-duplicate healing is tested):
```yaml
- uses: actions/checkout@v4
  with: {{ fetch-depth: 0 }}
- uses: ./.github/actions/ghostwalk-diff
  with: {{ graph: graph.json }}
```
Example comment (snapshot-tested): `+ fraud-check → config-svc · new dependency · blast radius 4 services (fraud-check, payments, checkout-api, web-edge) · a learned edge already touches it · config-svc caused INC-0931, INC-1042`

### Numbers for "Search vs walk"
- LLM tokens per verdict: ghostwalk **{ops['tokens_per_verdict']['ghostwalk']}**, TF-IDF **{ops['tokens_per_verdict']['tfidf']}** (neither calls a model). No LLM baseline was run, so there is no number for one.
- Verdict latency, in-memory: p50 {ops['ghostwalk']['verdict_ms_p50']:.1f} ms, p95 {ops['ghostwalk']['verdict_ms_p95']:.1f} ms. Via HydraDB: **not measured** (no node has answered; the adapter's response parser is still a stub).
- Novel vs repeat incidents AC@1: ghostwalk {d['repeat_vs_novel']['methods']['ghostwalk']['novel']['point']:.3f} novel / {d['repeat_vs_novel']['methods']['ghostwalk']['repeat']['point']:.3f} repeat, learning off {d['repeat_vs_novel']['methods']['learning_off']['novel']['point']:.3f} / {d['repeat_vs_novel']['methods']['learning_off']['repeat']['point']:.3f}, TF-IDF {d['repeat_vs_novel']['methods']['tfidf']['novel']['point']:.3f} / {d['repeat_vs_novel']['methods']['tfidf']['repeat']['point']:.3f}.

### Agent benchmark (stretch): not run
It needs an LLM API key and spend, and none is configured here, so there is no result and nothing is claimed about it.
"""
p = R / "README.md"
s = p.read_text(encoding="utf8")
start = s.index("## Engineering")
end = s.index("## Performance") if "## Performance" in s else len(s)
p.write_text(s[:start] + text.lstrip("\n") + "\n" + s[end:], encoding="utf8")
print("Engineering section regenerated")
