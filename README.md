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
