# Reference

Generated from `docs/templates/REFERENCE.tpl.md`. The README has the quickstart; this has every setting, command and tool.

## Configuration

Copy `.env.example` to `.env`. Secrets are never committed.

| variable | what it is | secret? | notes |
|---|---|---|---|
| AUTH_MODE | none or clerk | no | `clerk`: `/app` needs a Clerk session and every user gets their own workspace; `/demo` stays public. |
| CLERK_PUBLISHABLE_KEY, VITE_CLERK_PUBLISHABLE_KEY | Clerk publishable key | no (public) | The browser's Clerk SDK; the second name is the build-time variable on Vercel. |
| CLERK_SECRET_KEY | Clerk secret key | **yes** | Only for tooling that talks to Clerk's backend API (the live smoke test). The API does not need it to verify sessions. |
| CLERK_JWKS_URL | Clerk's JWKS URL | no | Session tokens are verified against these keys (cached); issuer and authorised party are checked. |
| GW_STORE | memory or hydradb | no | `hydradb`: the graph and the learner's memory live in HydraDB. |
| HYDRA_URL, HYDRA_TOKEN | HydraDB address and bearer token | token: **yes** | Defaults to the compose service; the token must be at least thirty-two bytes. |
| GW_DEMO_INCIDENTS | past incidents in the demo workspace | no | The seeded history the demo starts with. |
| GW_PUBLIC_DEMO | 0 or 1 | no | `1`: settings, onboarding and webhooks are read-only in the demo sandbox, and it is rebuilt every night. |
| GW_ADMIN_TOKEN | admin token | **yes** | Lets `POST /api/demo/reset` rebuild the demo on demand. |
| GW_RATE_LIMIT | requests/seconds, e.g. 60/60 | no | Off by default (`0`). An abuse guard for a public deployment, per client, on `/v1/*` and on POSTs; it answers 429 "Slow down, try again in a minute". The hosted demo sets `60/60` in `deploy/.env`. |
| GW_CORS_ORIGINS | comma-separated origins | no | The frontend origin(s) allowed to call the API; also the authorised parties for Clerk sessions. |
| GW_HOME | folder | no | Where the `gw` CLI keeps its workspace. |
| GW_URL, GW_TOKEN | API address and a workspace token | token: **yes** | Point `gw` and `gw mcp` at a hosted GhostWalk. Tokens look like `gw_live_<workspace>_<secret>`; only a hash is stored and the token is shown once. |
| GEMINI_API_KEY, GROQ_API_KEY | LLM keys | **yes** | Only for `eval/llm_baseline.py` and `eval/replays.py`. GhostWalk itself calls no LLM. |
| GITHUB_APP_ID, GITHUB_APP_PRIVATE_KEY, GITHUB_WEBHOOK_SECRET, GITHUB_PR_TOKEN | GitHub App settings | **yes** | Optional: map import from GitHub, postmortem issues, the `gw diff` PR comment. |

## CLI

Every block below is the real output of the command, captured by `scripts/capture_cli_examples.py` (in a throwaway workspace; `doctor` and `why-edge` against the live deployment).

**The commands**

```
$ gw --help


 Usage: -c [OPTIONS] COMMAND [ARGS]...

 GhostWalk: why is it broken, and what should the map have said?

┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --help  -h      <bool>  Show this message and exit.                                             │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
┌─ Commands ──────────────────────────────────────────────────────────────────────────────────────┐
│ demo      Create the simulated acme-demo workspace and write the next outage to alerts.json.    │
│ why       Rank the likely root causes of an alert storm and show the path.                      │
│ doctor    Check the stack: the API, the store it uses, HydraDB, the learning queue and the      │
│           stored results.                                                                       │
│ why-edge  Why does the map say SRC depends on DST: the lesson, the postmortems that taught it,  │
│           the incidents that confirmed it (HydraDB store).                                      │
│ learn     Turn a postmortem into graph changes, review them, apply.                             │
│ eval      The held-out numbers: AC@1 with 95% bootstrap intervals, the gain over the best       │
│           baseline, the gap closed.                                                             │
│ export    The graph (official + learned) and incident roots as JSON: the input `gw diff` needs  │
│           in CI. `gw export > graph.json`.                                                      │
│ diff      Pre-deploy blast radius: dependencies this change adds or removes, and what hangs off │
│           them. Read-only, works offline.                                                       │
│ mcp       Run the MCP server on stdio (tools: why, path, blast_radius, why_edge, lesson_impact, │
│           propose_edge). Read-only; GW_URL + GW_TOKEN for hosted mode.                          │
│ map       The dependency map.                                                                   │
│ change    What changed: deploys and config changes the verdict can use.                         │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

**A demo workspace and the next outage**

```
$ gw demo

  acme-demo · 80 services · 30 past incidents
  wrote alerts.json (46 alerts). Now: gw why --alerts alerts.json
