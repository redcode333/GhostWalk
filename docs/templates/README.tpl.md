<div align="center">

<img src="docs/logo.svg" alt="GhostWalk" height="64">

# GhostWalk

**The outage is never where the pager says.**

[![CI](https://github.com/{{repo}}/actions/workflows/ci.yml/badge.svg)](https://github.com/{{repo}}/actions/workflows/ci.yml)
[![tests](https://img.shields.io/github/actions/workflow/status/{{repo}}/ci.yml?branch=main&label=tests)](https://github.com/{{repo}}/actions/workflows/ci.yml)
[![license](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![live demo](https://img.shields.io/badge/live%20demo-open-6A4BFF)]({{live_demo}})

[**Live demo**]({{live_demo}}) · {{loom_link}}[**Proof page**]({{live_site}}/proof) · [**Docs**](docs)

<img src="docs/learning-curve.svg" alt="Top-1 accuracy by incident number: GhostWalk learns, learning off and placebo postmortems stay flat" width="760">

</div>

## The 30-second version

**The problem.** When an alert storm hits, the service that pages is rarely the service that broke, and the dependency that links them is often one nobody wrote down (a generated client, a shared config, a permission). Engineers lose their first minutes, and the next incident starts from zero again.

**What GhostWalk does.** It keeps a weighted dependency graph, walks it from the alerting services to rank root causes with a confidence and a path, and learns the missing edges from your postmortems, with a guard: a new edge stays tentative until a second incident confirms it. The graph and every lesson live in [HydraDB](https://github.com/hydra-db/hydradb).

| | |
|---|---|
| **{{gw_ac1}}** top-1 root cause on {{companies}} companies never used for development or tuning ({{incidents}} incidents) | 95% CI {{gw_ac1_ci}}; the best baseline ({{best_baseline}}) gets {{best_baseline_ac1}} |
| **{{learn_gain}}** from learning, with the placebo flat | learning off {{off_ac1}}, placebo postmortems {{placebo_ac1}}, GhostWalk {{gw_ac1}} |
| **Graph beats vector search** at ranking root causes | {{hydra_ac1}} vs {{vec_ac1}} for vector search over the same postmortems; a 1-hop key-value store gets {{kv_ac1}} |
| **{{verdict_headline}}** | laptop numbers and the load test are in [Performance](#performance-and-latency) |

**Who pays and why.** Teams with an on-call rotation: $49 a month flat for the workspace. One avoided hour of a wrong first guess pays for it.

> Honest limits, up front: the incidents are simulated (the knobs are in the evaluation section); Postgres with recursive queries gets the same accuracy as HydraDB and is faster on raw queries at our sizes; graph memory did not beat vector retrieval at finding similar past incidents; the LLM baseline ran on a {{llm_n}}-incident subset, not the full set; the real-outage replays are illustrations, not an accuracy measurement.

## How it works

### Architecture

```mermaid
{{mermaid_architecture}}
```

Verdicts are served from a revision-checked write-through cache: when the learner writes to HydraDB it applies the identical change to the cached graph and confirms the revision HydraDB reports, and a verdict is never served from a cache that is behind HydraDB. Path computation runs in the engine. HydraDB's in-database path mode was measured and is slower at these sizes, so it is not used. Deeper version: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

### One incident, end to end

```mermaid
{{mermaid_sequence}}
```

### The memory is the graph

GhostWalk's learning loop lives in HydraDB: every lesson is a node linked to the postmortems that taught it and the incidents that confirmed it.

```mermaid
{{mermaid_er}}
```

`gw why-edge config-svc fraud-check`, `GET /v1/edges/{src}/{dst}/why` and an MCP tool answer "why does the map say this?" by traversing Lesson → Postmortem → Incident. A real answer from the live deployment:

```
{{why_edge_example}}
```

### Lesson lifecycle

```mermaid
{{mermaid_lifecycle}}
```

The design reason for the guard: a single postmortem can be wrong, so it only ever creates a tentative edge that counts for little in a verdict; the edge becomes a full edge when a second incident confirms it, and it decays when it sends the walk astray. {{poison_sentence}} {{guard_sentence}}

### A worked example

{{worked_example}}

## Proof

All numbers on this page are generated from [`results.json`](results.json) by `scripts/update_readme_numbers.py` (commit {{git}}). The held-out split was used for declared runs only; every tuned setting was fitted on a separate DEV split.

### Main results

{{table_main}}

Learning starts from zero at each company. Confidence intervals are paired cluster bootstraps over companies ({{boot}} draws). Against the best baseline, GhostWalk is {{gain_vs_best}} ahead and closes {{gap_closed}} of the gap to the perfect-map oracle.

### How GhostWalk compares

Same incidents, same engine and learner, only the store changes (for the store rows):

{{table_compare}}

{{honest_sentences}}

**The LLM, on the same incidents.** Every method on the {{llm_n}}-incident subset:

{{table_llm}}

### Learning proof

{{table_learning_main}}

Removing one learning step at a time:

{{table_learning_ablation}}

How deep the walk needs to go (max hops):

{{table_depth}}

**When postmortems are wrong.** The simulator makes a share of postmortems point at the wrong root; the guard keeps learning useful:

{{table_poison}}

**New and repeat incidents.** {{novel_definition}} ({{share_repeat}} of incidents are repeats.)

{{table_novel_repeat}}

### Selective accuracy: abstain when unsure

Every verdict carries a confidence. Answering only above a threshold trades coverage for accuracy:

{{table_selective}}

### What didn't win

**Graph memory did not beat ordinary retrieval at finding similar past incidents.** Retrieving the five most relevant past incidents of the same company, using only past incidents (hit@5: a retrieved incident has the same root cause; repeat incidents only; 95% CIs in brackets):

{{table_memory}}

{{memory_sentence}} Looking up similar past incidents is easy in this setting: a repeat incident usually alerts on the same services, so a bag-of-words match on the alert text finds it and the graph adds nothing. **The graph matters for root-cause ranking, which is a different job**: {{gw_ac1}} for the walk against {{tfidf_ac1}} for TF-IDF retrieval and {{vec_ac1}} for vector search (see [the store swap](#how-ghostwalk-compares)).

**Change evidence helps only in a corner.** {{change_main}} Sensitivity (simulated knobs: how often the root's own change precedes the incident, and how many distractor changes there are):

{{table_change}}

{{change_helps}}

### Real-outage replays

{{table_replays}}

The scenarios, their sources and the assumptions are in [`docs/replays/`](docs/replays); run them live from the Replay buttons on the Incidents page of the [demo]({{live_demo}}).

### Judging checklist

{{table_checklist}}

## Performance and latency

Every number below is measured, labelled with the machine, and reproducible. Full tables: [docs/PERFORMANCE.md](docs/PERFORMANCE.md).

{{table_machines}}

**Per query on HydraDB** (p50 / p95, {{timed}} timed requests after {{warmup}} warm-up):

{{table_queries}}

**Per verdict** (p50 / p95):

{{table_verdicts}}

The cold read (the whole graph read back from HydraDB, which the cache avoids) is slower on the VM than on the laptop; HydraDB reads from MinIO there, and we did not isolate how much of the difference is that. Verdicts stay in the low milliseconds because they read the cached graph; the learning write (a few dozen sequential HydraDB commits) happens after the verdict and never delays one.

**Scale** (synthetic layered graphs, same generator, one machine; the in-database verdict is the slow path and is not used):

{{table_scale}}

**Load test on the VM** (`make loadtest`):

{{table_load}}

Throughput falls as clients are added, and that is the honest limit of this version: the walk is {{vm_walk_ms}} of each request (in memory, same VM), but every request takes the workspace lock, records the incident and rewrites the workspace's state file, which grows with the incidents recorded. Batching or journalling that save is the obvious next fix; it is not done.

**The transport diagnosis, in three lines.** HydraDB answers a read in about {{server_ms}} (its own metrics), yet every request from the Windows host took about {{floor_ms}}. The cause was the Docker Desktop published-port hop reacting to HTTP clients that write headers and body separately; a client that sends them in one write takes {{fast_ms}} through the same port, so the adapter now does that (`ghostwalk/graph/fasthttp.py`). Those {{floor_ms}} were never HydraDB's.

**The HydraDB restart bug.** HydraDB 0.4.0 rejected every HTTP write after a restart (`409 mutation_conflict`), because HTTP requests are numbered `http-query-1, 2, ...` from the start of every process and writes are deduplicated durably by that number. Fixed on our side by sending a unique `query_id` with every request (regression test: `tests/test_hydra_restart.py`); root cause from the source and a curl reproduction: [docs/hydradb-issue.md](docs/hydradb-issue.md). Not filed upstream yet.

**Reproduce:** `make bench` (engine at scale), `make bench-hydra` (HydraDB per query and per verdict, needs `docker compose --profile eval up -d hydradb postgres`), `make loadtest URL=...`, and on a VM `deploy/measure_vm.py` and `deploy/loadtest_vm.sh`.

## Quickstart

```bash
git clone https://github.com/{{repo}} && cd GhostWalk
docker compose up -d --build            # the app on http://localhost:8000
GW_STORE=hydradb docker compose up -d hydradb app    # optional: the graph and the memory in HydraDB
docker compose exec app gw doctor --url http://127.0.0.1:8000
```

Open http://localhost:8000 (the demo workspace needs no sign-in). Then:

```bash
pip install -e .
gw demo                          # a demo workspace and the next outage as alerts.json
gw why --alerts alerts.json      # the verdict
gw learn INC-1030 --root config-svc --path "config-svc -> fraud-check -> checkout-api"
```

**MCP, for Claude Code and Cursor.** `gw mcp` is a stdio server. Local (reads the workspace `gw` saved):

```bash
claude mcp add ghostwalk -- gw mcp
```

```json
{ "mcpServers": { "ghostwalk": { "command": "gw", "args": ["mcp"] } } }
```

Hosted (forwards to a GhostWalk server): set `GW_URL` and `GW_TOKEN` in the `env` of the same entry.

**Configuration** (`.env.example`):

{{env_table}}

## CLI and MCP reference

{{cli_reference}}

### The six MCP tools

| tool | arguments | what it does |
|---|---|---|
| `why` | `alerts` (service names, or `{name, signal, t}`; Alertmanager and Grafana payloads work) | ranks root causes with a confidence, the path and an explanation |
| `path` | `root`, `service` | explains how `service` depends on `root`, hop by hop, and which hops were learned |
| `blast_radius` | `service`, `hops` | what is affected if `service` fails |
| `why_edge` | `src`, `dst` | the lesson behind a learned edge, the postmortems that taught it and the incidents that confirmed it (HydraDB store) |
| `lesson_impact` | `lesson_id` | the services and past incidents whose paths use a learned edge |
| `propose_edge` | `src`, `dst`, `incident_id`, `reason` | suggests a lesson as a pending proposal; a person approves it, nothing is written |

GhostWalk never calls an LLM. The assistant asks and the graph answers.

## How it differs from OpenTelemetry and observability tools

| | OpenTelemetry | Observability tools | GhostWalk |
|---|---|---|---|
| what it is | a standard for collecting traces, metrics and logs | dashboards, search and alerting over telemetry | root-cause ranking over a dependency graph that learns |
| decides which failure explains the alerts | no | no, it shows what is happening | yes, with a confidence and a path |
| knows dependencies that never show up in telemetry (generated files, shared config, permissions) | no | no | yes, learned from postmortems with a guard |
| learns from your incidents | no | no | yes |

OpenTelemetry collects; it does not decide root cause or learn. Observability tools show what is happening; GhostWalk decides which failure explains the alerts and remembers dependencies that telemetry cannot see. They are complementary: OpenTelemetry traces are a planned evidence source for GhostWalk's learner.

## Evaluation method

Short version here; full method in [docs/EVALUATION.md](docs/EVALUATION.md).

- **Simulator.** `gwsim` builds companies from three families (hub, layered, and real-topology-shaped) with hidden edges missing from the official map, aliases, silent services, and a share of wrong postmortems.
- **Splits.** Weights and baselines are tuned on DEV only; the test split is used for declared final runs. Learning starts from zero at every company; each incident is predicted before its postmortem is learned from.
- **Statistics.** Paired cluster bootstrap over companies ({{boot}} draws). Controls: learning off, placebo postmortems (random root and edges), the perfect-map oracle, and a poisoning stress at several wrong-postmortem rates.
- **The test rerun history, in full.** Top-1 hits of {{incidents}} moved {{history}}: the first change reordered exact ties after a speed optimisation, the second added a deterministic tie-break; every table in `results.json` comes from the final engine ({{history_final}}).
- **Citations.** The topologies of two of the three real-system families follow RCAEval's published microservice systems; no RCAEval data is used. The PageRank baseline follows MicroRCA-style personalised PageRank, tuned on DEV (the untuned default is shown too).
- **Limitations.** The incidents are simulated; there are no replayed real outages; the LLM baseline covers {{llm_n}} incidents (a stratified subset, not all of them) and the free-tier models changed during the run (the model is recorded per incident); the replays are two scenarios we built from public postmortems; Postgres is faster on raw queries at our sizes; the change-evidence gain is small and conditional.

## Future work

- **Rust.** A single-binary `gw` CLI and MCP server in Rust; the walk engine as a Rust extension (PyO3) once the scale benchmark demands it (the engine's p95 at the largest size is {{engine_p95_5000}}, inside the budget); long term, the walk as a HydraDB-native procedure with no network hop. The Python engine stays the reference implementation, with CI parity tests.
- **OpenTelemetry traces** as a fourth evidence source, with the same tentative-then-confirmed guard.
- **Multi-path reach** (top-k paths), **cross-company learned priors** for a cold start, and a **temporal graph** ("what did we believe at incident time").
- **External validation** on RCAEval recorded faults, as a CI job.
- **Integrations:** a Slack and Teams verdict bot, native PagerDuty, Grafana and Datadog apps, the GitHub App and the `gw diff` PR check to general availability.
- **Production:** object storage on AWS S3, SSO and SAML, payments, a SOC 2 path.
- **Upstream:** the HydraDB restart bug ([docs/hydradb-issue.md](docs/hydradb-issue.md)); the filed issue will be linked here.

## Project structure

```
ghostwalk/            the product
  engine/             the walk: resolve aliases, score, verdict (frozen)
  learn/              the learner: propose and apply graph changes from postmortems (frozen)
  graph/              the graph state, the HydraDB adapter, the fast HTTP client
  api/                FastAPI app, workspace, demo sandbox, alert normalisers
  discover/           map import from compose, Kubernetes, Helm, *_URL settings
  integrations/       GitHub App, postmortem issues
  cli.py, mcp_*.py    the gw CLI and the MCP server
gwsim/                the incident simulator (families, knobs, hidden edges)
baselines/            PageRank, deepest-alert, retrieval, random
eval/                 the evaluation harness, store swap, latency and load tests
web/                  the React app (landing, auth, dashboard, Proof page)
deploy/               production compose, Caddy, MinIO, setup, smoke test, VM scripts
docs/                 architecture, performance, evaluation, graph-vs-sql, measurements
scripts/              generators for this README, the docs and the proof card
tests/                unit, parity (HydraDB vs in-memory), memory, async-write and restart tests
results.json         every measured number
```

## Contributing

Run `pytest` (the HydraDB tests need `docker compose up -d hydradb` and skip otherwise) and `cd web && npm test`. The engine and learner are frozen: changes to scoring need a DEV result and a new declared test run, recorded in `results.json`. Numbers in the README and docs are generated: edit `docs/templates/*.tpl.md` or `scripts/readme_blocks.py`, then run `python scripts/update_readme_numbers.py`; CI fails if the README is stale or a typed number appears in the prose. Commits carry no AI co-author or attribution lines.

## License

MIT, see [LICENSE](LICENSE).

## Acknowledgements

[HydraDB](https://github.com/hydra-db/hydradb) for the graph store and for an unusually readable codebase; [RCAEval](https://github.com/phamquiluan/RCAEval) for the microservice topologies and the benchmark that sets the bar; MicroRCA for the PageRank formulation we compare against.
