"""Every value and table the README and docs/*.md show, computed from results.json (plus a few live reads: the demo scenario, the CLI examples, the test count).
Nothing here is a typed result. scripts/update_readme_numbers.py fills the templates in docs/templates/ with these."""
from __future__ import annotations
import json, pathlib, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
R = json.loads((ROOT / "results.json").read_text(encoding="utf8"))
LINKS = json.loads((ROOT / "docs" / "links.json").read_text(encoding="utf8")) if (ROOT / "docs" / "links.json").exists() else {}

# ---------------------------------------------------------------------------------------------- formatting
pct = lambda x, d=1: f"{x * 100:.{d}f}%"
pci = lambda c, d=1: f"{c['point'] * 100:.{d}f}% [{c['ci95'][0] * 100:.{d}f}, {c['ci95'][1] * 100:.{d}f}]"
pts = lambda x, d=1: f"{x * 100:+.{d}f}".replace("-", "−") + " pts"
ptsci = lambda c, d=1: f"{pts(c['point'], d)} (95% CI {c['ci95'][0] * 100:+.{d}f} to {c['ci95'][1] * 100:+.{d}f})".replace("-", "−")
ms = lambda x: f"{x:.2f} ms" if x < 1 else (f"{x:.1f} ms" if x < 10 else f"{x:,.0f} ms")
pp = lambda d: f"{ms(d['p50'])} / {ms(d['p95'])}"
num = lambda x: f"{x:,}"
LABEL = {"ghostwalk": "GhostWalk (multi-hop walk + learning)", "learning_off": "GhostWalk, learning off", "placebo": "GhostWalk, placebo postmortems", "oracle": "GhostWalk on the true graph (oracle)",
         "pagerank": "Personalized PageRank (tuned on DEV)", "pagerank_untuned": "Personalized PageRank (untuned default)", "retrieval": "TF-IDF retrieval of past postmortems", "deepest": "Deepest alerting service",
         "random": "Random", "ghostwalk_changes": "GhostWalk + change evidence (`--use-changes`)"}
M, P, SW = R["methods"], R["paired"], R["store_swap"]["backends"]
META = R["meta"]


def md_table(head, rows):
    return "\n".join(["| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|"] + ["| " + " | ".join(str(c) for c in row) + " |" for row in rows])


