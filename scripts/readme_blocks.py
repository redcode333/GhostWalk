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
    v["gw_ac1"] = pct(g["ac1"]["point"])
    v["gw_ac1_ci"] = f"{g['ac1']['ci95'][0] * 100:.1f} to {g['ac1']['ci95'][1] * 100:.1f}%"
    v["gw_ac3_ci"] = pci(g["ac3"])
    v["off_ac1"], v["placebo_ac1"], v["oracle_ac1"] = pct(M["learning_off"]["ac1"]["point"]), pct(M["placebo"]["ac1"]["point"]), pct(M["oracle"]["ac1"]["point"])
    v["learn_gain"] = ptsci(P["ac1"]["ghostwalk - learning_off"])
    v["placebo_gain"] = pts(M["placebo"]["ac1"]["point"] - M["learning_off"]["ac1"]["point"])
    h = R["headline"]
    v["best_baseline"] = {"pagerank": "tuned personalized PageRank", "deepest": "the deepest-alert rule", "retrieval": "TF-IDF retrieval"}.get(h["best_baseline"], h["best_baseline"])
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
        v["vm_name"] = f"AWS {mm.get('instance_type') or 'VM'} ({mm['logical_cpus']} vCPU, {mm['ram_gb']} GB)"
        v["verdict_headline"] = f"{ms(vm['minio']['online_loop']['verdict_ms']['p50'])} p50 / {ms(vm['minio']['online_loop']['verdict_ms']['p95'])} p95 per verdict, HydraDB on MinIO, learning on, on the {v['vm_name']}"
    else:
        v["vm_name"] = "VM (not measured)"
        v["verdict_headline"] = f"{ms(R['store_swap']['backends']['hydradb']['verdict_ms_p50'])} p50 / {ms(R['store_swap']['backends']['hydradb']['verdict_ms_p95'])} p95 per verdict, HydraDB, learning on, on the laptop"
    v["laptop_name"] = f"laptop ({lap['machine']['platform'].split('-SP')[0]}, {lap['machine']['cpus']} logical CPUs, {lap['machine']['ram_gb']} GB)"
    v["engine_p95_5000"] = ms(R["latency"]["gate"]["p95_5000_ms"])
    v["w_tent"] = f"{META['learner']['W_TENTATIVE']:.2f}"
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


def _neg(c):
    return {"point": -c["point"], "ci95": [-c["ci95"][1], -c["ci95"][0]]}


def _lat(b):
    return f"{ms(b['verdict_ms_p50'])} / {ms(b['verdict_ms_p95'])}" if b else ""


