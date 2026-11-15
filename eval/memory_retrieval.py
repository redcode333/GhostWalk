"""Graph memory vs vector memory (HydraDB's own claim), measured.

    python eval/memory_retrieval.py --split test          # needs HydraDB and Postgres+pgvector: docker compose --profile eval up -d hydradb postgres

For every incident, online, using ONLY past incidents of the same company, three retrievers each return their top 5 past incidents:
  graph    HydraDB. Past incidents with an alert on a service within 2 hops of the current alerting services (a traversal over the graph the learner wrote:
           DEPENDS_ON in both directions, then Incident-RAISED->Alert-ON->Service), ranked by neighbourhood overlap. The alert TEXT is never used.
  vector   pgvector. The 5 past postmortems nearest (cosine) to the embedding of the current alert text.
  keyword  TF-IDF. The 5 past postmortems with the highest TF-IDF cosine to the current alert text.
The learner runs exactly as in the main evaluation (HydraDB store, write-through cache), so this also re-checks AC@1.
Metrics: hit@5 = a retrieved past incident has the same root cause as the current one (defined only when such a past incident exists = "repeat");
MRR = 1 / rank of the first such incident in the top 5 (0 if none); for "novel" incidents (no past incident shares the root) hit@5 cannot exist, so
related@5 is reported instead: a retrieved past incident whose true causal chain shares a dependency edge with the current one's.
Retrievers never see the ground truth. Paired cluster bootstrap over companies. Writes results.json "memory_retrieval". Nothing is tuned here."""
from __future__ import annotations
import argparse, json, math, os, pathlib, sys, time
from collections import Counter
import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from eval.runner import load, run_company
from eval.full_eval import bootstrap
from eval import stores
from ghostwalk.graph.hydra import HydraGraph

PG = os.environ.get("PG_URL", "postgresql://gw:gw@127.0.0.1:5433/gw")
HYDRA_URL = os.environ.get("HYDRA_URL", "http://127.0.0.1:8443")
HYDRA_TOKEN = os.environ.get("HYDRA_TOKEN", "local-development-token-32-bytes")
K = 5
ARMS = ("graph", "vector", "keyword")


def tfidf_top(query, past, k=K):
    toks = lambda t: Counter(x.lower() for x in stores._TOK.findall(t))
    docs = [toks(p["text"]) for p in past]
    df = Counter()
    for d in docs:
        df.update(d.keys())
    n = len(docs)
    idf = lambda t: math.log((1 + n) / (1 + df[t])) + 1
    vec = lambda c: {t: c[t] * idf(t) for t in c}
    qv = vec(toks(query))
    qn = math.sqrt(sum(x * x for x in qv.values())) or 1.0
    sims = []
    for p, d in zip(past, docs):
        dv = vec(d)
        dn = math.sqrt(sum(x * x for x in dv.values())) or 1.0
        sims.append((sum(qv.get(t, 0.0) * x for t, x in dv.items()) / (qn * dn), p["seq"]))
    return [s for _, s in sorted(sims, key=lambda t: (-t[0], -t[1]))[:k]]