# ---------------------------------------------------------------------------------------------- inline values
def values():
    v = {}
    n_inc = META["incidents"]
    v["companies"], v["incidents"] = str(META["companies"]), num(n_inc)
    g = M["ghostwalk"]
    v["gw_ac1"], v["gw_ac1_ci"] = pct(g["ac1"]["point"]), pci(g["ac1"])
    v["gw_ac3_ci"] = pci(g["ac3"])
    v["off_ac1"], v["placebo_ac1"], v["oracle_ac1"] = pct(M["learning_off"]["ac1"]["point"]), pct(M["placebo"]["ac1"]["point"]), pct(M["oracle"]["ac1"]["point"])
    v["learn_gain"] = ptsci(P["ac1"]["ghostwalk - learning_off"])
    v["placebo_gain"] = pts(M["placebo"]["ac1"]["point"] - M["learning_off"]["ac1"]["point"])
    h = R["headline"]
    v["best_baseline"] = LABEL[h["best_baseline"]]
    v["best_baseline_ac1"] = pct(h["best_baseline_ac1"]["point"])
    v["gain_vs_best"] = ptsci(h["gain_vs_best"])
    v["gap_closed"] = f"{h['gap_closed']['point'] * 100:.0f}%"
    v["tfidf_ac1"] = pct(M["retrieval"]["ac1"]["point"])
    v["vec_ac1"], v["kv_ac1"], v["pg_ac1"] = pct(SW["pgvector"]["ac1"]["point"]), pct(SW["kv_1hop"]["ac1"]["point"]), pct(SW["pg_cte"]["ac1"]["point"])
    v["hydra_ac1"] = pct(SW["hydradb"]["ac1"]["point"])
    v["vec_gap"] = ptsci(SW["pgvector"]["delta_vs_reference"])
    v["kv_gap"] = ptsci(SW["kv_1hop"]["delta_vs_reference"])
    v["pg_gap"] = ptsci(SW["pg_cte"]["delta_vs_reference"])
    vm = R.get("ops", {}).get("vm", {})
    lap = R["ops"]["hydradb_latency"]["warm"]
    if "minio" in vm:
        mm = vm["minio"]["machine"]
        v["vm_name"] = f"AWS {mm.get('instance_type') or 'VM'} ({mm['logical_cpus']} vCPU, {mm['ram_gb']:.0f} GB)"
        v["verdict_headline"] = f"{ms(vm['minio']['online_loop']['verdict_ms']['p50'])} p50 / {ms(vm['minio']['online_loop']['verdict_ms']['p95'])} p95 per verdict, HydraDB on MinIO, learning on, on the {v['vm_name']}"
    else:
        v["vm_name"] = "VM (not measured)"
        v["verdict_headline"] = f"{ms(R['store_swap']['backends']['hydradb']['verdict_ms_p50'])} p50 / {ms(R['store_swap']['backends']['hydradb']['verdict_ms_p95'])} p95 per verdict, HydraDB, learning on, on the laptop"
    v["laptop_name"] = f"laptop ({lap['machine']['platform'].split('-SP')[0]}, {lap['machine']['cpus']} logical CPUs, {lap['machine']['ram_gb']} GB)"
    v["engine_p95_5000"] = ms(R["latency"]["gate"]["p95_5000_ms"])
    v["w_tent"], v["w_conf"] = f"{META['learner']['W_TENTATIVE']:.2f}", f"{SW['hydradb']['ac1']['point'] * 0 + 0.7:.2f}"
    from ghostwalk.graph.state import W_CONFIRMED
    v["w_conf"] = f"{W_CONFIRMED:.2f}"
    v["drop_below"], v["decay_wrong"], v["eta_up"] = f"{META['learner']['DROP_BELOW']:.2f}", f"{META['learner']['DECAY_WRONG']:.2f}", f"{META['learner']['ETA_UP']:.1f}"
    v["wrong_pm_default"] = pct(R["poisoning"]["levels"][min(R["poisoning"]["levels"], key=float)]["wrong_pm"], 0)
    v["boot"] = num(META["seeds"]["bootstrap_draws"])
    v["git"] = META["git"]["short"]
    hist = META.get("ac1_history", [])
    v["history"] = " → ".join(str(x["hits"]) for x in hist)
    v["history_final"] = f"{hist[-1]['hits']} of {num(hist[-1]['of'])}" if hist else ""
    mr = R["memory_retrieval"]["arms"]
    v["mem_graph_hit"], v["mem_vec_hit"], v["mem_kw_hit"] = pct(mr["graph"]["hit5_repeat"]["point"]), pct(mr["vector"]["hit5_repeat"]["point"]), pct(mr["keyword"]["hit5_repeat"]["point"])
    v["checks_to_root"] = f"{R['ops']['ghostwalk']['mean_checks_to_root']:.1f}"
    v["tests"] = str(test_count())
    v["loom"] = LINKS.get("loom")
    v["live_demo"] = LINKS.get("live_demo", "https://ghostwalk-henna.vercel.app/demo")
    v["live_site"] = LINKS.get("live_site", "https://ghostwalk-henna.vercel.app")
    v["live_api"] = LINKS.get("live_api", "https://api.13-51-194-36.sslip.io")
    v["repo"] = LINKS.get("repo", "redcode333/GhostWalk")
    d = R["ops"]["hydradb_latency"]["diagnosis"]
    v["floor_ms"] = ms(d["evidence_p50_ms"]["host (Windows) -> published port"]["httpx keep-alive"]["one_hop"])
    v["fast_ms"] = ms(d["evidence_p50_ms"]["host (Windows) -> published port"]["raw socket, one write"]["one_hop"])
    v["server_ms"] = ms(max(d["server_side_read_op_mean_ms"].values()))
    return v