def table_compare():
    """One table on the same TEST incidents: approach | AC@1 (95% CI) | delta vs GhostWalk | verdict latency | tokens per verdict | learns from postmortems?
    (the LLM rows are on the marked subset; the next table puts every method on that subset)."""
    ops, llm = R["ops"], R.get("llm_baseline")
    toks = lambda k: num(round(llm["arms"][k]["tokens_per_incident"]["mean"]))
    rows = [
        ["**GhostWalk on HydraDB**", pci(SW["hydradb"]["ac1"]), "reference", _lat(SW["hydradb"]), "0", "yes: lessons in HydraDB, linked to evidence"],
        ["Same engine on Postgres (recursive CTE)", pci(SW["pg_cte"]["ac1"]), ptsci(SW["pg_cte"]["delta_vs_reference"]) + ": matches accuracy; the gain comes from multi-hop graph walks; Postgres is faster on raw path queries at our sizes", _lat(SW["pg_cte"]), "0", "yes"],
        ["Same engine in memory (no store)", pci(SW["inmemory"]["ac1"]), ptsci(SW["inmemory"]["delta_vs_reference"]), _lat(SW["inmemory"]), "0", "yes"],
        ["Key-value store (Redis), 1 hop", pci(SW["kv_1hop"]["ac1"]), ptsci(SW["kv_1hop"]["delta_vs_reference"]), _lat(SW["kv_1hop"]), "0", "yes, 1 hop only"],
        ["Vector search over postmortems (pgvector)", pci(SW["pgvector"]["ac1"]), ptsci(SW["pgvector"]["delta_vs_reference"]), _lat(SW["pgvector"]), "0", "adds text, no graph"],
        ["Keyword retrieval (TF-IDF) of past postmortems", pci(M["retrieval"]["ac1"]), ptsci(_neg(P["ac1"]["ghostwalk - retrieval"])), _lat(ops["retrieval"]), "0", "adds text, no graph"],
        ["Deepest alerting service", pci(M["deepest"]["ac1"]), ptsci(_neg(P["ac1"]["ghostwalk - deepest"])), _lat(ops["deepest"]), "0", "no"],
        ["Personalized PageRank (tuned on DEV)", pci(M["pagerank"]["ac1"]), ptsci(_neg(P["ac1"]["ghostwalk - pagerank"])), _lat(ops["pagerank"]), "0", "no"],
        ["Random", pci(M["random"]["ac1"]), pts(M["random"]["ac1"]["point"] - M["ghostwalk"]["ac1"]["point"]), _lat(ops.get("random")), "0", "no"],
        ["GhostWalk with learning off", pci(M["learning_off"]["ac1"]), ptsci(_neg(P["ac1"]["ghostwalk - learning_off"])), "", "0", "no (the learning proof)"],
        ["GhostWalk with placebo postmortems", pci(M["placebo"]["ac1"]), ptsci(_neg(P["ac1"]["ghostwalk - placebo"])), "", "0", "learns noise (the learning proof)"],
    ]
    if llm:
        n = llm["n_incidents"]
        for k, label in (("llm_plain", "LLM, plain"), ("llm_memory", "LLM + memory (five past postmortems)")):
            a = llm["arms"][k]
            rows.append([f"{label} (n={n} subset)", pci(a["ac1"]), ptsci(_neg(llm["paired_ac1"][f"ghostwalk_minus_{k}"])) + " on the subset", f"{ms(a['latency_ms']['p50'])} / {ms(a['latency_ms']['p95'])}", toks(k), "no"])
    else:
        rows.append(["LLM, plain / + memory", "not run", "", "", "", "no"])
    return md_table(["approach", "AC@1 (95% CI)", "Δ vs GhostWalk", "verdict p50 / p95", "tokens per verdict", "learns from postmortems?"], rows)


def table_llm():
    """Every method on the SAME LLM subset, with AC@1 and AC@3, paired CIs vs GhostWalk, tokens, latency, invalid-output rate and provider share."""
    llm = R.get("llm_baseline")
    if not llm:
        return "The LLM baseline has not been run."
    names = {"ghostwalk": "GhostWalk", "learning_off": "GhostWalk, learning off", "tfidf": "TF-IDF retrieval", "llm_plain": "LLM, plain", "llm_memory": "LLM + memory"}
    rows = []
    for k, label in names.items():
        a = llm["arms"][k]
        d1 = "reference" if k == "ghostwalk" else ptsci(_neg(llm["paired_ac1"][f"ghostwalk_minus_{k}"]))
        if "tokens_per_incident" in a:
            share = a["provider_share"]
            extra = [num(round(a["tokens_per_incident"]["mean"])), f"{ms(a['latency_ms']['p50'])} / {ms(a['latency_ms']['p95'])}", pct(a["invalid_output_rate"], 0), f"Gemini {pct(share['gemini'], 0)}, Groq {pct(share['groq'], 0)}"]
        else:
            extra = ["0", "", "", ""]
        rows.append([label, pci(a["ac1"]), d1, pci(a["ac3"])] + extra)
    models = ", ".join(f"`{m}`" for k in ("llm_plain", "llm_memory") for m in llm["arms"][k]["models_used"]) if llm["arms"]["llm_plain"].get("models_used") else ""
    t = md_table(["method", "AC@1 (95% CI)", "Δ AC@1 vs GhostWalk", "AC@3 (95% CI)", "tokens / incident", "latency p50 / p95", "invalid output", "provider share"], rows)
    stop = (f" The run stopped when Groq's free daily token limit was reached: these are the first {llm['n_incidents']} of the {llm['n_requested']} planned incidents in company order ({llm['companies']} of {META['companies']} companies; families covered: {', '.join(llm['families_covered'])}{'; not reached: ' + ', '.join(sorted(set(llm['families_total']) - set(llm['families_covered']))) if set(llm['families_total']) - set(llm['families_covered']) else ''}); `python eval/llm_baseline.py` resumes from the cache once the limit resets." if llm["stopped_early"] else "")
    note = (f"{llm['label']} {num(llm['n_incidents'])} incidents across {llm['companies']} companies, chosen with a fixed seed and saved to `eval/llm_subset.json` before any call: {llm['subset']['rule']}. "
            f"Models used (recorded per incident in `eval/llm_cache/`): {', '.join(sorted({m for k in ('llm_plain', 'llm_memory') for m in llm['arms'][k]['models_used']}))}. temperature 0, strict JSON, one retry on bad JSON then a miss." + stop)
    return t + "\n\n" + note


