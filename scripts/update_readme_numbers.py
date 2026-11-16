"""Regenerates README.md and docs/{ARCHITECTURE,PERFORMANCE,EVALUATION}.md from the templates in docs/templates/ and results.json, and docs/learning-curve.svg.
Every number in those files is computed by scripts/readme_blocks.py from results.json (or from a live read of the code); the templates contain none.

    python scripts/update_readme_numbers.py            write the files, then run the claim audit
    python scripts/update_readme_numbers.py --check    fail if a file is stale or the audit finds a typed number (CI)

Claim audit: a digit in a template's prose (outside code fences, inline code, link targets and a short allow-list of structural tokens such as AC@1 or p95) is a typed number: it fails the run."""
from __future__ import annotations
import json, pathlib, re, sys
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import readme_blocks as B

ROOT = B.ROOT
TEMPLATES = {"README.md": "README.tpl.md", "docs/REFERENCE.md": "REFERENCE.tpl.md", "docs/ARCHITECTURE.md": "ARCHITECTURE.tpl.md", "docs/PERFORMANCE.md": "PERFORMANCE.tpl.md", "docs/EVALUATION.md": "EVALUATION.tpl.md"}

ENV_ROWS = [("AUTH_MODE", "none or clerk", "no", "`clerk`: `/app` needs a Clerk session and every user gets their own workspace; `/demo` stays public."),
            ("CLERK_PUBLISHABLE_KEY, VITE_CLERK_PUBLISHABLE_KEY", "Clerk publishable key", "no (public)", "The browser's Clerk SDK; the second name is the build-time variable on Vercel."),
            ("CLERK_SECRET_KEY", "Clerk secret key", "**yes**", "Only for tooling that talks to Clerk's backend API (the live smoke test). The API does not need it to verify sessions."),
            ("CLERK_JWKS_URL", "Clerk's JWKS URL", "no", "Session tokens are verified against these keys (cached); issuer and authorised party are checked."),
            ("GW_STORE", "memory or hydradb", "no", "`hydradb`: the graph and the learner's memory live in HydraDB."),
            ("HYDRA_URL, HYDRA_TOKEN", "HydraDB address and bearer token", "token: **yes**", "Defaults to the compose service; the token must be at least thirty-two bytes."),
            ("GW_DEMO_INCIDENTS", "past incidents in the demo workspace", "no", "The seeded history the demo starts with."),
            ("GW_PUBLIC_DEMO", "0 or 1", "no", "`1`: settings, onboarding and webhooks are read-only in the demo sandbox, and it is rebuilt every night."),
            ("GW_ADMIN_TOKEN", "admin token", "**yes**", "Lets `POST /api/demo/reset` rebuild the demo on demand."),
            ("GW_RATE_LIMIT", "requests/seconds, e.g. 60/60", "no", "Off by default (`0`). An abuse guard for a public deployment, per client, on `/v1/*` and on POSTs; it answers 429 \"Slow down, try again in a minute\". The hosted demo sets `60/60` in `deploy/.env`."),
            ("GW_CORS_ORIGINS", "comma-separated origins", "no", "The frontend origin(s) allowed to call the API; also the authorised parties for Clerk sessions."),
            ("GW_HOME", "folder", "no", "Where the `gw` CLI keeps its workspace."),
            ("GW_URL, GW_TOKEN", "API address and a workspace token", "token: **yes**", "Point `gw` and `gw mcp` at a hosted GhostWalk. Tokens look like `gw_live_<workspace>_<secret>`; only a hash is stored and the token is shown once."),
            ("GEMINI_API_KEY, GROQ_API_KEY", "LLM keys", "**yes**", "Only for `eval/llm_baseline.py` and `eval/replays.py`. GhostWalk itself calls no LLM."),
            ("GITHUB_APP_ID, GITHUB_APP_PRIVATE_KEY, GITHUB_WEBHOOK_SECRET, GITHUB_PR_TOKEN", "GitHub App settings", "**yes**", "Optional: map import from GitHub, postmortem issues, the `gw diff` PR comment.")]


def env_table():
    return B.md_table(["variable", "what it is", "secret?", "notes"], [list(r) for r in ENV_ROWS])