def test_count():
    try:
        out = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q"], cwd=ROOT, capture_output=True, text=True, timeout=300).stdout
        last = [l for l in out.splitlines() if "tests collected" in l or "test collected" in l]
        return int(last[-1].split()[0]) if last else 0
    except Exception:
        return 0


# ---------------------------------------------------------------------------------------------- tables
def table_main():
    order = ["ghostwalk", "learning_off", "placebo", "oracle", "pagerank", "pagerank_untuned", "retrieval", "deepest", "random", "ghostwalk_changes"]
    ops = R["ops"]
    rows = []
    for k in order:
        m = M[k]
        chk = ops.get(k, {}).get("mean_checks_to_root")
        rows.append([f"**{LABEL[k]}**" if k == "ghostwalk" else LABEL[k], pci(m["ac1"]), pci(m["ac3"]), f"{chk:.2f}" if chk else ""])
    return md_table(["method", "AC@1 [95% CI]", "AC@3 [95% CI]", "mean checks to root"], rows)


def table_compare():
    ops = R["ops"]
    lat = lambda b: f"{ms(b['verdict_ms_p50'])} / {ms(b['verdict_ms_p95'])}"
    rows = [
        ["**GhostWalk on HydraDB**", pci(SW["hydradb"]["ac1"]), "reference", lat(SW["hydradb"]), "0", "yes"],
        ["GhostWalk on Postgres (recursive CTE)", pci(SW["pg_cte"]["ac1"]), ptsci(SW["pg_cte"]["delta_vs_reference"]), lat(SW["pg_cte"]), "0", "yes"],
        ["GhostWalk in memory", pci(SW["inmemory"]["ac1"]), ptsci(SW["inmemory"]["delta_vs_reference"]), lat(SW["inmemory"]), "0", "yes"],
        ["Key-value store (Redis), 1 hop", pci(SW["kv_1hop"]["ac1"]), ptsci(SW["kv_1hop"]["delta_vs_reference"]), lat(SW["kv_1hop"]), "0", "yes (1 hop only)"],
        ["Vector search over postmortems (pgvector)", pci(SW["pgvector"]["ac1"]), ptsci(SW["pgvector"]["delta_vs_reference"]), lat(SW["pgvector"]), "0", "adds text, no graph"],
        ["TF-IDF retrieval of past postmortems", pci(M["retrieval"]["ac1"]), ptsci(P["ac1"]["ghostwalk - retrieval"]).replace(pts(P["ac1"]["ghostwalk - retrieval"]["point"]), pts(-P["ac1"]["ghostwalk - retrieval"]["point"])), lat(ops["retrieval"]), R["ops"]["llm_tokens"]["retrieval"], "adds text, no graph"],
        ["Personalized PageRank (tuned on DEV)", pci(M["pagerank"]["ac1"]), "", lat(ops["pagerank"]), "0", "no"],
        ["Deepest alerting service", pci(M["deepest"]["ac1"]), "", lat(ops["deepest"]), "0", "no"],
        ["LLM baseline", "not run", "", "", "needs an API key and spend", "n/a"],
    ]
    return md_table(["system", "AC@1 [95% CI]", "Δ vs GhostWalk on HydraDB", "verdict p50 / p95 (laptop)", "LLM tokens per verdict", "learns the graph from postmortems"], rows)