def honest_sentences():
    kv, vec, pg, llm = SW["kv_1hop"], SW["pgvector"], SW["pg_cte"], R.get("llm_baseline")
    sc = R["scale"]["path_query"]["sizes"]
    sizes = sorted(sc, key=int)
    pg_faster = all(sc[s]["path_query"][h]["postgres"]["p50"] < sc[s]["path_query"][h]["hydradb"]["p50"] for s in sizes for h in ("hops_3", "hops_5"))
    out = [f"1. **Graph traversal is what matters.** Replacing it with a 1-hop key-value store costs {abs(kv['delta_vs_reference']['point']) * 100:.1f} points of top-1 accuracy and vector search over the same postmortems costs {abs(vec['delta_vs_reference']['point']) * 100:.1f}.",
           f"2. **A Postgres recursive CTE matches accuracy** (it walks the graph too; difference {pg['delta_vs_reference']['point'] * 100:+.1f} points, 95% CI {pg['delta_vs_reference']['ci95'][0] * 100:+.1f} to {pg['delta_vs_reference']['ci95'][1] * 100:+.1f}): the gain comes from multi-hop graph walks, not from which product stores the graph, and stores that cannot walk the graph lose {abs(kv['delta_vs_reference']['point']) * 100:.1f} to {abs(vec['delta_vs_reference']['point']) * 100:.1f} points; {'Postgres is faster on raw path queries at our sizes' if pg_faster else 'neither store is faster everywhere on raw path queries'} (HydraDB {ms(sc[sizes[-1]]['path_query']['hops_5']['hydradb']['p50'])} vs Postgres {ms(sc[sizes[-1]]['path_query']['hops_5']['postgres']['p50'])} for 5 hops at {sizes[-1]} services)."]
    if llm:
        a, m = llm["arms"]["llm_plain"], llm["arms"]["llm_memory"]
        verdict = lambda k: ("ahead of" if llm["paired_ac1"][f"ghostwalk_minus_{k}"]["ci95"][0] > 0 else "not distinguishable from" if llm["paired_ac1"][f"ghostwalk_minus_{k}"]["ci95"][1] > 0 else "behind")
        rng = lambda k: f"{llm['paired_ac1'][f'ghostwalk_minus_{k}']['point'] * 100:+.1f} points, 95% CI {llm['paired_ac1'][f'ghostwalk_minus_{k}']['ci95'][0] * 100:+.1f} to {llm['paired_ac1'][f'ghostwalk_minus_{k}']['ci95'][1] * 100:+.1f}"
        partial = f" (the first {llm['n_incidents']} of {llm['n_requested']} planned incidents, {llm['companies']} of the {META['companies']} companies: the run stopped at the model API's daily token quota)" if llm["stopped_early"] else ""
        out.append(f"3. **The LLM costs tokens and seconds per verdict.** On the {llm['n_incidents']}-incident subset{partial} it used about {num(round(a['tokens_per_incident']['mean']))} tokens and {ms(a['latency_ms']['p50'])} p50 per verdict (GhostWalk: none, {ms(SW['hydradb']['verdict_ms_p50'])}). "
                   f"On the same incidents GhostWalk scored {pci(llm['arms']['ghostwalk']['ac1'])}: {verdict('llm_plain')} the plain LLM ({pci(a['ac1'])}; difference {rng('llm_plain')}) and {verdict('llm_memory')} the LLM given five past postmortems ({pci(m['ac1'])}; difference {rng('llm_memory')}). These intervals are wide: this is a comparison on a small, partly covered subset, not a verdict on LLMs.")
    else:
        out.append("3. **The LLM baseline has not been run**, so there is no LLM number.")
    out.append("4. **GhostWalk's learning lives in HydraDB**: every lesson is a node linked to the postmortem that taught it and the incident that confirmed it, and it survives restarts (durability demo, async write queue with replay).")
    return "\n".join(out)


