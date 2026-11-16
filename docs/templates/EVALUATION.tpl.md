# Evaluation method

Generated from [`results.json`](../results.json) by `scripts/update_readme_numbers.py`. The short version is in the README; this is the full method and every table.

## What is measured

For each incident of a company, in order: the verdict is computed from the alerts and the graph as it stands, scored against the true root (top-1 and top-3), and only then the incident's postmortem is learned from. Learning starts from zero at every company. The primary metric is top-1 accuracy (AC@1) over {{incidents}} incidents of {{companies}} held-out companies, with 95% intervals from a paired cluster bootstrap over companies ({{boot}} draws, fixed seeds recorded in `results.json`).

## The simulator

`gwsim` generates companies from three families: **hub** (a few shared services everything leans on), **layered** (tiers from edge to infrastructure), and **real** (topologies shaped like published microservice systems; two of the three follow RCAEval's systems, no RCAEval data is used). Each company has an official map that is missing edges (hidden dependencies: generated files, shared config, permissions), aliases (alerts name a service differently from the map), silent services, and postmortems that are sometimes wrong. Defaults of every knob:

{{simulator_knobs}}

## Main results

{{table_main}}

Learning starts from zero at each company. Intervals are paired cluster bootstraps over companies ({{boot}} draws). Against the best baseline, GhostWalk is {{gain_vs_best}} ahead and closes {{gap_closed}} of the gap to the perfect-map oracle.

![What learning adds](learning-curve.png)

## How GhostWalk compares

Same incidents, same engine and learner; only the store changes for the store rows.

{{table_compare}}

{{honest_sentences}}

## Splits and rules

- **DEV** is where everything is tuned: the PageRank baseline's grid, the change-evidence weights, the engine settings. **TEST** ({{companies}} companies, never used for development or tuning) is used for declared runs only, and each run is recorded.
- **The rerun history, in full.** The test split's top-1 hits moved as below. The first change reordered exact ties after a speed optimisation; the second added a deterministic tie-break (equal scores are ordered by component id). Every table in `results.json` comes from the final engine.

{{history_table}}

## Controls and baselines

- **Learning off** (the same engine, no learner), **placebo postmortems** (a random root and random edges: same shape, no information) and the **perfect-map oracle** bracket the learning proof.
- **Baselines:** deepest alerting service; personalised PageRank, tuned on DEV for fairness ({{pagerank_grid}}); TF-IDF retrieval of past postmortems; random. The best baseline on TEST by AC@1 is reported (it favours the baseline).
- **Stores:** the same engine and learner on HydraDB, Postgres (recursive CTE), a 1-hop key-value store and in memory; vector search (pgvector) over postmortem text. Only the store changes.
- **Poisoning:** the simulator is rerun with deliberately wrong postmortems at several rates.
- **LLM baseline.** {{llm_label}} {{llm_n}} incidents, stratified by company and incident index with a fixed seed, saved before any call (`eval/llm_subset.json`). Two arms: plain (alerts in firing order and the official map as text) and memory (plus the five most similar past postmortems of that company by TF-IDF, never a future one). Temperature zero, strict JSON, one retry on bad JSON then a miss; every response is cached in `eval/llm_cache/` with provider and exact model id. The free-tier Gemini quota ran out part-way, so later incidents were answered by the Groq fallback: that is stated per incident, not hidden.

{{table_llm}}

## Learning proof

{{table_learning_main}}

{{placebo_late}}

{{table_learning_ablation}}

## Other results

**Walk depth:**

{{table_depth}}

**Poisoning:**

{{table_poison}}

**New and repeat incidents.** {{novel_definition}}

{{table_novel_repeat}}

**Selective accuracy:**

{{table_selective}}

**Change evidence.** {{change_main}}

{{table_change}}

{{change_helps}}

## What did not win

**Graph memory did not beat ordinary retrieval at finding similar past incidents.** {{memory_sentence}} Looking up similar past incidents is easy in this setting: a repeat incident usually alerts on the same services, so a bag-of-words match finds it and the graph adds nothing. The graph matters for root-cause ranking, which is a different job: {{gw_ac1}} for the walk against {{tfidf_ac1}} for TF-IDF retrieval and {{vec_ac1}} for vector search. The retrieval table is in [PERFORMANCE.md](PERFORMANCE.md#graph-memory-retrieval).

## Real-outage replays

{{table_replays}}

## Checklist

{{table_checklist}}

## Limitations

The incidents are simulated, so absolute accuracy is not a forecast for your system; the comparisons between methods on the same incidents are the claim. The replays are illustrations. The LLM baseline covers a stratified subset and used free-tier models whose availability changed during the run. Postgres is faster than HydraDB on raw path queries at our sizes. The change-evidence gain is small and conditional on how often the root's own change precedes the incident.

## Citations

- RCAEval: a benchmark for root cause analysis of microservice systems with telemetry data (topologies of two of the real-system families; no data used).
- MicroRCA: root cause localisation of performance issues in microservices (the personalised PageRank formulation the baseline follows).