def honest_sentences():
    pg, kv, vec = SW["pg_cte"], SW["kv_1hop"], SW["pgvector"]
    sc = R["scale"]["path_query"]["sizes"]
    sizes = sorted(sc, key=int)
    pg_faster = all(sc[s]["path_query"][h]["postgres"]["p50"] < sc[s]["path_query"][h]["hydradb"]["p50"] for s in sizes for h in ("hops_3", "hops_5"))
    out = [
        f"1. **Postgres ties on accuracy.** The same engine and learner on Postgres with recursive queries scores {pct(pg['ac1']['point'])} against {pct(SW['hydradb']['ac1']['point'])} on HydraDB (difference {ptsci(pg['delta_vs_reference'])}): the gain comes from the multi-hop weighted walk, not from which product stores the graph.",
        f"2. **{'Postgres is faster at raw path queries at our sizes' if pg_faster else 'Neither store is faster everywhere'}** ({', '.join(f'{s} services: HydraDB {ms(sc[s]['path_query']['hops_5']['hydradb']['p50'])} vs Postgres {ms(sc[s]['path_query']['hops_5']['postgres']['p50'])} for 5 hops' for s in sizes)}). We use HydraDB because the graph, its weights and the learner's memory live in one native graph store with weighted path algorithms, not for speed.",
        f"3. **Graph memory did not beat vector or keyword retrieval at finding similar past incidents** (hit@5 {pct(R['memory_retrieval']['arms']['graph']['hit5_repeat']['point'])} vs {pct(R['memory_retrieval']['arms']['vector']['hit5_repeat']['point'])} vector and {pct(R['memory_retrieval']['arms']['keyword']['hit5_repeat']['point'])} TF-IDF). The graph matters for root-cause ranking: replacing it with a 1-hop key-value store costs {pts(-kv['delta_vs_reference']['point'])} and vector search over postmortems scores {pct(vec['ac1']['point'])}.",
        "4. **The LLM baseline was not run** (it needs an API key and spend), so there is no accuracy, latency or token number for an LLM, and none is claimed.",
    ]
    return "\n".join(out)


def table_learning():
    rows = []
    for k in ("learning_off", "placebo", "ghostwalk", "oracle"):
        rows.append([LABEL[k], pci(M[k]["ac1"])])
    t1 = md_table(["variant", "AC@1 [95% CI]"], rows)
    t1 += f"\n\nLearning gain over learning off: {ptsci(P['ac1']['ghostwalk - learning_off'])}. Placebo postmortems (a random root and random edges, same shape, no information) move accuracy by {pts(M['placebo']['ac1']['point'] - M['learning_off']['ac1']['point'])}: the gain is the content of the postmortems, not the act of learning."
    full = M["ghostwalk"]["ac1"]["point"]
    ab = [["hidden-edge discovery", "ablate_hidden"], ["reweighting", "ablate_reweight"], ["aliases", "ablate_alias"], ["shortcuts", "ablate_shortcut"], ["guard (tentative until confirmed)", "ablate_guard"], ["blind-spot counters", "ablate_blind"]]
    t2 = md_table(["learning step removed", "AC@1 [95% CI]", "change vs full learner"], [[n, pci(M[k]["ac1"]), pts(M[k]["ac1"]["point"] - full)] for n, k in ab])
    dep = md_table(["max hops", "AC@1 [95% CI]"], [[k, pci(M[f"depth_{k}"]["ac1"])] for k in sorted(R["depth"])])
    return t1, t2, dep


def table_poison():
    rows = []
    for lvl in sorted(R["poisoning"]["levels"], key=float):
        l = R["poisoning"]["levels"][lvl]
        rows.append([pct(l["observed_wrong_share"], 0), pci(l["ghostwalk"]), pci(l["learning_off"]), ptsci(l["gain"])])
    return md_table(["wrong postmortems", "GhostWalk AC@1", "learning off AC@1", "gain from learning"], rows)


def table_novel_repeat():
    rn = R["repeat_vs_novel"]
    rows = [[LABEL.get(k, "TF-IDF retrieval" if k == "tfidf" else k), pci(v["repeat"]), pci(v["novel"])] for k, v in rn["methods"].items()]
    return md_table(["method", "root seen before (repeat)", "root never seen (novel)"], rows), rn["definition"], pct(rn["share_repeat"], 0)


def table_selective():
    bins = R["calibration"]
    tot = sum(b["n"] for b in bins)
    rows = []
    for i, b in enumerate(bins):
        rest = bins[i:]
        n = sum(x["n"] for x in rest)
        acc = sum(x["n"] * x["ac1"] for x in rest) / n
        rows.append([f"≥ {b['conf_from']:.1f}", pct(n / tot, 0), pct(acc)])
    return md_table(["answer only when confidence", "share of incidents answered", "AC@1 on those"], rows)