def table_replays():
    rp = R.get("replays")
    if not rp:
        return "Not run yet."
    rows = []
    for s in rp["scenarios"]:
        st = s["stages"]
        cell = lambda x: f"{x['top1']} ({x['confidence']:.2f}); real root {'first' if x['root_rank'] == 1 else 'not ranked' if x['root_rank'] is None else 'rank ' + str(x['root_rank'])}"
        rows.append([f"[{s['short']}]({s['source']['url']}): real root `{s['root']}`", cell(st[0]), cell(st[1]), cell(st[2]),
                     f"{s['deepest_alert']['top1']}; real root {'not ranked' if s['deepest_alert']['root_rank'] is None else 'rank ' + str(s['deepest_alert']['root_rank'])}",
                     (f"{s['llm']['top1']}; real root {'not ranked' if s['llm']['root_rank'] is None else 'rank ' + str(s['llm']['root_rank'])} ({s['llm']['provider']})" if s.get("llm") else "not run")])
    t = md_table(["scenario", "GhostWalk, official map (hidden dependency missing)", "after one learned edge (tentative)", "after a second incident confirms it", "deepest alert", "LLM"], rows)
    return t + f"\n\n{rp['label']} One run per scenario, on a map and an alert order we built from the public description: this shows the mechanism, not an accuracy. With the dependency missing GhostWalk is confidently wrong, like the responders were; after one learned edge the real root enters the ranking but is not first. We make no claim that GhostWalk would have prevented either outage."


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
            f"- **After:** `{rk(a['ranking'])}`; path `{arrows(a['path'])}`. Blast radius if `{a['ranking'][0]['name']}` fails: {', '.join('`' + x + '`' for x in d['blast'])}.\n"
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
        ["Works end to end on a live deployment", f"[live demo]({values()['live_demo']}), [smoke test](../deploy/smoke.py), [`deploy.md`](deploy.md)"],
        ["Measured on unseen data, not claimed", "30 held-out companies, test split used for declared runs only: [main results](#main-results), [`results.json`](../results.json)"],
        ["Learning is real, not an artefact", "[learning off and placebo controls, ablations, poisoning](#learning-proof)"],
        ["Honest about what did not win", "[what did not win](#what-did-not-win), [Postgres ties on accuracy](#how-ghostwalk-compares)"],
        ["Uses HydraDB for more than a cache", "graph, weights and the learner's memory in HydraDB: [memory schema](ARCHITECTURE.md#the-schema-in-hydradb), [`ghostwalk/graph/hydra.py`](../ghostwalk/graph/hydra.py), [parity tests](../tests/test_parity.py)"],
        ["Found and reported a HydraDB bug", "[`hydradb-issue.md`](hydradb-issue.md) (root cause from the source, curl reproduction, fix and regression test)"],
        ["Survives restarts", "[durability demo](measurements/durability_demo_vm.txt), [async write queue with replay](../tests/test_async_learning.py)"],
        ["Reproducible", "`make eval-quick`, `make bench`, `make loadtest`; seeds, commit and engine settings are recorded in `results.json`"],
        ["Tested", "unit, parity (HydraDB against in-memory), memory, tenancy and isolation, async-write replay, restart and replay tests: [`tests/`](../tests), run in CI"],
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