def run(cos, hg, store, compare=False):
    rows = {arm: [] for arm in ARMS}
    cmp = {"ms_traversal": [], "checked": 0}
    ac, loop_rows = {}, {}
    for co in cos:
        store.fresh(co)
        past, pending = [], [None]
        recs = {arm: [] for arm in ARMS}

        def probe(inc, backend):
            if pending[0] is not None:                                    # the previous incident becomes 'past' only now
                p = pending[0]
                store.learn(p)
                past.append({"seq": p["seq"], "root": p["root"], "text": p["postmortem_text"], "chain": {tuple(e) for e in p["chain"]}})
            pending[0] = inc
            if not past:
                return                                                    # nothing to retrieve from yet
            by_seq = {p["seq"]: p for p in past}
            alerts, truth, chain = inc["alerts"], inc["root"], {tuple(e) for e in inc["chain"]}
            text = "alerts: " + " ".join(a["name"] for a in alerts)
            repeat = any(p["root"] == truth for p in past)
            out = {}
            t = time.perf_counter()
            out["graph"] = [s for s, _ in backend.similar_incidents(alerts, K)]
            ms = {"graph": (time.perf_counter() - t) * 1000}
            if compare:                                                   # the first implementation (every step a HydraDB query) must return the identical list
                t = time.perf_counter()
                old = [s for s, _ in backend.similar_incidents_traversal(alerts, K)]
                cmp["ms_traversal"].append((time.perf_counter() - t) * 1000)
                assert old == out["graph"], (co["name"], inc["seq"], old, out["graph"])
                cmp["checked"] += 1
            t = time.perf_counter()
            q = stores._vec(stores.embed(text))
            out["vector"] = [r[0] for r in store.db.execute("SELECT seq FROM gw_pm WHERE co=%s ORDER BY emb <=> %s::vector, seq DESC LIMIT %s", (store.co, q, K)).fetchall()]
            ms["vector"] = (time.perf_counter() - t) * 1000
            t = time.perf_counter()
            out["keyword"] = tfidf_top(text, past)
            ms["keyword"] = (time.perf_counter() - t) * 1000
            for arm in ARMS:
                same = [by_seq[s]["root"] == truth for s in out[arm]]
                first = same.index(True) + 1 if True in same else None
                recs[arm].append({"company": co["name"], "seq": inc["seq"], "repeat": repeat, "hit": first is not None, "rr": 1.0 / first if first else 0.0,
                                  "related": any(by_seq[s]["chain"] & chain for s in out[arm]), "ms": ms[arm], "n": len(out[arm])})

        res = run_company(co, "ghostwalk", backend=hg, probe=probe)
        hg.drop()
        for arm in ARMS:
            rows[arm].append(recs[arm])
        loop_rows[co["name"]] = res
        ac[co["name"]] = [sum(1 for r in res if r["rank"] == 1), len(res)]
        print(f"  {co['name']:22s} AC@1 {ac[co['name']][0]}/{ac[co['name']][1]}  retrieval incidents {len(recs['graph'])}", flush=True)
    return rows, ac, loop_rows, cmp