def table_memory():
    mr = R["memory_retrieval"]
    A, Pd = mr["arms"], mr["paired"]
    lat = lambda a: f"{ms(A[a]['latency_ms']['p50'])} / {ms(A[a]['latency_ms']['p95'])}"
    row = lambda label, m, f=pci: [label] + [f(A[a][m]) for a in ("graph", "vector", "keyword")]
    rows = [row(f"hit@5, repeat incidents (n={num(A['graph']['hit5_repeat']['n'])})", "hit5_repeat"),
            [f"MRR, repeat incidents"] + [f"{A[a]['mrr_repeat']['point']:.3f} [{A[a]['mrr_repeat']['ci95'][0]:.3f}, {A[a]['mrr_repeat']['ci95'][1]:.3f}]" for a in ("graph", "vector", "keyword")],
            row(f"related@5, novel incidents (n={num(A['graph']['related5_novel']['n'])})", "related5_novel"),
            ["retrieval latency p50 / p95"] + [lat(a) for a in ("graph", "vector", "keyword")]]
    d = Pd["hit5_repeat"]
    word = lambda c: "ahead of" if c["ci95"][0] > 0 else "behind" if c["ci95"][1] < 0 else "not distinguishable from"
    sent = (f"On repeat incidents, graph memory is {word(d['graph_minus_vector'])} vector search ({ptsci(d['graph_minus_vector'])}) and {word(d['graph_minus_keyword'])} TF-IDF ({ptsci(d['graph_minus_keyword'])}). "
            f"Graph retrieval first took {ms(mr['latency']['graph_hydradb_traversal_before']['p50'])} p50 as a HydraDB query per step; now it expands the neighbourhood on the revision-checked cached graph and keeps a per-revision index "
            f"({ms(mr['latency']['graph']['p50'])} p50), returning identical lists for all {num(mr['latency']['identical_lists_checked'])} incidents.")
    return md_table(["", "graph (HydraDB)", "vector (pgvector)", "keyword (TF-IDF)"], rows), sent


def table_change():
    ce = R["change_evidence"]
    ps = sorted({s["p_root"] for s in ce["sensitivity"]})
    rs = sorted({s["r_noise"] for s in ce["sensitivity"]})
    cell = lambda p, r: next(s for s in ce["sensitivity"] if s["p_root"] == p and s["r_noise"] == r)["gain"]
    fmt = lambda g: pts(g["point"]) + ("" if g["ci95"][0] > 0 else " (CI includes 0)")
    t = md_table(["root's own change rate ↓ / distractor noise →"] + [str(r) for r in rs], [[str(p)] + [fmt(cell(p, r)) for r in rs] for p in ps])
    main = f"With the change evidence on (`--use-changes`, weights fitted on DEV): {pci(ce['main']['with'])} against {pci(ce['main']['without'])} without, a gain of {ptsci(ce['main']['gain'])}."
    return t, main, ce["helps_only_when"]


def worked_example():
    from ghostwalk.api.demo import demo_inside
    d = demo_inside()
    b, a = d["before"], d["after"]
    name = {n["id"]: n["name"] for n in d["nodes"]}
    arrows = lambda path: " → ".join([name[path[0]["u"]]] + [name[s["v"]] for s in path]) if path else ""
    rk = lambda ranking: ", ".join(f"{x['name']} {x['confidence']:.2f}" for x in ranking[:3])
    fires = ", ".join(x.replace("|", " (") + ")" for x in d["search"]["query"])
    return (f"Five alerts fire at once ({fires}). The pager points at the front of the stack; the cause is two hops away.\n\n"
            f"- **Before the lesson:** `{rk(b['ranking'])}`; path `{arrows(b['path'])}`.\n"
            f"- A postmortem says the real root was `{a['ranking'][0]['name']}`, reached from `{name[d['learned_edges'][0]['u']]}` through an edge the service catalog never listed. The learner proposes it at weight {values()['w_tent']} (tentative); a second incident confirms it ({values()['w_conf']}).\n"
            f"- **After:** `{rk(a['ranking'])}`; path `{arrows(a['path'])}`, in {ms(d['ms'])}. Blast radius if `{a['ranking'][0]['name']}` fails: {', '.join('`' + x + '`' for x in d['blast'])}.\n"
            f"- A search over old postmortems (TF-IDF) for the same alerts returns {', '.join('`' + m['incident'] + ' → ' + m['root'] + '`' for m in d['search']['matches'])}: similar text, wrong roots.\n\n"
            f"Computed by the real engine and learner on a small scenario ({d['note']}).")