def per_bin_svg(theme="light"):
    """Per-bin chart (EVALUATION.md): AC@1 gain over learning off per five-incident bin, in points, for GhostWalk (with its 95% paired company-bootstrap band) and for the placebo, with the zero line.
    Drawn from results.json learning_curve.paired_gain. theme is "light" or "dark"."""
    pg = R["learning_curve"]["paired_gain"]
    gw, pl = pg["series"]["ghostwalk_minus_learning_off"], pg["series"]["placebo_minus_learning_off"]
    ref = pg["reference_paired_ci"]["ghostwalk_minus_learning_off"]["overall"]
    dark = theme == "dark"
    bg, ink, muted, grid, zero = ("#14131C", "#ECEBF4", "#A6A5B4", "#2B2A38", "#ECEBF4") if dark else ("#FFFFFF", "#1B1A24", "#6B6B76", "#E6E6EC", "#3A3A44")
    violet, amber = ("#9C86FF", "#F0A93B") if dark else ("#6A4BFF", "#D98A00")
    W, H, L, Bm, T, Rr = 760, 360, 56, 62, 34, 92
    has_band = all(p["ci95"] for p in gw)
    vals = [p["gain"] * 100 for p in gw + pl] + ([c * 100 for p in gw for c in p["ci95"]] if has_band else [])
    lo, hi = min(-4.0, (int(min(vals) / 4) - 1) * 4.0), (int(max(vals) / 4) + 1) * 4.0
    n = len(gw)
    x = lambda i: L + i * (W - L - Rr) / (n - 1)
    y = lambda v: T + (hi - v) * (H - T - Bm) / (hi - lo)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" role="img" aria-label="What learning adds: accuracy gain over learning off by incident number, GhostWalk with its 95 percent band against placebo postmortems" font-family="system-ui, sans-serif">',
           f'<rect width="{W}" height="{H}" rx="12" fill="{bg}"/>',
           f'<text x="{L}" y="20" font-size="14" font-weight="600" fill="{ink}">What learning adds</text>']
    t = lo
    while t <= hi + 1e-9:
        z = abs(t) < 1e-9
        out.append(f'<line x1="{L}" x2="{W - Rr}" y1="{y(t):.1f}" y2="{y(t):.1f}" stroke="{zero if z else grid}" stroke-width="{1.4 if z else 1}"/><text x="{L - 8}" y="{y(t) + 4:.1f}" text-anchor="end" font-size="11" fill="{muted}">{t:+.0f}</text>')
        t += 4
    out.append(f'<text transform="translate(14 {(T + H - Bm) / 2:.0f}) rotate(-90)" text-anchor="middle" font-size="12" fill="{muted}">AC@1 gain over learning off (points)</text>')
    for i, p in enumerate(gw):
        if i % 2 == 0 or i == n - 1:
            out.append(f'<text x="{x(i):.1f}" y="{H - Bm + 18}" text-anchor="middle" font-size="11" fill="{muted}">{p["from"] + 1}-{p["to"] + 1}</text>')
    out.append(f'<text x="{(L + W - Rr) / 2:.0f}" y="{H - Bm + 38}" text-anchor="middle" font-size="12" fill="{muted}">incident number at each company (bins of five)</text>')
    if has_band:
        up = " ".join(f"{x(i):.1f},{y(p['ci95'][1] * 100):.1f}" for i, p in enumerate(gw))
        dn = " ".join(f"{x(i):.1f},{y(p['ci95'][0] * 100):.1f}" for i, p in reversed(list(enumerate(gw))))
        out.append(f'<polygon points="{up} {dn}" fill="{violet}" opacity="0.16"/>')
    for series, col, dash, sw in ((gw, violet, "", 3.2), (pl, amber, "2 5", 2.4)):
        d = " ".join(f"{'M' if i == 0 else 'L'}{x(i):.1f},{y(p['gain'] * 100):.1f}" for i, p in enumerate(series))
        out.append(f'<path d="{d}" fill="none" stroke="{col}" stroke-width="{sw}" stroke-linecap="round" stroke-linejoin="round"' + (f' stroke-dasharray="{dash}"' if dash else "") + "/>")
        last = series[-1]["gain"] * 100
        out.append(f'<text x="{x(n - 1) + 8:.1f}" y="{y(last) + 4:.1f}" font-size="12.5" font-weight="600" fill="{col}">{last:+.1f} pts</text>')
    out.append(f'<line x1="{L}" x2="{L + 24}" y1="{H - 10}" y2="{H - 10}" stroke="{violet}" stroke-width="3.2"/><text x="{L + 30}" y="{H - 6}" font-size="11.5" fill="{muted}">GhostWalk minus learning off{" (shaded: 95% band)" if has_band else ""}</text>')
    lx = L + (330 if has_band else 218)
    out.append(f'<line x1="{lx}" x2="{lx + 24}" y1="{H - 10}" y2="{H - 10}" stroke="{amber}" stroke-width="2.4" stroke-dasharray="2 5" stroke-linecap="round"/><text x="{lx + 30}" y="{H - 6}" font-size="11.5" fill="{muted}">placebo minus learning off</text>')
    out.append(f'<text x="{W - 12}" y="20" text-anchor="end" font-size="11.5" fill="{muted}">whole run: {ref["gain"] * 100:+.1f} pts, 95% CI {ref["ci95"][0] * 100:+.1f} to {ref["ci95"][1] * 100:+.1f}</text>')
    out.append("</svg>")
    return "\n".join(out)


