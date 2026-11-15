# GhostWalk

Root cause analysis that learns the dependencies nobody drew.

```
make data          # regenerate the simulated dev/test companies (data/ is gitignored)
make eval-quick    # DEV split, ~2 min: PageRank tuning + every headline number -> dev_results.json
make eval          # final TEST run -> results.json, then the real-store swap in docker (eval profile)
make test          # pytest   (web: cd web && npm test)
docker compose up -d --build   # app on :8000 (AUTH_MODE=none opens the demo workspace)
```

If `make` is not installed (Windows), run the commands in the Makefile directly.

## Layout
- `ghostwalk/` engine, learner, in-memory graph, API (`ghostwalk/api`), CLI (`gw`), discovery parsers, GitHub integration
- `gwsim/` simulator, `baselines/`, `eval/` (runner, full eval, PageRank tuning, store swap)
- `web/` React + Vite + TS + Tailwind app; `design/` the hand-off (DESIGN_SPEC.md is the source of truth)
- `results.json` the held-out numbers; the landing strip, Proof page and `gw eval` read it, nothing is hard-coded

## Rules the eval follows
TEST is only touched by final runs. Tuning (PageRank settings) happens on DEV only (`eval/tune_pagerank.py` refuses `test`).

## GitHub App
Read-only: repository contents + issues, subscribe to the Issues event, webhook URL `/api/webhooks/github`.
Env: `GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY`, `GITHUB_APP_SLUG`, `GITHUB_WEBHOOK_SECRET`.
A read-only App cannot open a pull request, so the postmortem-template PR uses `GITHUB_PR_TOKEN` (a token you control);
without it the UI offers a prefilled "new file" link.

## MCP server
`gw mcp` runs a stdio MCP server with four tools: `why(alerts)`, `path(root, service)`, `blast_radius(service, hops=3)` and
`propose_edge(src, dst, incident_id, reason)`. The first three are read-only. `propose_edge` only creates a pending proposal
that a person approves in Learn. GhostWalk never calls an LLM; the assistant asks and the graph answers.

Claude Code:
```
claude mcp add ghostwalk -- gw mcp
```
Cursor (`.cursor/mcp.json`) and other clients:
```json
{ "mcpServers": { "ghostwalk": { "command": "gw", "args": ["mcp"] } } }
```
Local mode reads the map saved by `gw` (`GW_HOME`, default `./.gw`). Hosted mode: set `GW_URL` and `GW_TOKEN`
(the API token from Settings) and each call is forwarded to that server.

## Engineering

All numbers below are in `results.json` (TEST split, commit `f8bf9a8`). Tuning happens on DEV only; TEST is run once at the end.

### Change evidence (`--use-changes`)
The simulator now emits "what changed recently" events per incident. The true root had a deploy or config change in the 30 minutes before the
first alert with probability `p_root`; distractor changes land on random non-root services at Poisson rate `r_noise`; 10% of timestamps are jittered
by up to ±10 minutes. Change events use their own random stream, so every other field of every incident is byte-identical to the benchmark before
they existed (tested). The engine adds `GAMMA * exp(-minutes_before_first_alert / TAU)` to a candidate's log score. `GAMMA ∈ {0, .25, .5, 1}` and
`TAU ∈ {5, 15, 30}` were searched on DEV only (`eval/tune_changes.py`); the optimum (GAMMA 1, TAU 30) sits on the corner of the grid.

At the defaults (`p_root` 0.5, `r_noise` 2) AC@1 goes 0.766 → 0.783, a gain of **+1.7 pts (95% CI +1.0 to +2.4, paired)**.
The DEV gain was larger (+2.8 pts), so some of it was fitted. Sensitivity of the gain, in AC@1 points (`*` = 95% CI includes 0):

| root has a change \ distractors per incident | 0.5 | 2 | 5 |
|---|---|---|---|
| 20% | +0.8 (+0.3 to +1.3) | +0.4 (-0.0 to +0.9) * | +0.2 (-0.3 to +0.7) * |
| 50% | +1.9 (+1.2 to +2.7) | +1.7 (+1.0 to +2.4) | +1.1 (+0.4 to +1.7) |
| 80% | +3.4 (+2.5 to +4.3) | +3.2 (+2.4 to +4.1) | +2.6 (+2.0 to +3.2) |

**helps only when the root's own change is common: reliable gain (95% CI above 0) for p_root in [0.5, 0.8]; at p_root=0.2 the gain is +0.4 pts with a CI that includes 0. Distractor noise up to r_noise=5 does not remove it at p_root=0.5.** The gain does not vanish at `r_noise` 5 when `p_root` is 0.5, but it is within noise at `p_root` 0.2 with the default noise.
Change evidence is a small, conditional gain. It is off by default and is not on the landing page.

Inputs: `POST /v1/changes` `{service, ts, kind, ref}`, a GitHub `deployment_status` / `release` webhook, and `gw change add SERVICE --ref '#482'`.
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
  with: { fetch-depth: 0 }
- uses: ./.github/actions/ghostwalk-diff
  with: { graph: graph.json }
```
Example comment (snapshot-tested): `+ fraud-check → config-svc · new dependency · blast radius 4 services (fraud-check, payments, checkout-api, web-edge) · a learned edge already touches it · config-svc caused INC-0931, INC-1042`

### Numbers for "Search vs walk"
- LLM tokens per verdict: ghostwalk **0**, TF-IDF **0** (neither calls a model). No LLM baseline was run, so there is no number for one.
- Verdict latency, in-memory: p50 0.3 ms, p95 1.6 ms. Via HydraDB: **not measured** (no node has answered; the adapter's response parser is still a stub).
- Novel vs repeat incidents AC@1: ghostwalk 0.707 novel / 0.845 repeat, learning off 0.689 / 0.666, TF-IDF 0.214 / 0.692.

### Agent benchmark (stretch): not run
It needs an LLM API key and spend, and none is configured here, so there is no result and nothing is claimed about it.