def cli_reference():
    ex = json.loads((ROOT / "docs" / "cli-examples" / "examples.json").read_text(encoding="utf8"))
    parts = ["Every block below is the real output of the command, captured by `scripts/capture_cli_examples.py` (in a throwaway workspace; `doctor` and `why-edge` against the live deployment)."]
    for e in ex:
        out = e["output"]
        body = out if out.startswith("$") else f"$ {e['cmd']}\n\n{out}"
        parts.append(f"**{e['title'][0].upper() + e['title'][1:]}**\n\n```\n{body}\n```")
    return "\n\n".join(parts)


def mermaid():
    storage = "MinIO (S3-compatible object storage)" if "minio" in B.R.get("ops", {}).get("vm", {}) else "persistent volume"
    arch = f"""flowchart LR
    subgraph SRC[Alert sources]
        W["Alertmanager and Grafana webhooks"]
        C[gw CLI]
        M["MCP clients: Claude Code, Cursor"]
    end
    WEB[Web app on Vercel] --> API
    W --> API
    C --> API
    M --> API
    CLERK["Clerk: sign-in and sessions"] -.-> WEB
    CLERK -.-> API
    DEMO["/demo: public sandbox workspace"] -.-> API
    subgraph API[API: FastAPI]
        ENG["Engine: resolve aliases, walk, score, verdict"]
        CACHE[("Revision-checked write-through cache")]
        LRN["Learner: propose, review, apply"]
        Q["Background write queue: ordered and journalled"]
    end
    ENG <--> CACHE
    LRN --> Q
    Q --> H
    CACHE <--> H[("HydraDB: graph and memory")]
    H --> S[("Storage: {storage}")]"""
    seq = """sequenceDiagram
    autonumber
    participant P as Alert source
    participant A as GhostWalk API
    participant E as Engine
    participant H as HydraDB
    participant R as On-call engineer
    P->>A: alerts arrive (webhook, CLI or MCP)
    A->>E: resolve aliases, walk the graph
    E->>H: revision check (cached graph)
    E-->>A: ranked roots, path, confidence
    A-->>R: verdict in milliseconds
    R->>R: fixes the real cause
    R->>A: postmortem (three fields, a GitHub issue, or an importer)
    A-->>R: proposals: new edges, reweights, aliases
    R->>A: approves
    A->>H: Lesson, Postmortem and Incident written (background queue)
    H-->>A: revision bumps (the UI shows saving, then saved)
    P->>A: the next incident
    A->>E: the walk now uses the learned edge
    E-->>A: verdict"""
    er = """erDiagram
    SERVICE ||--o{ SERVICE : "DEPENDS_ON (w, cost)"
    INCIDENT ||--o{ ALERT : RAISED
    ALERT }o--|| SERVICE : ON
    POSTMORTEM ||--|| INCIDENT : ABOUT
    LESSON }o--|| POSTMORTEM : TAUGHT_BY
    LESSON }o--o{ INCIDENT : CONFIRMED_BY
    SERVICE {
        int id
        string name
        string kind
        int tier
    }
    INCIDENT {
        int seq
        string name
        float ts
    }
    ALERT {
        string name
        string signal
        float ts
    }
    POSTMORTEM {
        int incident_id
        string root_name
        string path
        string missed
    }
    LESSON {
        string src_name
        string dst_name
        float w
        string state
        int created_seq
    }"""
    return arch, seq, er


def transport_evidence(d):
    rows = []
    for where, d2 in d["evidence_p50_ms"].items():
        for client, q in d2.items():
            if q:
                rows.append([where, client, B.ms(q["one_hop"])])
    return B.md_table(["where", "client", "1-hop query p50"], rows)


def simulator_knobs():
    try:
        import dataclasses
        from gwsim.world import Knobs
        rows = [[f.name, repr(f.default) if f.default is not dataclasses.MISSING else ""] for f in dataclasses.fields(Knobs)]
        return B.md_table(["knob", "default"], rows)
    except Exception as e:                                                       # pragma: no cover
        return f"(simulator knobs unavailable: {e})"