# ---------------------------------------------------------------------------------------------- the short README
def results_lines():
    v, llm = values(), R.get("llm_baseline")
    vm = R["ops"].get("vm", {}).get("minio")
    q = vm["warm"].get("one_hop_query_ms") if vm else None
    out = [
        f"- **{v['gw_ac1']}** top-1 root cause on {v['companies']} companies never used for development or tuning ({v['incidents']} incidents), 95% CI {v['gw_ac1_ci']}.",
        f"- Learning adds **{v['learn_gain']}** over learning off. Placebo postmortems add {v['placebo_gain']} over the whole run.",
        f"- The graph walk is what matters. Remove the graph and accuracy collapses: **{v['hydra_ac1']}** for the walk against {v['vec_ac1']} for vector search and {v['kv_ac1']} for a 1-hop key-value store.",
        f"- **{v['gain_vs_best']}** over the best baseline ({v['best_baseline']}, {v['best_baseline_ac1']}).",
    ]
    if vm and q:
        out.append(f"- **{ms(q['p50'])}** p50 for a HydraDB 1-hop query and **{ms(vm['online_loop']['verdict_ms']['p50'])}** p50 per verdict, on the {v['vm_name']}, HydraDB on MinIO.")
    if llm:
        a, b = llm["arms"]["llm_plain"], llm["arms"]["llm_memory"]
        out.append(f"- An LLM given the same alerts and map gets {pct(a['ac1']['point'])} (plain) and {pct(b['ac1']['point'])} (with past postmortems) against {pct(llm['arms']['ghostwalk']['ac1']['point'])} for GhostWalk, on a {llm['n_incidents']}-incident subset; it costs about {num(round(a['tokens_per_incident']['mean']))} tokens and {ms(a['latency_ms']['p50'])} per verdict.")
    out.append("- Lessons persist in HydraDB across restarts, each linked to the postmortem that taught it and the incidents that confirmed it.")
    return "\n".join(out)


def table_results8():
    llm = R.get("llm_baseline")
    rows = [
        ["**GhostWalk**", pci(M["ghostwalk"]["ac1"]), "The reference."],
        ["Learning off", pci(M["learning_off"]["ac1"]), "Same engine, no postmortem learning: the gap is what learning adds."],
        ["Placebo postmortems", pci(M["placebo"]["ac1"]), "Random root and edges: learning from noise adds nothing."],
        ["Best baseline (tuned PageRank)", pci(M["pagerank"]["ac1"]), "A graph method with no learning."],
        ["Key-value store, 1 hop", pci(SW["kv_1hop"]["ac1"]), "Direct neighbours only: it misses multi-hop dependencies."],
        ["Vector search (pgvector)", pci(SW["pgvector"]["ac1"]), "Similar text is not a causal path."],
    ]
    if llm:
        a = llm["arms"]["llm_plain"]
        rows.append([f"LLM, plain (n={llm['n_incidents']} subset)", pci(a["ac1"]), "Costs tokens and seconds per verdict, with no graph path behind the answer."])
    rows.append(["Perfect map (oracle)", pci(M["oracle"]["ac1"]), "The ceiling if every dependency were known."])
    return md_table(["approach", "AC@1 (95% CI)", "takeaway"], rows)


def replay_lines():
    rp = R.get("replays")
    if not rp:
        return "Not run yet."
    lines = []
    rank = lambda x: "first" if x["root_rank"] == 1 else "not ranked" if x["root_rank"] is None else f"rank {x['root_rank']}"
    for s in rp["scenarios"]:
        a, b = s["stages"][0], s["stages"][1]
        lines.append(f"- **{s['short']}.** Official map without the hidden dependency: top-1 `{a['top1']}` ({a['confidence']:.2f}), real root {rank(a)}. After one learned edge: top-1 `{b['top1']}` ({b['confidence']:.2f}), real root {rank(b)}.")
    return "\n".join(lines) + f"\n\n*{rp['label']}* The scenarios are in [`docs/replays/`](docs/replays)."