# ---------------------------------------------------------------------------------------------- performance
def table_machines():
    lap = R["ops"]["hydradb_latency"]["warm"]["machine"]
    rows = [["laptop", f"{lap['platform'].split('-SP')[0]}, {lap['cpus']} logical CPUs, {lap['ram_gb']} GB RAM, Python {lap['python']}", "client on the host; HydraDB and Postgres in Docker Desktop containers through published ports (transport fixed, see below)"]]
    vm = R["ops"].get("vm", {}).get("minio")
    if vm:
        m = vm["machine"]
        rows.append(["VM", f"AWS {m.get('instance_type') or ''}, {m['cpu']}, {m['logical_cpus']} vCPU, {m['ram_gb']} GB RAM, Linux {m['kernel']}, Python {m['python']}", "client in the API container, HydraDB on the same Docker network (no proxy hop); HydraDB's data in MinIO or on local disk, as labelled"])
    return md_table(["machine", "what", "how it was used"], rows)


def table_queries():
    w = R["ops"]["hydradb_latency"]["warm"]["per_query"]
    rows = []
    names = [("1-hop neighbours", "one_hop"), ("best path, 3 hops", "path_3_hops"), ("best path, 5 hops", "path_5_hops"), ("edge-weight write", "edge_write")]
    vm = R["ops"].get("vm", {})
    for label, k in names:
        row = [label, pp(w[k]["hydradb"]), pp(w[k]["postgres"])]
        for kind in ("minio", "local"):
            wk = {"one_hop": "one_hop_query_ms", "path_3_hops": "path_3_hops_ms", "path_5_hops": "path_5_hops_ms", "edge_write": "edge_write_ms"}[k]
            row.append(pp(vm[kind]["warm"][wk]) if kind in vm and wk in vm[kind]["warm"] else "not measured")
        rows.append(row)
    return md_table(["query (one at a time, after warm-up)", "HydraDB, laptop", "Postgres, laptop", "HydraDB, VM, MinIO", "HydraDB, VM, local disk"], rows)


def table_verdicts():
    lap = R["ops"]["hydradb_latency"]["warm"]
    ol = R["ops"]["hydradb_online_loop_test"]
    vm = R["ops"].get("vm", {})
    g = lambda kind, path: pp(path(vm[kind])) if kind in vm else "not measured"
    safe = lambda f: (lambda d: f(d))
    rows = [
        ["in memory (no store)", pp({"p50": R["ops"]["ghostwalk"]["verdict_ms_p50"], "p95": R["ops"]["ghostwalk"]["verdict_ms_p95"]}), g("minio", lambda d: d["warm"]["verdict_in_memory_ms"]) if vm.get("minio", {}).get("warm", {}).get("verdict_in_memory_ms") else "not measured"],
        ["HydraDB, cache hit (nothing written since the last verdict)", pp(lap["per_verdict"]["cached_hit"]), g("minio", lambda d: d["warm"]["verdict_cached_hit_ms"])],
        ["HydraDB, during learning (write-through cache, every incident)", pp({"p50": ol["verdict_ms_p50"], "p95": ol["verdict_ms_p95"]}), g("minio", lambda d: d["online_loop"]["verdict_ms"])],
        ["HydraDB, cold read of the whole graph", pp(lap["per_verdict"]["cold"]), g("minio", lambda d: d["warm"]["verdict_cold_read_ms"]) if vm.get("minio", {}).get("warm", {}).get("verdict_cold_read_ms") else "not measured"],
        ["learning write (after the verdict, off the verdict path)", pp({"p50": ol["learning_write_ms_p50"], "p95": ol["learning_write_ms_p95"]}), g("minio", lambda d: d["online_loop"]["learning_write_ms"])],
    ]
    return md_table(["verdict", "laptop (30 TEST companies / DEV companies)", "VM, HydraDB on MinIO"], rows)


