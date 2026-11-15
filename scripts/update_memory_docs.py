"""README section "The memory is the graph", generated from results.json (memory_graph + memory_retrieval) so it cannot go stale.
    python scripts/update_memory_docs.py"""
import json, pathlib
ROOT = pathlib.Path(__file__).resolve().parent.parent
r = json.loads((ROOT / "results.json").read_text(encoding="utf8"))
mg, mr = r["memory_graph"], r["memory_retrieval"]
A, P = mr["arms"], mr["paired"]
pts = lambda x: f"{x * 100:+.1f}".replace("-", "−")
pc = lambda d: f"{d['point'] * 100:.1f}%"
cis = lambda d: f"[{d['ci95'][0] * 100:.1f}, {d['ci95'][1] * 100:.1f}]"


def verdict(m, a, b):
    d = P[m][f"{a}_minus_{b}"]
    lo, hi = d["ci95"]
    word = "ahead of" if lo > 0 else "behind" if hi < 0 else "not distinguishable from"
    return f"{a} is {word} {b} ({pts(d['point'])} pts, 95% CI {pts(lo)} to {pts(hi)})"


def row(label, m, fmt=pc):
    return f"| {label} | " + " | ".join(f"{fmt(A[arm][m])} {cis(A[arm][m]) if fmt is pc else ''}".strip() for arm in ("graph", "vector", "keyword")) + " |"


mrr = lambda d: f"{d['point']:.3f} [{d['ci95'][0]:.3f}, {d['ci95'][1]:.3f}]"
lat = lambda arm: f"{A[arm]['latency_ms']['p50']:.1f} / {A[arm]['latency_ms']['p95']:.1f} ms"
inc = mr["incidents"]
why = mg["why_edge_example"]
per = mg["persistence"]

sec = f"""<!-- memory:begin -->
## The memory is the graph
**GhostWalk's learning loop lives in HydraDB: every lesson is a node linked to the postmortems that taught it and the incidents that confirmed it.**
The learner reads and writes through the HydraDB repository layer; the in-memory graph is a cache that is rebuilt from HydraDB by revision (`GW_STORE=hydradb`).

```mermaid
graph LR
  I[Incident] -- RAISED --> AL[Alert] -- ON --> S1[Service]
  PM[Postmortem] -- ABOUT --> I
  L[Lesson: src, dst, w, state] -- TAUGHT_BY --> PM
  L -- CONFIRMED_BY --> I
  S1 -- "DEPENDS_ON (w, cost) mirrors the Lesson" --> S2[Service]
```

`state` is tentative, confirmed or decayed. Every node carries the company key. A lesson's weight is written together with its `DEPENDS_ON` edge.

**Why does the map say `{why['src']}` depends on `{why['dst']}`?** One traversal, `gw why-edge {why['src']} {why['dst']}` (also `GET /v1/edges/{{src}}/{{dst}}/why` and an MCP tool):

```
{why['text']}
```

`GET /v1/lessons/{{id}}/impact` answers the other way round: the services and past incidents whose paths use a learned edge.

**Persistence.** {per['summary']}

**Graph memory against vector memory** ({mr['companies']} held-out companies, online, only past incidents of the same company; top {mr['k']}; paired cluster bootstrap, 95% CIs in brackets).
The graph arm uses no alert text: it traverses HydraDB from the alerting services (2 hops, both directions) to the past incidents that alerted on that neighbourhood, ranked by overlap.

| | graph (HydraDB) | vector (pgvector) | keyword (TF-IDF) |
|---|---|---|---|
{row(f"hit@5, repeat incidents (n={A['graph']['hit5_repeat']['n']})", 'hit5_repeat')}
| MRR, repeat incidents | {mrr(A['graph']['mrr_repeat'])} | {mrr(A['vector']['mrr_repeat'])} | {mrr(A['keyword']['mrr_repeat'])} |
{row(f"related@5, novel incidents (n={A['graph']['related5_novel']['n']})", 'related5_novel')}
{row(f"related@5, all (n={A['graph']['related5_all']['n']})", 'related5_all')}
| retrieval latency p50 / p95 | {lat('graph')} | {lat('vector')} | {lat('keyword')} |

On repeat incidents, hit@5: {verdict('hit5_repeat', 'graph', 'vector')}; {verdict('hit5_repeat', 'graph', 'keyword')}. MRR: {verdict('mrr_repeat', 'graph', 'vector')}.
On novel incidents (no past incident shares the root, so hit@5 cannot exist), related@5 asks whether a retrieved incident's true causal chain shares a dependency with the current one: {verdict('related5_novel', 'graph', 'vector')}.
hit@5 needs a past incident with the same root; {inc['repeat_root']} of {inc['with_a_past_incident']} incidents have one, and the first incident of each company has nothing to retrieve from.
The LLM arms were not run (no API key), so there is no `llm_graph_memory` number. Full definitions and CIs: `results.json` `memory_retrieval`.
<!-- memory:end -->
"""
rd = ROOT / "README.md"
t = rd.read_text(encoding="utf8")
if "<!-- memory:begin -->" in t:
    a, z = t.index("<!-- memory:begin -->"), t.index("<!-- memory:end -->") + len("<!-- memory:end -->")
    t = t[:a] + sec.rstrip("\n") + t[z:]
else:
    i = t.index("\n## HydraDB (live)")
    t = t[:i] + "\n" + sec + t[i:]
rd.write_text(t, encoding="utf8")
print("README memory section written")