def gw_why_example():
    ex = json.loads((ROOT / "docs" / "cli-examples" / "examples.json").read_text(encoding="utf8"))
    for e in ex:
        if e["title"] == "who broke it":
            out = e["output"]
            return out if out.startswith("$") else f"$ {e['cmd']}\n\n{out}"
    return ""


def mermaid_engine():
    return """flowchart TD
    A[Alerts] --> B[Resolve aliases to services]
    B --> C[Candidate roots: alerting services and what they depend on]
    C --> D["Reach: limited Bellman-Ford, up to 5 hops, cost = -ln w"]
    D --> E["Score each candidate: noisy-OR over every alert it would explain"]
    E --> F[Add onset order and priors]
    F --> G[Normalise to a confidence]
    G --> H{Confidence above the abstain threshold?}
    H -- yes --> I[Verdict: ranked roots, path, explanation]
    H -- no --> J[Verdict: not sure, with the ranked candidates]"""


def mermaid_learner():
    return """flowchart TD
    A[Postmortem: three fields] --> D[Proposals]
    B[GitHub postmortem issue] --> D
    C[Importer: reads a postmortem text] --> D
    D --> E["Review: a person approves or edits"]
    E --> F[Background write queue: ordered and journalled]
    F --> G[HydraDB writes: Lesson, Postmortem, Incident]
    G --> H[Revision bump]
    H --> I[Write-through cache applies the same change]
    I --> J[Next verdict uses the learned edge]"""


def v_placebo_gain():
    return pts(M['placebo']['ac1']['point'] - M['learning_off']['ac1']['point'])


def cumulative_gain_svg(theme="light"):
    """The headline chart, 'What learning adds': cumulative paired gain over learning off for incidents 1..n (n = 1..60), GhostWalk with a shaded 95% bootstrap-by-company band and the placebo dotted with a light band.
    Drawn from results.json learning_curve.cumulative_gain; the end labels are the final values. theme is "light" or "dark"."""
    cg = R["learning_curve"]["cumulative_gain"]
    gw, pl = cg["series"]["ghostwalk_minus_learning_off"], cg["series"]["placebo_minus_learning_off"]
    dark = theme == "dark"
    bg, ink, muted, grid, zero = ("#14131C", "#ECEBF4", "#A6A5B4", "#2B2A38", "#9A99A8") if dark else ("#FFFFFF", "#1B1A24", "#6B6B76", "#E6E6EC", "#8A8A96")
    violet, amber = ("#9C86FF", "#F0A93B") if dark else ("#6A4BFF", "#D98A00")
    W, H, L, Bm, T, Rr = 780, 416, 58, 70, 52, 96
    vals = [v * 100 for p in gw + pl for v in (p["gain"], p["lo"], p["hi"])]
    lo, hi = min(-2.0, (int(min(vals) / 2) - 1) * 2.0), (int(max(vals) / 2) + 1) * 2.0
    n0, n1 = gw[0]["n"], gw[-1]["n"]
    x = lambda n: L + (n - n0) * (W - L - Rr) / (n1 - n0)
    y = lambda v: T + (hi - v) * (H - T - Bm) / (hi - lo)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" role="img" aria-label="What learning adds: cumulative accuracy gain over no learning by incidents seen per company, GhostWalk with a 95 percent band against placebo postmortems" font-family="system-ui, sans-serif">',
           f'<rect width="{W}" height="{H}" rx="12" fill="{bg}"/>',
           f'<text x="{L}" y="22" font-size="15" font-weight="600" fill="{ink}">What learning adds</text>',
           f'<text x="{L}" y="40" font-size="11.5" fill="{muted}">Cumulative over incidents 1..n. {META["companies"]} held-out companies, {num(META["incidents"])} incidents. Band = 95% bootstrap by company.</text>']
    t = lo
    while t <= hi + 1e-9:
        z = abs(t) < 1e-9
        out.append(f'<line x1="{L}" x2="{W - Rr}" y1="{y(t):.1f}" y2="{y(t):.1f}" stroke="{zero if z else grid}" stroke-width="{1.4 if z else 1}"/><text x="{L - 8}" y="{y(t) + 4:.1f}" text-anchor="end" font-size="11" fill="{muted}">{"0" if z else f"{t:+.0f}"}</text>')
        t += 2
    out.append(f'<text transform="translate(14 {(T + H - Bm) / 2:.0f}) rotate(-90)" text-anchor="middle" font-size="12" fill="{muted}">{cg["y_label"]}</text>')
    for n in (10, 20, 30, 40, 50, 60):
        out.append(f'<text x="{x(n):.1f}" y="{H - Bm + 18}" text-anchor="middle" font-size="11" fill="{muted}">{n}</text>')
    out.append(f'<text x="{(L + W - Rr) / 2:.0f}" y="{H - Bm + 40}" text-anchor="middle" font-size="12" fill="{muted}">{cg["x_label"]}</text>')
    for series, col, op in ((pl, amber, 0.13), (gw, violet, 0.17)):
        up = " ".join(f"{x(p['n']):.1f},{y(p['hi'] * 100):.1f}" for p in series)
        dn = " ".join(f"{x(p['n']):.1f},{y(p['lo'] * 100):.1f}" for p in reversed(series))
        out.append(f'<polygon points="{up} {dn}" fill="{col}" opacity="{op}"/>')
    for series, col, dash, sw in ((pl, amber, "1 6", 2.6), (gw, violet, "", 3.4)):
        d = " ".join(f"{'M' if i == 0 else 'L'}{x(p['n']):.1f},{y(p['gain'] * 100):.1f}" for i, p in enumerate(series))
        out.append(f'<path d="{d}" fill="none" stroke="{col}" stroke-width="{sw}" stroke-linecap="round" stroke-linejoin="round"' + (f' stroke-dasharray="{dash}"' if dash else "") + "/>")
    ends = sorted([(y(gw[-1]["gain"] * 100), pts(gw[-1]["gain"]), violet), (y(pl[-1]["gain"] * 100), pts(pl[-1]["gain"]), amber)])
    if ends[1][0] - ends[0][0] < 16:
        ends[1] = (ends[0][0] + 16, ends[1][1], ends[1][2])
    for yy, label, col in ends:
        out.append(f'<text x="{x(n1) + 8:.1f}" y="{yy + 4:.1f}" font-size="13" font-weight="600" fill="{col}">{label}</text>')
    out.append(f'<line x1="{L}" x2="{L + 24}" y1="{H - 12}" y2="{H - 12}" stroke="{violet}" stroke-width="3.4"/><text x="{L + 30}" y="{H - 8}" font-size="11.5" fill="{muted}">GhostWalk minus learning off</text>')
    out.append(f'<line x1="{L + 222}" x2="{L + 246}" y1="{H - 12}" y2="{H - 12}" stroke="{amber}" stroke-width="2.6" stroke-dasharray="1 6" stroke-linecap="round"/><text x="{L + 252}" y="{H - 8}" font-size="11.5" fill="{muted}">placebo minus learning off</text>')
    out.append("</svg>")
    return chr(10).join(out)


