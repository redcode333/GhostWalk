PY ?= python
COMPOSE ?= docker compose

.PHONY: data eval eval-quick eval-stores test up down web bench durability-demo

data:
	$(PY) -m gwsim.cli --out data

# DEV only, about 2 minutes: PageRank tuning (72 settings), every headline number, poisoning. Writes dev_results.json.
eval-quick: data
	$(PY) eval/tune_pagerank.py
	$(PY) eval/full_eval.py --split dev --quick

# Final run on the TEST split: all methods, ablations, depth sweep, poisoning, then the real-store swap in docker.
# Uses the PageRank settings already fitted on DEV (eval/pagerank_tuned.json); never re-tunes on TEST.
eval: data
	$(PY) eval/full_eval.py --split test
	$(MAKE) eval-stores

# Redis (1-hop KV) + Postgres recursive CTE + pgvector, in the `eval` compose profile. Merges `store_swap` into results.json.
eval-stores:
	$(COMPOSE) --profile eval run --rm --build eval

test:
	$(PY) -m pytest -q

up:
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) --profile eval down

web:
	cd web && npm ci && npm run build

# Scale benchmark: p50/p95/p99 verdict latency at 100 / 1,000 / 5,000 services, 1,000 incidents each -> results.json "latency".
bench:
	$(PY) eval/bench.py --reference

# Delete ONLY HydraDB local data on the stack in deploy/ (MinIO volume kept), restart, and check ranking + why-edge are identical.
durability-demo:
	$(PY) deploy/durability_demo.py --api $(or $(API),https://localhost) $(if $(INSECURE),--insecure,)
