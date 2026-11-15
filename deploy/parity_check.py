"""Parity of the deployed HydraDB store with the in-memory learner, on the demo company (hub, 80 services, the one the public demo uses).

    docker compose --env-file deploy/.env -f deploy/docker-compose.prod.yml cp deploy/parity_check.py api:/app/parity_check.py
    docker compose --env-file deploy/.env -f deploy/docker-compose.prod.yml exec -T api python /app/parity_check.py

Runs the same incidents with learning on both stores and asserts identical rankings (order and scores) and an identical learned graph. Exit code 1 on any difference."""
import json, os, sys, time
sys.path.insert(0, "/app" if os.path.isdir("/app/ghostwalk") else ".")
from gwsim.cli import make
from eval.runner import run_company
from ghostwalk.graph.hydra import HydraGraph

co = json.loads(make("hub", 7777, 80).to_json())
hg = HydraGraph(os.environ.get("HYDRA_URL", "http://hydradb:8443"), os.environ.get("HYDRA_TOKEN", "local-development-token-32-bytes"), run_id=int(time.time()) % 900 + 50)
tm, th = {}, {}
t0 = time.time()
mem = run_company(co, "ghostwalk", trace=tm)
hy = run_company(co, "ghostwalk", backend=hg, trace=th)
bad = []
for rm, rh, km, kh in zip(mem, hy, tm["rankings"], th["rankings"]):
    if [c for c, _ in km] != [c for c, _ in kh] or max((abs(x - y) for (_, x), (_, y) in zip(km, kh)), default=0) > 1e-9:
        bad.append(rm["seq"])
a, b = tm["final"], th["final"]
same_graph = (list(a.edges) == list(b.edges) and all((a.edges[k].w, a.edges[k].origin, a.edges[k].confirmations, a.edges[k].learned_from, a.edges[k].created_seq) ==
              (b.edges[k].w, b.edges[k].origin, b.edges[k].confirmations, b.edges[k].learned_from, b.edges[k].created_seq) for k in a.edges)
              and a.root_counts == b.root_counts and a.shortcuts == b.shortcuts and a.affected == b.affected and a.missed == b.missed and a.names == b.names and a.seq == b.seq)
hg.drop()
print(json.dumps({"company": co["name"], "incidents": len(mem), "rankings_differing": bad, "identical_learned_graph": same_graph, "seconds": round(time.time() - t0, 1),
                  "full_graph_rereads": hg.full_reads}))
sys.exit(0 if not bad and same_graph else 1)