def gain_line():
    """The bold line under the README title: the gains in percentage points, derived like web/src/lib/results.ts gainStats (the LLM gain only if its paired 95% interval excludes 0)."""
    llm = R.get("llm_baseline")
    parts = []
    gp = lambda x: f"{x * 100:+.1f} pts"
    shown = False
    if llm:
        arms = [k for k in llm["arms"] if k.startswith("llm_") and f"ghostwalk_minus_{k}" in llm["paired_ac1"]]
        best = max(arms, key=lambda k: llm["arms"][k]["ac1"]["point"]) if arms else None
        d = llm["paired_ac1"][f"ghostwalk_minus_{best}"] if best else None
        if d and d["ci95"][0] > 0:
            parts.append(f"{gp(d['point'])} vs an LLM")
            shown = True
    if not shown:
        parts.append(f"{gp(R['headline']['gain_vs_best']['point'])} vs best baseline (tuned PageRank)")
    parts.append(f"{gp(-SW['kv_1hop']['delta_vs_reference']['point'])} vs a key-value store")
    parts.append(f"{gp(-SW['pgvector']['delta_vs_reference']['point'])} vs a vector store")
    parts.append(f"{gp(P['ac1']['ghostwalk - learning_off']['point'])} from learning")
    vm = R["ops"].get("vm", {}).get("minio")
    parts.append(f"{ms(vm['online_loop']['verdict_ms']['p50'])} verdict p50" if vm else f"{ms(SW['hydradb']['verdict_ms_p50'])} verdict p50")
    return "**" + " · ".join(parts) + "**"