def pagerank_grid():
    pr = B.R["baseline_fairness"]["pagerank"]
    return f"{pr['grid_budget']} settings on DEV (restart {pr['grid']['restart']}, direction {pr['grid']['direction']}, weighted {pr['grid']['weighted']}, onset {pr['grid']['onset']}); chosen {pr['settings']}; DEV AC@1 {B.pct(pr['dev_ac1_tuned'])} tuned against {B.pct(pr['dev_ac1_untuned_default'])} untuned."


def placebo_late():
    pg = B.R["learning_curve"]["paired_gain"]
    p, g = pg["series"]["placebo_minus_learning_off"], pg["series"]["ghostwalk_minus_learning_off"]
    if not all(x["ci95"] for x in p):
        return ""
    last = p[-1]
    return (f"Over the whole run the placebo is {B.v_placebo_gain()} against learning off. By incident number it is not flat everywhere: in the last bin of five (incidents {last['from'] + 1} to {last['to'] + 1}) the placebo is "
            f"{B.pts(last['gain'])} against learning off (95% CI {last['ci95'][0] * 100:+.1f} to {last['ci95'][1] * 100:+.1f}), so by then learning from random postmortems has hurt; we did not isolate why. "
            f"GhostWalk's gain in the same bin is {B.pts(g[-1]['gain'])} (95% CI {g[-1]['ci95'][0] * 100:+.1f} to {g[-1]['ci95'][1] * 100:+.1f}). "
            "The per-bin bands are paired company bootstraps over the per-company tables stored under `learning_curve.paired_gain.tables`.")


def blocks():
    v = B.values()
    arch, seq, er = mermaid()
    mg = B.R["memory_graph"]
    lp1, lp2, dep = B.table_learning()
    nr, nr_def, nr_share = B.table_novel_repeat()
    tm, ms_sent = B.table_memory()
    tc, change_main, change_helps = B.table_change()
    d = B.R["ops"]["hydradb_latency"]["diagnosis"]
    lv = B.R["poisoning"]["levels"]
    llm = B.R.get("llm_baseline")
    v.update({
        "guard_sentence": f"On this benchmark, removing the guard changes top-1 accuracy by {B.pts(B.M['ablate_guard']['ac1']['point'] - B.M['ghostwalk']['ac1']['point'])}, inside the noise, so no benefit from it is measured here.",
        "vm_walk_ms": B.ms(B.R["ops"]["vm"]["minio"]["warm"]["verdict_in_memory_ms"]["p50"]) if "minio" in B.R["ops"].get("vm", {}) else "small",
        "llm_n": str(llm["n_incidents"]) if llm else "no",
        "llm_label": llm["label"] if llm else "No LLM baseline was run.",
        "loom_link": f"[**Loom**]({v['loom']}) · " if v.get("loom") else "",
        "mermaid_architecture": arch, "mermaid_sequence": seq, "mermaid_er": er, "mermaid_lifecycle": B.mermaid_lifecycle(),
        "why_edge_example": mg["why_edge_example"]["text"], "worked_example": B.worked_example(),
        "poison_sentence": f"With {v['wrong_pm_default']} of postmortems deliberately wrong, learning still adds {B.ptsci(lv[min(lv, key=float)]['gain'])}.",
        "table_main": B.table_main(), "table_compare": B.table_compare(), "honest_sentences": B.honest_sentences(), "table_llm": B.table_llm(),
        "table_learning_main": lp1, "table_learning_ablation": lp2, "table_depth": dep, "table_poison": B.table_poison(),
        "novel_definition": nr_def, "share_repeat": nr_share, "table_novel_repeat": nr, "table_selective": B.table_selective(),
        "table_memory": tm, "memory_sentence": ms_sent, "table_change": tc, "change_main": change_main, "change_helps": change_helps,
        "table_replays": B.table_replays(), "results_lines": B.results_lines(), "table_results8": B.table_results8(), "replay_lines": B.replay_lines(), "gw_why_example": B.gw_why_example(), "mermaid_engine": B.mermaid_engine(), "mermaid_learner": B.mermaid_learner(), "table_checklist": B.table_checklist(),
        "table_machines": B.table_machines(), "table_queries": B.table_queries(), "table_verdicts": B.table_verdicts(), "table_scale": B.table_scale(), "table_load": B.table_load(),
        "env_table": env_table(), "cli_reference": cli_reference(), "transport_cause": d["cause"], "transport_also_fixed": "; ".join(d["also_fixed"]),
        "transport_evidence": transport_evidence(d), "engine_gate": B.R["latency"]["gate"]["rule"], "simulator_knobs": simulator_knobs(), "pagerank_grid": pagerank_grid(),
        "history_table": B.md_table(["engine", "top-1 hits"], [[h["engine"], f"{h['hits']} of {B.num(h['of'])}"] for h in B.META["ac1_history"]]),
        "scale_engine_note": B.R["latency"]["generator"], "timed": str(B.R["ops"]["hydradb_latency"]["warm"]["per_query"]["one_hop"]["n"]), "warmup": str(B.R["ops"]["hydradb_latency"]["warm"]["per_query"]["one_hop"]["warmup"]),
        "placebo_late": placebo_late(), "scale_sizes": ", ".join(f"{int(k):,}" for k in sorted(B.R["scale"]["path_query"]["sizes"], key=int)), "machine_note": B.R["latency"]["meta"]["platform"],
    })
    return v