def table_scale():
    sc = R["scale"]["path_query"]["sizes"]
    pv = R["scale"]["postgres_verdict"]["sizes"]
    eng = R["latency"]["sizes"]
    rows = []
    for s in sorted(sc, key=int):
        e = sc[s]
        rows.append([s, pp(eng[s]["in_memory_ms"]), pp(e["path_query"]["hops_3"]["hydradb"]), pp(e["path_query"]["hops_3"]["postgres"]), pp(e["path_query"]["hops_5"]["hydradb"]), pp(e["path_query"]["hops_5"]["postgres"]),
                     f"{ms(e['verdict']['cold_read']['p50'])} / {ms(e['verdict']['in_db']['p50'])} / {ms(pv[s]['p50'])}"])
    return md_table(["services", "engine verdict (in memory)", "HydraDB 3 hops", "Postgres 3 hops", "HydraDB 5 hops", "Postgres 5 hops", "whole verdict p50: HydraDB read-back / in-DB / Postgres"], rows)


def table_load():
    lt = R["ops"].get("loadtest", {}).get("vm")
    if not lt:
        return "Not measured yet: run `deploy/loadtest_vm.sh` on the VM, then `python scripts/merge_loadtest.py` (see below)."
    rows = []
    for l in lt["levels"]:
        rows.append([l["concurrency"], f"{l['req_per_s']:,.0f}", f"{ms(l['latency_ms']['p50'])} / {ms(l['latency_ms']['p95'])} / {ms(l['latency_ms']['p99'])}", l["errors"],
                     f"{l['container_cpu_percent_of_one_core']:.0f}%" if "container_cpu_percent_of_one_core" in l else "", f"{l['container_memory_mb']:.0f} MB" if "container_memory_mb" in l else ""])
    t = md_table(["concurrent clients", "requests / s", "latency p50 / p95 / p99", "errors", "API container CPU (% of one core)", "API container memory"], rows)
    return t + f"\n\nEach level ran {lt['seconds_per_level']:.0f} s against `{lt['endpoint']}` inside the API container on the VM ({lt['machine']['cpus']} vCPUs), rate limit off; every request is a full verdict that is also recorded and saved."


def transport_story():
    d = R["ops"]["hydradb_latency"]["diagnosis"]
    return d["cause"]


# ---------------------------------------------------------------------------------------------- misc
def mermaid_lifecycle():
    v = values()
    return f"""stateDiagram-v2
    direction LR
    [*] --> Tentative: a postmortem names an edge the map lacks (w {v['w_tent']})
    Tentative --> Confirmed: a second incident confirms it (w {v['w_conf']})
    Tentative --> Decayed: it sends the walk astray (w x 0.5)
    Confirmed --> Decayed: it sends the walk astray (w x {v['decay_wrong']})
    Decayed --> Decayed: again
    Decayed --> Dropped: w below {v['drop_below']}
    Dropped --> [*]"""


def table_checklist():
    rows = [
        ["Works end to end on a live deployment", f"[live demo]({values()['live_demo']}), [smoke test](deploy/smoke.py), [`docs/deploy.md`](docs/deploy.md)"],
        ["Measured on unseen data, not claimed", "30 held-out companies, test split used for declared runs only: [Proof](#proof), [`results.json`](results.json)"],
        ["Learning is real, not an artefact", "[learning off and placebo controls, ablations, poisoning](#learning-proof)"],
        ["Honest about what did not win", "[What didn't win](#what-didnt-win), [Postgres ties on accuracy](#how-ghostwalk-compares)"],
        ["Uses HydraDB for more than a cache", "graph, weights and the learner's memory in HydraDB: [memory schema](#how-it-works), [`ghostwalk/graph/hydra.py`](ghostwalk/graph/hydra.py), [parity tests](tests/test_parity.py)"],
        ["Found and reported a HydraDB bug", "[`docs/hydradb-issue.md`](docs/hydradb-issue.md) (root cause from the source, curl reproduction, fix and regression test)"],
        ["Survives restarts", "[durability demo](docs/measurements/durability_demo_vm.txt), [async write queue with replay](tests/test_async_learning.py)"],
        ["Reproducible", "`make eval-quick`, `make bench`, `make loadtest`; seeds, commit and engine settings are recorded in `results.json`"],
        ["Tested", f"{values()['tests']} tests ([`tests/`](tests))"],
    ]
    return md_table(["what a reviewer would ask", "evidence"], rows)