```

**Who broke it**

```
$ gw why --alerts alerts.json

  46 alerts · 46 services · walked 161 edges in 2 ms

  rank  service            confidence
  1     redis-sessions    ████████████████████  1.00
  2     session-svc       ░░░░░░░░░░░░░░░░░░░░  0.00
  3     auth-svc          ░░░░░░░░░░░░░░░░░░░░  0.00

  path  edge-gateway → inventory-api → redis-sessions

  why   explains 32 of 46 alerts · fired in path order
  INC-1030 saved. Teach it: gw learn INC-1030 --root redis-sessions
```

**Teach it what the postmortem found**

```
$ gw learn INC-1030 --root session-svc

  reading postmortem · 3 fields

  + redis-sessions ⇢ session-svc      new · tentative 0.35
  − edge-gateway → inventory-api      reweight · 0.79 → 0.67
  − inventory-api → redis-sessions    reweight · 0.85 → 0.72

  ok graph updated · revision 31
```

**Import a dependency map from repos**

```
$ gw map import /tmp/gw\acme

  scanning 3 repos …

  docker-compose.yml          9 edges
  k8s/*.yaml                  2 edges
  Helm values                 2 edges
  env vars  *_URL             6 edges

  ok 15 services · 17 dependencies

    ● edge 1   ● service 9   ● data 4   ● infra 1
  2 low-confidence edges left out (use --all to include)
```

**Record a deploy the verdict can use**

```
$ gw change add redis-sessions --ref #482

  ok redis-sessions · deploy #482
```

**The held-out numbers**

```
$ gw eval --split test

  30 held-out companies · 95% bootstrap CI

  method           AC@1   95% CI
  perfect map      0.829  0.807–0.852  █████████████████
  ghostwalk        0.764  0.745–0.786  ███████████████
  pagerank (tuned) 0.699  0.667–0.730  ██████████████
  placebo          0.682  0.647–0.717  ██████████████
  learning off     0.676  0.636–0.715  ██████████████
  deepest alert    0.658  0.628–0.687  █████████████
  tf-idf retrieval 0.419  0.374–0.468  ████████
  random           0.212  0.186–0.240  ████

  ok gain vs best baseline +6.5 pts (pagerank)   gap closed 58%
  ok results.json read · c116282 · 2026-11-15
```

**Export the graph (the input of `gw diff` in CI)**

```
$ gw export --out D:\Temp\tmp9kkgb7ot\graph.json


```

**Pre-deploy blast radius of a change**

```
$ gw diff --base HEAD~1 --head HEAD

  2 added · 1 removed dependencies

  + fraud-check → config-svc
      blast radius 25 services  admin-api, billing-svc, catalog-svc, consent-svc, fraud-svc, …
      config-svc caused INC-1002, INC-1009
  + search → redis-main
      redis-main is not in the graph yet
  − cart → redis-main  removed (docker-compose.yml)
```

**The MCP server (stdio; started by Claude Code or Cursor)**

```
$ gw mcp --help


 Usage: -c mcp [OPTIONS]

 Run the MCP server on stdio (tools: why, path, blast_radius, why_edge, lesson_impact,
 propose_edge). Read-only; GW_URL + GW_TOKEN for hosted mode.

┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --help  -h      <bool>  Show this message and exit.                                             │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

**Check a running stack**

```
$ gw doctor

  ok api                   https://api.13-51-194-36.sslip.io {'ok': True, 'services': 80, 'store':
'hydradb', 'revision': 31, 'saving': 0, 'public_demo': True, 'writer_error': None}
  ok workspace             80 services, 8 learned edges, revision 31
  ok store                 HydraDB graph (memory in the graph) (hydradb)
  ok learning queue        saving 0
  ok hydradb               ready (http://127.0.0.1:9090/readyz)
  ok results.json          30 held-out companies

  ok all checks passed
```

**Why does the map say this?**

```
$ gw why-edge experiment-svc ledger-db

  experiment-svc -> ledger-db   w 0.79  learned  2 confirmations

  lesson L153  confirmed  w 0.79  created at revision 4
    taught by   INC-1004  root ledger-db  path experiment-svc -> ledger-db
    confirmed   ok INC-1018

  gw why-edge answers by traversal: Lesson -> Postmortem -> Incident, in HydraDB
```

## The six MCP tools

| tool | arguments | what it does |
|---|---|---|
| `why` | `alerts` (service names, or `{name, signal, t}`; Alertmanager and Grafana payloads work) | ranks root causes with a confidence, the path and an explanation |
| `path` | `root`, `service` | explains how `service` depends on `root`, hop by hop, and which hops were learned |
| `blast_radius` | `service`, `hops` | what is affected if `service` fails |
| `why_edge` | `src`, `dst` | the lesson behind a learned edge, the postmortems that taught it and the incidents that confirmed it (HydraDB store) |
| `lesson_impact` | `lesson_id` | the services and past incidents whose paths use a learned edge |
| `propose_edge` | `src`, `dst`, `incident_id`, `reason` | suggests a lesson as a pending proposal; a person approves it, nothing is written |

GhostWalk never calls an LLM. The assistant asks and the graph answers.