# ---------------------------------------------------------------------------------------------- filling and auditing
PLACEHOLDER = re.compile(r"\{\{([a-z0-9_]+)\}\}")
ALLOW = [l.strip() for l in (HERE / "audit_allow.txt").read_text(encoding="utf8").splitlines() if l.strip() and not l.startswith("#")]


def fill(tpl: str, v: dict) -> str:
    def sub(m):
        if m.group(1) not in v:
            raise KeyError(f"template placeholder {{{{{m.group(1)}}}}} has no value")
        return str(v[m.group(1)])
    return PLACEHOLDER.sub(sub, tpl)


def audit(name: str, tpl: str) -> list[str]:
    """Typed numbers in a template's prose."""
    bad, fence = [], False
    for i, line in enumerate(tpl.splitlines(), 1):
        if line.lstrip().startswith("```"):
            fence = not fence
            continue
        if fence:
            continue
        t = re.sub(r"`[^`]*`", "", line)                                          # inline code
        t = re.sub(r"\]\([^)]*\)", "]", t)                                        # link targets
        t = re.sub(r"https?://\S+", "", t)
        t = re.sub(r"<[^>]*>", "", t)                                             # html tags and attributes
        t = PLACEHOLDER.sub("", t)
        for a in ALLOW:
            t = re.sub(a, "", t, flags=re.M)
        if re.search(r"\d", t):
            bad.append(f"{name}:{i}: {line.strip()[:110]}")
    return bad


def main():
    check = "--check" in sys.argv
    v = blocks()
    problems, stale = [], []
    for out, tpl_name in TEMPLATES.items():
        tpl_path = ROOT / "docs" / "templates" / tpl_name
        if not tpl_path.exists():
            continue
        tpl = tpl_path.read_text(encoding="utf8")
        problems += audit(tpl_name, tpl)
        text = fill(tpl, v).rstrip() + "\n"
        path = ROOT / out
        if check:
            if not path.exists() or path.read_text(encoding="utf8").replace("\r\n", "\n") != text:
                stale.append(out)
        else:
            path.write_text(text, encoding="utf8")
    for name, theme in (("learning-curve.svg", "light"), ("learning-curve-dark.svg", "dark")):
        svg, sp = B.paired_gain_svg(theme), ROOT / "docs" / name
        if check:
            if not sp.exists() or sp.read_text(encoding="utf8").replace("\r\n", "\n") != svg:
                stale.append("docs/" + name)
        else:
            sp.write_text(svg, encoding="utf8")
    if not check:
        print("wrote", ", ".join(TEMPLATES), "and docs/learning-curve(-dark).svg (the PNGs: cd web && node ../scripts/render_png.mjs)")
    if problems:
        print("CLAIM AUDIT FAILED: typed numbers in prose (generate them from results.json instead):")
        print("\n".join("  " + p for p in problems))
    if stale:
        print("STALE (run scripts/update_readme_numbers.py):", ", ".join(stale))
    if problems or stale:
        sys.exit(1)
    print("claim audit passed: no typed numbers in the prose of", ", ".join(TEMPLATES.values()))


if __name__ == "__main__":
    main()