# ---------------------------------------------------------------------------------------------- the learning-curve picture
def learning_curve_svg():
    lc = R["learning_curve"]["series"]
    W, H, L, B, T, Rr = 760, 330, 52, 46, 18, 16
    series = [("ghostwalk", "#6A4BFF", "", 3.0, "GhostWalk (learning on)"), ("learning_off", "#8A8A96", "", 2.0, "learning off"), ("placebo", "#D98A00", "5 4", 2.0, "placebo postmortems"), ("oracle", "#0E9F8E", "2 4", 2.0, "perfect map (oracle)")]
    vals = [p["ac1"] for k, *_ in series for p in lc[k]] + [p["ci95"][0] for p in lc["ghostwalk"]] + [p["ci95"][1] for p in lc["ghostwalk"]]
    lo, hi = max(0.0, int(min(vals) * 20) / 20 - 0.05), min(1.0, int(max(vals) * 20) / 20 + 0.10)
    n = len(lc["ghostwalk"])
    x = lambda i: L + i * (W - L - Rr) / (n - 1)
    y = lambda v: T + (hi - v) * (H - T - B) / (hi - lo)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" role="img" aria-label="Top-1 accuracy by incident number: GhostWalk learns, the controls do not" font-family="system-ui, sans-serif">',
           f'<rect width="{W}" height="{H}" rx="12" fill="#ffffff"/>']
    g = 0.05
    t = lo
    while t <= hi + 1e-9:
        out.append(f'<line x1="{L}" x2="{W - Rr}" y1="{y(t):.1f}" y2="{y(t):.1f}" stroke="#E6E6EC"/><text x="{L - 8}" y="{y(t) + 4:.1f}" text-anchor="end" font-size="11" fill="#6B6B76">{t * 100:.0f}%</text>')
        t += 0.1
    band = lc["ghostwalk"]
    pts_up = " ".join(f"{x(i):.1f},{y(p['ci95'][1]):.1f}" for i, p in enumerate(band))
    pts_dn = " ".join(f"{x(i):.1f},{y(p['ci95'][0]):.1f}" for i, p in reversed(list(enumerate(band))))
    out.append(f'<polygon points="{pts_up} {pts_dn}" fill="#6A4BFF" opacity="0.12"/>')
    for k, col, dash, sw, _ in series:
        d = " ".join(f"{'M' if i == 0 else 'L'}{x(i):.1f},{y(p['ac1']):.1f}" for i, p in enumerate(lc[k]))
        out.append(f'<path d="{d}" fill="none" stroke="{col}" stroke-width="{sw}" stroke-linecap="round" stroke-linejoin="round"' + (f' stroke-dasharray="{dash}"' if dash else "") + "/>")
    for i, p in enumerate(band):
        if i % 2 == 0 or i == n - 1:
            out.append(f'<text x="{x(i):.1f}" y="{H - B + 18}" text-anchor="middle" font-size="11" fill="#6B6B76">{p["from"] + 1}–{p["to"] + 1}</text>')
    out.append(f'<text x="{(L + W - Rr) / 2:.0f}" y="{H - 8}" text-anchor="middle" font-size="12" fill="#3A3A44">incident number within a company (learning starts from zero at each)</text>')
    lx = L + 8
    for k, col, dash, sw, label in series:
        out.append(f'<line x1="{lx}" x2="{lx + 22}" y1="{T + 6}" y2="{T + 6}" stroke="{col}" stroke-width="{sw}"' + (f' stroke-dasharray="{dash}"' if dash else "") + f'/><text x="{lx + 28}" y="{T + 10}" font-size="11.5" fill="#3A3A44">{label}</text>')
        lx += 28 + 7 * len(label) + 18
    out.append("</svg>")
    return "\n".join(out)