def tab(rows_arm, sel, val):
    return np.array([[sum(val(r) for r in rs if sel(r)), sum(1 for r in rs if sel(r))] for rs in rows_arm], dtype=float)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="test")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--boot", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=20261116)
    ap.add_argument("--results", default=None)
    ap.add_argument("--latency-only", action="store_true", help="re-measure graph-retrieval latency only: asserts the faster implementation returns identical lists, changes no accuracy number")
    a = ap.parse_args()
    cos = load(a.split)
    if a.limit:
        cos = cos[:a.limit]
    out = pathlib.Path(a.results or ("results.json" if a.split == "test" else "dev_results.json"))
    hg = HydraGraph(HYDRA_URL, HYDRA_TOKEN, run_id=int(time.time()) % 900 + 1)
    store = stores.PgVectorStore(PG)
    t0 = time.time()
    rows, ac, loop_rows, cmp = run(cos, hg, store, compare=a.latency_only)
    if a.latency_only:
        doc = json.loads(out.read_text(encoding="utf8"))
        mr = doc["memory_retrieval"]
        assert [sum(v[0] for v in ac.values()), sum(v[1] for v in ac.values())] == [mr["learner_ac1_in_this_run"]["top1"], mr["learner_ac1_in_this_run"]["of"]], "learner accuracy moved"
        pct = lambda xs: {"p50": float(np.percentile(xs, 50)), "p95": float(np.percentile(xs, 95))}
        new = pct([r["ms"] for rs in rows["graph"] for r in rs])
        lat = mr.get("latency", {})
        lat.setdefault("graph_hydradb_traversal_before", mr["arms"]["graph"]["latency_ms"])      # the first measurement, kept
        lat["graph_hydradb_traversal_remeasured"] = pct(cmp["ms_traversal"])
        lat["graph"] = new
        lat["vector"], lat["keyword"] = (pct([r["ms"] for rs in rows[arm] for r in rs]) for arm in ("vector", "keyword"))
        lat["identical_lists_checked"] = cmp["checked"]
        lat["index_rebuilds"] = hg.index_rebuilds
        lat["note"] = ("graph = neighbourhood expanded on the cached in-memory graph (revision-checked), past incidents from a per-revision service->incidents index kept by the write-through path, "
                       "winners' details fetched from HydraDB by id in one batch. Every retrieved list was asserted identical to the first implementation (a HydraDB traversal per step). "
                       "Latency only: no accuracy number was changed.")
        mr["latency"], mr["arms"]["graph"]["latency_ms"] = lat, new
        doc["memory_retrieval"] = mr
        out.write_text(json.dumps(doc, indent=2), encoding="utf8")
        print(f"checked {cmp['checked']} lists identical; graph before p50/p95 {lat['graph_hydradb_traversal_before']['p50']:.1f}/{lat['graph_hydradb_traversal_before']['p95']:.1f} ms -> now {new['p50']:.2f}/{new['p95']:.2f} ms; index rebuilds {hg.index_rebuilds}")
        return
    print(f"  {len(cos)} companies in {time.time() - t0:.0f} s", flush=True)
    rep, nov, anyr = (lambda r: r["repeat"]), (lambda r: not r["repeat"]), (lambda r: True)
    metrics = {"hit5_repeat": (rep, lambda r: r["hit"]), "mrr_repeat": (rep, lambda r: r["rr"]),
               "related5_novel": (nov, lambda r: r["related"]), "related5_repeat": (rep, lambda r: r["related"]), "related5_all": (anyr, lambda r: r["related"])}
    res = {"split": a.split, "companies": len(cos), "k": K, "arms": {}, "paired": {}}
    pairs = [("graph", "vector"), ("graph", "keyword"), ("vector", "keyword")]
    for m, (sel, val) in metrics.items():
        tabs = {arm: tab(rows[arm], sel, val) for arm in ARMS}
        ci, diffs = bootstrap(tabs, a.boot, a.seed, pairs)
        for arm in ARMS:
            res["arms"].setdefault(arm, {})[m] = {**ci[arm], "n": int(tabs[arm][:, 1].sum())}
        res["paired"][m] = {k.replace(" - ", "_minus_"): v for k, v in diffs.items()}
    for arm in ARMS:
        ms = np.array([r["ms"] for rs in rows[arm] for r in rs])
        res["arms"][arm]["latency_ms"] = {"p50": float(np.percentile(ms, 50)), "p95": float(np.percentile(ms, 95))}
    n_all = sum(len(rs) for rs in rows["graph"])
    n_rep = sum(1 for rs in rows["graph"] for r in rs if r["repeat"])
    res["incidents"] = {"with_a_past_incident": n_all, "repeat_root": n_rep, "novel_root": n_all - n_rep, "first_incident_of_each_company_excluded": len(cos)}
    res["definitions"] = {"hit@5": "a retrieved past incident has the same root cause as the current one; defined only for repeat incidents (a past incident with that root exists)",
                          "mrr": "1 / rank of the first same-root past incident in the top 5, else 0 (repeat incidents)",
                          "related@5": "a retrieved past incident whose true causal chain shares a dependency edge with the current incident's chain (used for novel incidents, where hit@5 cannot exist)",
                          "graph": "HydraDB traversal: past incidents with an alert on a service within 2 hops of the alerting services, ranked by neighbourhood overlap; alert text unused",
                          "vector": "pgvector: nearest 5 past postmortems to the embedded alert text (feature-hashing bag-of-words, 512 dims)",
                          "keyword": "TF-IDF cosine between the alert text and past postmortem texts"}
    res["learner_ac1_in_this_run"] = {"top1": sum(v[0] for v in ac.values()), "of": sum(v[1] for v in ac.values())}
    res["llm_graph_memory"] = {"status": "not run", "why": "the LLM baseline (B4) was never run: it needs an API key and spend, so there is no llm_memory arm to put an llm_graph_memory arm next to"}
    res["measured_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    doc = json.loads(out.read_text(encoding="utf8")) if out.exists() else {}
    doc["memory_retrieval"] = res
    if a.split == "test" and not a.limit and "store_swap" in doc:       # the same online loop: record the HydraDB verdict and learning-write latency (aborts if AC@1 moved)
        from eval.store_swap import update_hydradb_row, hydra_status
        update_hydradb_row(doc, loop_rows, hg, a.split, hydra_status())
    out.write_text(json.dumps(doc, indent=2), encoding="utf8")
    f = lambda d: f"{d['point']:.3f} [{d['ci95'][0]:.3f}, {d['ci95'][1]:.3f}]"
    for m in metrics:
        print(f"{m:16s}", "  ".join(f"{arm} {f(res['arms'][arm][m])}" for arm in ARMS))
    for arm in ARMS:
        print(f"{arm:8s} latency p50 {res['arms'][arm]['latency_ms']['p50']:.1f} ms  p95 {res['arms'][arm]['latency_ms']['p95']:.1f} ms")
    print("AC@1 of the learner in this run:", res["learner_ac1_in_this_run"])


if __name__ == "__main__":
    main()
