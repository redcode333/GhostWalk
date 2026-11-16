import { useEffect } from "react"
import { apiUrl } from "@/lib/api"
import { CumulativeChart, PairedGainChart } from "@/components/LearningCharts"
import { loadResults, METHOD_LABEL, ms, pct, proofStrip, pts, type CI, type Results } from "@/lib/results"
import { Err, Muted, useLoad } from "@/components/common"
import { H1, Page } from "@/components/AppShell"

const f3 = (x: number) => x.toFixed(3)
const ci = (c: CI) => `${f3(c.ci95[0])}–${f3(c.ci95[1])}`

function MemorySchema() {
  const box = (x: number, y: number, label: string, hot = false) => (
    <g key={label + x}><rect x={x} y={y} width="112" height="34" rx="9" fill="var(--card, var(--bg))" stroke={hot ? "var(--accent)" : "var(--line)"} strokeWidth="1.2" />
      <text x={x + 56} y={y + 21} textAnchor="middle" fontSize="13" fill="var(--text-2)" fontFamily="Geist, sans-serif">{label}</text></g>)
  const arrow = (d: string, lx: number, ly: number, label: string, anchor: "start" | "middle" | "end" = "middle") => (
    <g key={label}><path d={d} fill="none" stroke="var(--text-4)" strokeWidth="1.2" markerEnd="url(#mem-arrow)" />
      <text x={lx} y={ly} textAnchor={anchor} fontSize="10.5" fill="var(--text-4)" fontFamily="Geist Mono, monospace">{label}</text></g>)
  return (
    <svg viewBox="0 0 740 190" role="img" aria-label="Memory schema: Lesson TAUGHT_BY Postmortem ABOUT Incident RAISED Alert ON Service; Lesson CONFIRMED_BY Incident; Service DEPENDS_ON Service"
      style={{ width: "100%", maxWidth: 740, height: "auto" }}>
      <defs><marker id="mem-arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="var(--text-4)" /></marker></defs>
      {box(14, 30, "Lesson", true)}{box(204, 30, "Postmortem")}{box(394, 30, "Incident")}{box(584, 30, "Alert")}{box(584, 130, "Service")}{box(394, 130, "Service")}
      {arrow("M126,47 H202", 164, 40, "TAUGHT_BY")}{arrow("M316,47 H392", 354, 40, "ABOUT")}{arrow("M506,47 H582", 544, 40, "RAISED")}
      {arrow("M640,64 V128", 646, 100, "ON", "start")}{arrow("M582,147 H508", 545, 141, "DEPENDS_ON")}
      {arrow("M70,64 V104 H450 V64", 260, 118, "CONFIRMED_BY")}
    </svg>)
}


const ci2 = (c: CI) => `${(c.point * 100).toFixed(1)}% [${(c.ci95[0] * 100).toFixed(1)}, ${(c.ci95[1] * 100).toFixed(1)}]`
const dpts = (c: { point: number; ci95?: [number, number] }) => `${c.point >= 0 ? "+" : "−"}${Math.abs(c.point * 100).toFixed(1)} pts${c.ci95 ? ` (${(c.ci95[0] * 100).toFixed(1)} to ${(c.ci95[1] * 100).toFixed(1)})` : ""}`.replace("+-", "−")

/** One table, same incidents: every store and baseline, the controls, and the LLM on its marked subset. Everything is read from results.json. */
function CompareTable({ r }: { r: any }) {
  const sw = r.store_swap?.backends ?? {}, M = r.methods ?? {}, P = r.paired?.ac1 ?? {}, ops = r.ops ?? {}, llm = r.llm_baseline
  const lat = (b: any) => (b ? `${ms(b.verdict_ms_p50)} / ${ms(b.verdict_ms_p95)} ms` : "")
  const neg = (c: any) => ({ point: -c.point, ci95: [-c.ci95[1], -c.ci95[0]] as [number, number] })
  const rows: [string, string, string, string, string, string][] = []
  const rowId = (name: string) => name.startsWith("Key-value") ? "cmp-kv" : name.startsWith("Vector search") ? "cmp-vector" : name.startsWith("Personalized PageRank") ? "cmp-pagerank" : name.startsWith("GhostWalk with learning off") ? "cmp-learning-off" : name.startsWith("LLM + memory") ? "cmp-llm" : name.startsWith("LLM plain") ? "cmp-llm-plain" : undefined
  const add = (name: string, ac: CI | undefined, delta: string, latency: string, tokens: string, learns: string) => ac && rows.push([name, ci2(ac), delta, latency, tokens, learns])
  add("GhostWalk on HydraDB", sw.hydradb?.ac1, "reference", lat(sw.hydradb), "0", "yes")
  add("Same engine on Postgres (recursive CTE)", sw.pg_cte?.ac1, dpts(sw.pg_cte?.delta_vs_reference ?? { point: 0 }), lat(sw.pg_cte), "0", "yes")
  add("Key-value store, 1 hop", sw.kv_1hop?.ac1, dpts(sw.kv_1hop?.delta_vs_reference ?? { point: 0 }), lat(sw.kv_1hop), "0", "yes (1 hop only)")
  add("Vector search over postmortems (pgvector)", sw.pgvector?.ac1, dpts(sw.pgvector?.delta_vs_reference ?? { point: 0 }), lat(sw.pgvector), "0", "adds text, no graph")
  add("TF-IDF retrieval of past postmortems", M.retrieval?.ac1, P["ghostwalk - retrieval"] ? dpts(neg(P["ghostwalk - retrieval"])) : "", ops.retrieval ? `${ms(ops.retrieval.verdict_ms_p50)} / ${ms(ops.retrieval.verdict_ms_p95)} ms` : "", "0", "adds text, no graph")
  add("Deepest alerting service", M.deepest?.ac1, P["ghostwalk - deepest"] ? dpts(neg(P["ghostwalk - deepest"])) : "", ops.deepest ? `${ms(ops.deepest.verdict_ms_p50)} / ${ms(ops.deepest.verdict_ms_p95)} ms` : "", "0", "no")
  add("Personalized PageRank (tuned on DEV)", M.pagerank?.ac1, P["ghostwalk - pagerank"] ? dpts(neg(P["ghostwalk - pagerank"])) : "", ops.pagerank ? `${ms(ops.pagerank.verdict_ms_p50)} / ${ms(ops.pagerank.verdict_ms_p95)} ms` : "", "0", "no")
  add("Random", M.random?.ac1, M.random && M.ghostwalk ? dpts({ point: M.random.ac1.point - M.ghostwalk.ac1.point }) : "", ops.random ? `${ms(ops.random.verdict_ms_p50)} / ${ms(ops.random.verdict_ms_p95)} ms` : "", "0", "no")
  add("GhostWalk with learning off", M.learning_off?.ac1, P["ghostwalk - learning_off"] ? dpts(neg(P["ghostwalk - learning_off"])) : "", "", "0", "no")
  add("GhostWalk with placebo postmortems", M.placebo?.ac1, P["ghostwalk - placebo"] ? dpts(neg(P["ghostwalk - placebo"])) : "", "", "0", "learns noise")
  if (llm) {
    for (const [k, label] of [["llm_plain", "LLM plain"], ["llm_memory", "LLM + memory (5 past postmortems)"]] as const) {
      const a = llm.arms?.[k]
      if (a) rows.push([`${label} (n=${llm.n_incidents} subset)`, ci2(a.ac1), llm.paired_ac1?.[`ghostwalk_minus_${k}`] ? dpts(neg(llm.paired_ac1[`ghostwalk_minus_${k}`])) + " (on the subset)" : "", `${ms(a.latency_ms.p50)} / ${ms(a.latency_ms.p95)} ms`, `${Math.round(a.tokens_per_incident.mean).toLocaleString()}`, "no"])
    }
  }
  return (
    <section id="compare" className="card" style={{ padding: 18, overflowX: "auto", scrollMarginTop: 80 }} aria-label="How GhostWalk compares">
      <h2 style={{ margin: 0, fontSize: 16 }}>How GhostWalk compares</h2>
      <p style={{ margin: "2px 0 10px", fontSize: 13, color: "var(--text-4)" }}>Same held-out incidents, top-1 accuracy with 95% intervals. Store rows change only the store; the LLM rows are marked with their subset size (same incidents, GhostWalk's own accuracy on that subset is in the paired difference).</p>
      <table className="mono" style={{ fontSize: 12.5, borderCollapse: "collapse", minWidth: 760 }}>
        <thead><tr style={{ color: "var(--text-4)", textAlign: "left" }}>{["approach", "AC@1 [95% CI]", "Δ vs GhostWalk", "verdict p50 / p95", "tokens per verdict", "learns from postmortems?"].map((h) => <th key={h} style={{ padding: "6px 12px 6px 0", fontFamily: "Geist", fontWeight: 500 }}>{h}</th>)}</tr></thead>
        <tbody>{rows.map((row, i) => <tr key={row[0]} id={rowId(row[0])} style={{ borderTop: "1px solid var(--line)", fontWeight: i === 0 ? 600 : 400 }}>{row.map((c, j) => <td key={j} style={{ padding: "7px 12px 7px 0", fontFamily: j === 0 || j === 5 ? "Geist" : undefined }}>{c}</td>)}</tr>)}</tbody>
      </table>
      <p style={{ margin: "10px 0 0", fontSize: 13, color: "var(--text-3)" }}>
        {sw.kv_1hop && sw.pgvector ? `Stores that cannot walk the graph lose ${Math.abs(sw.kv_1hop.delta_vs_reference.point * 100).toFixed(1)} to ${Math.abs(sw.pgvector.delta_vs_reference.point * 100).toFixed(1)} pts: a 1-hop key-value store scores ${dpts(sw.kv_1hop.delta_vs_reference)} and vector search over the same postmortems ${dpts(sw.pgvector.delta_vs_reference)}. ` : ""}
        {sw.pg_cte ? `A Postgres recursive CTE matches accuracy (${dpts(sw.pg_cte.delta_vs_reference)}; it walks the graph too), so the gain comes from multi-hop walks, not from the store, and Postgres is faster on raw path queries at our sizes. ` : ""}
        {llm ? `The LLM costs about ${Math.round(llm.arms.llm_plain.tokens_per_incident.mean).toLocaleString()} tokens and ${ms(llm.arms.llm_plain.latency_ms.p50)} ms per verdict (${llm.arms.llm_plain.invalid_output_rate > 0 ? `${(llm.arms.llm_plain.invalid_output_rate * 100).toFixed(0)}% invalid outputs; ` : ""}${(llm.arms.llm_plain.provider_share.gemini * 100).toFixed(0)}% Gemini, ${(llm.arms.llm_plain.provider_share.groq * 100).toFixed(0)}% Groq): ${ci2(llm.arms.llm_plain.ac1)} AC@1. ` : ""}
        GhostWalk's learning lives in HydraDB: lessons are linked to the postmortems and incidents that taught them, and they survive restarts.
      </p>
      {llm && <p style={{ margin: "6px 0 0", fontSize: 12, color: "var(--text-4)" }}>{llm.label} Subset: {llm.n_incidents} incidents across {llm.companies} companies, chosen with a fixed seed before any call.</p>}
    </section>
  )
}

function ReplayCards({ r }: { r: any }) {
  const rp = r.replays
  if (!rp) return null
  return (
    <section className="card" style={{ padding: 18 }} aria-label="Real-outage replays">
      <h2 style={{ margin: 0, fontSize: 16 }}>Real-outage replays</h2>
      <p style={{ margin: "2px 0 10px", fontSize: 13, color: "var(--text-4)" }}>{rp.label} Two scenarios, one run each: not a sample, not an accuracy number. Run them live from Incidents (the Replay buttons).</p>
      <div style={{ overflowX: "auto" }}>
        <table className="mono" style={{ fontSize: 12.5, borderCollapse: "collapse", minWidth: 700 }}>
          <thead><tr style={{ color: "var(--text-4)", textAlign: "left" }}>{["scenario", "official map", "after one tentative edge", "after it is confirmed", "deepest alert", "LLM"].map((h) => <th key={h} style={{ padding: "6px 12px 6px 0", fontFamily: "Geist", fontWeight: 500 }}>{h}</th>)}</tr></thead>
          <tbody>{rp.scenarios.map((s: any) => (
            <tr key={s.id} style={{ borderTop: "1px solid var(--line)" }}>
              <td style={{ padding: "7px 12px 7px 0", fontFamily: "Geist" }}><a href={s.source.url} target="_blank" rel="noreferrer" style={{ color: "var(--accent-text)" }}>{s.short}</a><div style={{ color: "var(--text-4)" }}>real root: {s.root}</div></td>
              {s.stages.map((st: any) => <td key={st.stage} style={{ padding: "7px 12px 7px 0" }}>{st.top1} {st.confidence.toFixed(2)}<div style={{ color: "var(--text-4)" }}>root: {st.root_rank == null ? "not ranked" : `rank ${st.root_rank}`}</div></td>)}
              <td style={{ padding: "7px 12px 7px 0" }}>{s.deepest_alert.top1}<div style={{ color: "var(--text-4)" }}>root: {s.deepest_alert.root_rank == null ? "not ranked" : `rank ${s.deepest_alert.root_rank}`}</div></td>
              <td style={{ padding: "7px 12px 7px 0" }}>{s.llm ? s.llm.top1 : "not run"}{s.llm && <div style={{ color: "var(--text-4)" }}>root: {s.llm.root_rank == null ? "not ranked" : `rank ${s.llm.root_rank}`}</div>}</td>
            </tr>))}</tbody>
        </table>
      </div>
      <p style={{ margin: "8px 0 0", fontSize: 13, color: "var(--text-3)" }}>With the hidden dependency missing from the map, GhostWalk is confidently wrong, as the responders were. After one learned edge the real root enters the ranking but is not first. We do not claim GhostWalk would have prevented either outage.</p>
    </section>
  )
}

export default function Proof() {
  const { data: r, error } = useLoad(loadResults, [])
  useEffect(() => { if (r && window.location.hash) window.setTimeout(() => document.getElementById(window.location.hash.slice(1))?.scrollIntoView({ block: "start" }), 60) }, [r])
  if (error) return <Page><Err>{error}</Err></Page>
  if (!r) return <Page><H1 title="Proof" /><Muted>No results.json yet. Run <span className="mono">make eval</span>.</Muted></Page>
  const strip = proofStrip(r)
  const order = ["ghostwalk", "pagerank", "retrieval", "deepest", "random"]
  const ops = r.ops ?? {}
  const sw = r.store_swap
  const st = (k: string, label: string) => {
    const b = sw?.backends?.[k]
    return b ? { label, v: f3(b.ac1.point), sub: b.delta_vs_reference ? `${pts(b.delta_vs_reference.point)} (${pts(b.delta_vs_reference.ci95[0])} to ${pts(b.delta_vs_reference.ci95[1])})` : "reference" } : null
  }
  const refName = (k: string) => (sw && sw.reference === k ? " (reference)" : "")
  const tiles = [st("hydradb", "HydraDB paths" + refName("hydradb")), st("pg_cte", "Postgres recursive"), st("pgvector", "pgvector search"), st("kv_1hop", "Key-value, 1 hop"), st("inmemory", "In-memory graph" + refName("inmemory"))].filter(Boolean) as { label: string; v: string; sub: string }[]
  const depth = (r as any).depth as Record<string, CI> | undefined
  const vecB = sw?.backends?.pgvector, graphB = sw?.backends?.[sw?.reference ?? ""]
  const gv = vecB && graphB ? { graph: graphB.ac1, vec: vecB.ac1 } : null
  const kvB = sw?.backends?.kv_1hop, cteB = sw?.backends?.pg_cte
  const refLabel = sw ? (sw.reference === "hydradb" ? "HydraDB" : "the in-memory graph") : ""
  const sc = r.scale?.path_query?.sizes
  const scaleRows = sc ? Object.entries(sc).sort((a, b) => +a[0] - +b[0]) : []
  const pgFaster = scaleRows.length > 0 && scaleRows.every(([, e]) => ["hops_3", "hops_5"].every((h) => e.path_query[h].postgres.p50 < e.path_query[h].hydradb.p50))
  const beforeFix = (r as any).scale_before_transport_fix?.path_query?.sizes?.["1000"]?.path_query?.hops_3?.hydradb?.p50 as number | undefined
  const warm = (r.ops as any)?.hydradb_latency?.warm as any
  const loop = (r.ops as any)?.hydradb_online_loop_test as any
  const mg = (r as any).memory_graph as any
  const mr = (r as any).memory_retrieval as any
  return (
    <Page>
      <H1 title="Proof" sub={`Held-out ${r.meta.split} split: ${r.meta.companies} companies, ${r.meta.incidents.toLocaleString()} incidents. 95% bootstrap intervals.`}
        right={<a className="btn btn-glass" href={apiUrl("/results.json")} download>Download results.json</a>} />
      <p style={{ margin: 0, padding: "14px 18px", border: "1px solid var(--accent)", borderRadius: 14, fontSize: 17, fontWeight: 500, background: "rgba(var(--lrgb), .03)" }}>
        Evaluated on {r.meta.companies} held-out companies never used for development or tuning; learning starts from zero at each company.
      </p>
      <CompareTable r={r} />
      <ReplayCards r={r} />
      {gv && (
        <section className="card" style={{ padding: 18 }} aria-label="Graph vs vector search">
          <h2 style={{ margin: 0, fontSize: 16 }}>Graph vs vector search</h2>
          <p style={{ margin: "2px 0 12px", fontSize: 13, color: "var(--text-4)" }}>Top-1 accuracy on the same held-out incidents, 95% intervals over companies.</p>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 24, alignItems: "flex-end" }}>
            {[["GhostWalk, multi-hop weighted walk", gv.graph, "var(--accent)"], ["Vector search over postmortem text (pgvector)", gv.vec, "var(--text-4)"]].map(([label, v, c]) => (
              <div key={label as string} style={{ flex: "1 1 min(260px, 100%)" }}>
                <div className="mono" style={{ fontSize: 40, fontWeight: 600 }}>{((v as CI).point * 100).toFixed(1)}%</div>
                <div aria-hidden="true" style={{ height: 8, borderRadius: 4, background: "var(--muted)", margin: "6px 0" }}><div style={{ height: "100%", width: `${(v as CI).point * 100}%`, borderRadius: 4, background: c as string }} /></div>
                <div style={{ fontSize: 14, color: "var(--text-3)" }}>{label as string}</div>
                <div className="mono" style={{ fontSize: 12, color: "var(--text-4)" }}>95% CI {f3((v as CI).ci95[0])}–{f3((v as CI).ci95[1])}</div>
              </div>))}
          </div>
        </section>
      )}
      {mg && mr && (
        <section className="card" style={{ padding: 18, overflowX: "auto" }} aria-label="The memory is the graph">
          <h2 style={{ margin: 0, fontSize: 16 }}>The memory is the graph</h2>
          <p style={{ margin: "4px 0 12px", fontSize: 14, color: "var(--text-3)" }}>
            GhostWalk's learning loop lives in HydraDB: every lesson is a node linked to the postmortems that taught it and the incidents that confirmed it.
          </p>
          <MemorySchema />
          <h3 style={{ margin: "14px 0 6px", fontSize: 14, fontWeight: 500 }}>Why does the map say {mg.why_edge_example.src} depends on {mg.why_edge_example.dst}?</h3>
          <pre className="mono" style={{ margin: 0, fontSize: 12.5, lineHeight: 1.6, whiteSpace: "pre-wrap", color: "var(--text-2)" }}>{mg.why_edge_example.text}</pre>
          <h3 style={{ margin: "14px 0 6px", fontSize: 14, fontWeight: 500 }}>Kill the API, keep the learning</h3>
          <p style={{ margin: 0, fontSize: 13, color: "var(--text-3)" }}>{String(mg.persistence.summary).replaceAll("`", "")}</p>
          <h3 style={{ margin: "14px 0 6px", fontSize: 14, fontWeight: 500 }}>Graph memory against vector memory</h3>
          <p style={{ margin: "0 0 8px", fontSize: 13, color: "var(--text-4)" }}>
            Retrieve the 5 most relevant past incidents of the same company, using only past incidents. hit@5: a retrieved incident has the same root cause (repeat incidents only). 95% intervals over companies.
          </p>
          <table className="mono" style={{ fontSize: 13, borderCollapse: "collapse", minWidth: 560 }}>
            <thead><tr style={{ color: "var(--text-4)", textAlign: "left" }}>{["", "graph (HydraDB)", "vector (pgvector)", "keyword (TF-IDF)"].map((h) => <th key={h} style={{ padding: "6px 14px 6px 0", fontFamily: "Geist", fontWeight: 500 }}>{h}</th>)}</tr></thead>
            <tbody>
              {([["hit@5, repeat incidents", "hit5_repeat", "pct"], ["MRR, repeat incidents", "mrr_repeat", "num"], ["related@5, novel incidents", "related5_novel", "pct"], ["related@5, all incidents", "related5_all", "pct"]] as [string, string, string][]).map(([label, k, kind]) => (
                <tr key={k} style={{ borderTop: "1px solid var(--line)" }}>
                  <td style={{ padding: "8px 14px 8px 0", fontFamily: "Geist" }}>{label} <span style={{ color: "var(--text-4)" }}>(n={mr.arms.graph[k].n})</span></td>
                  {["graph", "vector", "keyword"].map((a) => { const c = mr.arms[a][k] as CI; return <td key={a} style={{ paddingRight: 14 }}>{kind === "pct" ? `${(c.point * 100).toFixed(1)}%` : c.point.toFixed(3)} <span style={{ color: "var(--text-4)" }}>{ci(c)}</span></td> })}
                </tr>))}
              <tr style={{ borderTop: "1px solid var(--line)" }}><td style={{ padding: "8px 14px 8px 0", fontFamily: "Geist" }}>latency p50 / p95 (ms)</td>
                {["graph", "vector", "keyword"].map((a) => <td key={a} style={{ paddingRight: 14 }}>{ms(mr.arms[a].latency_ms.p50)} / {ms(mr.arms[a].latency_ms.p95)}</td>)}</tr>
            </tbody>
          </table>
          <p style={{ margin: "8px 0 0", fontSize: 13, color: "var(--text-3)" }}>
            Graph minus vector on repeat incidents, hit@5: {pts(mr.paired.hit5_repeat.graph_minus_vector.point)} (95% CI {pts(mr.paired.hit5_repeat.graph_minus_vector.ci95[0])} to {pts(mr.paired.hit5_repeat.graph_minus_vector.ci95[1])}).
            Graph minus keyword: {pts(mr.paired.hit5_repeat.graph_minus_keyword.point)} ({pts(mr.paired.hit5_repeat.graph_minus_keyword.ci95[0])} to {pts(mr.paired.hit5_repeat.graph_minus_keyword.ci95[1])}).
            The LLM memory arms were not run (no API key).
          </p>
        </section>
      )}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
        {strip.map((t) => (
          <div key={t.label} className="card" style={{ flex: "1 1 min(220px, 100%)", padding: "16px 18px" }}>
            <div className="mono" style={{ fontSize: 30, fontWeight: 600 }}>{t.value}</div>
            <div style={{ fontSize: 14, color: "var(--text-3)" }}>{t.label}</div>
            {t.note && <div className="mono" style={{ fontSize: 11, color: "var(--text-4)", marginTop: 4 }}>{t.note}</div>}
          </div>
        ))}
      </div>
      <section id="learning" className="card" style={{ padding: 18, scrollMarginTop: 80 }} aria-label="What learning adds">
        <h2 style={{ margin: 0, fontSize: 16 }}>What learning adds</h2>
        <p style={{ margin: "2px 0 12px", fontSize: 13, color: "var(--text-4)" }}>Shared incident difficulty cancels out in the paired difference.</p>
        <PairedGainChart r={r} />
      </section>
      <section className="card" style={{ padding: 18 }} aria-label="Accuracy as it learns">
        <h2 style={{ margin: 0, fontSize: 16 }}>Accuracy as it learns</h2>
        <p style={{ margin: "2px 0 12px", fontSize: 13, color: "var(--text-4)" }}>Top-1 accuracy over each company's incidents up to that number, learning from zero at every company.</p>
        <CumulativeChart r={r} />
      </section>
      <section className="card" style={{ padding: 18, overflowX: "auto" }}>
        <h2 style={{ margin: "0 0 10px", fontSize: 16 }}>Against baselines</h2>
        <table className="mono" style={{ width: "100%", minWidth: 640, fontSize: 13, borderCollapse: "collapse" }}>
          <thead><tr style={{ color: "var(--text-4)", textAlign: "left" }}>{["Method", "AC@1", "95% CI", "AC@3", "Checks to root", "p95 latency"].map((h) => <th key={h} style={{ padding: "6px 8px", fontWeight: 500, fontFamily: "Geist" }}>{h}</th>)}</tr></thead>
          <tbody>
            {order.map((k) => {
              const m = r.methods[k]; const o = ops[k]
              if (!m) return null
              const mine = k === "ghostwalk"
              return (
                <tr key={k} style={{ borderTop: "1px solid var(--line)", color: mine ? "var(--ink)" : "var(--text-2)", fontWeight: mine ? 600 : 400 }}>
                  <td style={{ padding: "9px 8px", fontFamily: "Geist" }}>{METHOD_LABEL[k]}</td>
                  <td style={{ padding: "9px 8px" }}>{f3(m.ac1.point)}</td><td style={{ padding: "9px 8px" }}>{ci(m.ac1)}</td><td style={{ padding: "9px 8px" }}>{f3(m.ac3.point)}</td>
                  <td style={{ padding: "9px 8px" }}>{o && typeof o === "object" ? o.mean_checks_to_root.toFixed(2) : "—"}</td>
                  <td style={{ padding: "9px 8px" }}>{o && typeof o === "object" ? `${ms(o.verdict_ms_p95)} ms` : "—"}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
        <p style={{ margin: "10px 0 0", fontSize: 12, color: "var(--text-4)" }}>
          PageRank is tuned on the dev split{r.baseline_fairness?.pagerank.grid_budget ? ` over ${r.baseline_fairness.pagerank.grid_budget} settings` : ""} and run once on test. Latency is {String(ops.backend ?? "in-memory")}.
          Reproduce: <span className="mono">$ make eval</span>
        </p>
      </section>
      {tiles.length > 0 && (
        <section className="card" style={{ padding: 18 }}>
          <h2 style={{ margin: 0, fontSize: 16 }}>Same incidents, same learner. Only the store changes.</h2>
          {kvB?.delta_vs_reference && vecB?.delta_vs_reference && (
            <p style={{ margin: "6px 0 0", fontSize: 15, fontWeight: 500 }}>
              Replace graph traversal and it fails: key-value (1 hop) {pts(kvB.delta_vs_reference.point)}, vector search {pts(vecB.delta_vs_reference.point)} (vs {refLabel}).
            </p>)}
          <p style={{ margin: "6px 0 0", fontSize: 13, color: "var(--text-3)" }}>
            A relational database with recursive queries matches accuracy{cteB?.delta_vs_reference ? ` (${pts(cteB.delta_vs_reference.point)})` : ""}, as expected: the gain comes from multi-hop graph walks, not from which product stores the graph.
            We use HydraDB for its native weighted path algorithms.
          </p>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 12, marginTop: 12 }}>
            {tiles.map((t) => (
              <div key={t.label} style={{ flex: "1 1 min(190px, 100%)", border: "1px solid var(--line)", borderRadius: 12, padding: "12px 14px" }}>
                <div style={{ fontSize: 13, color: "var(--text-3)" }}>{t.label}</div>
                <div className="mono" style={{ fontSize: 24, fontWeight: 600 }}>{t.v}</div>
                <div aria-hidden="true" style={{ height: 6, borderRadius: 3, background: "var(--muted)", margin: "6px 0" }}><div style={{ height: "100%", width: `${parseFloat(t.v) * 100}%`, borderRadius: 3, background: "var(--accent)" }} /></div>
                <div className="mono" style={{ fontSize: 11, color: "var(--text-4)" }}>{t.sub}</div>
              </div>
            ))}
            {!sw?.backends?.hydradb && (
              <div style={{ flex: "1 1 min(190px, 100%)", border: "1px dashed var(--line)", borderRadius: 12, padding: "12px 14px" }}>
                <div style={{ fontSize: 13, color: "var(--text-3)" }}>HydraDB paths</div>
                <div className="mono" style={{ fontSize: 14, marginTop: 6 }}>not run</div>
                <div style={{ fontSize: 11, color: "var(--text-4)" }}>{sw?.hydradb.status}</div>
              </div>)}
          </div>
          {depth && (
            <div style={{ marginTop: 18 }}>
              <div style={{ fontSize: 14, color: "var(--text-3)", marginBottom: 8 }}>Max hops walked</div>
              <div style={{ display: "flex", alignItems: "flex-end", gap: 14, height: 110 }}>
                {Object.entries(depth).map(([h, c]) => (
                  <div key={h} className="mono" style={{ flex: 1, maxWidth: 90, display: "flex", flexDirection: "column", alignItems: "center", gap: 4, fontSize: 12 }}>
                    <span style={{ color: "var(--text-3)" }}>{f3(c.point)}</span>
                    <span aria-hidden="true" style={{ width: "100%", height: `${Math.max(6, c.point * 80)}px`, background: h === "5" ? "var(--accent)" : "var(--text-4)", borderRadius: "6px 6px 2px 2px", opacity: h === "5" ? 1 : 0.55 }} />
                    <span style={{ color: "var(--text-4)" }}>{h}</span>
                  </div>))}
              </div>
            </div>
          )}
        </section>
      )}
      {warm && (
        <section className="card" style={{ padding: 18, overflowX: "auto" }}>
          <h2 id="latency" style={{ margin: 0, fontSize: 16, scrollMarginTop: 80 }}>HydraDB and Postgres, warm latency</h2>
          <p style={{ margin: "2px 0 10px", fontSize: 13, color: "var(--text-4)" }}>p50 / p95 ms, 200 timed requests after warm-up, one at a time. {warm.machine?.cpus} CPUs, {warm.machine?.ram_gb} GB, both databases in docker on the same machine.</p>
          <table className="mono" style={{ fontSize: 13, borderCollapse: "collapse", minWidth: 520 }}>
            <thead><tr style={{ color: "var(--text-4)", textAlign: "left" }}>{["", "HydraDB", "Postgres"].map((h) => <th key={h} style={{ padding: "6px 14px 6px 0", fontFamily: "Geist", fontWeight: 500 }}>{h}</th>)}</tr></thead>
            <tbody>
              {([["1-hop neighbours", "one_hop"], ["Best path, 3 hops", "path_3_hops"], ["Best path, 5 hops", "path_5_hops"], ["Edge-weight write", "edge_write"]] as [string, string][]).map(([label, k]) => (
                <tr key={k} style={{ borderTop: "1px solid var(--line)" }}><td style={{ padding: "8px 14px 8px 0", fontFamily: "Geist" }}>{label}</td>
                  <td style={{ paddingRight: 14 }}>{ms(warm.per_query[k].hydradb.p50)} / {ms(warm.per_query[k].hydradb.p95)}</td><td>{ms(warm.per_query[k].postgres.p50)} / {ms(warm.per_query[k].postgres.p95)}</td></tr>))}
              {([["Verdict, cache hit", "cached_hit"], ["Verdict, cache miss (every incident while learning)", "cached_miss"], ["Verdict, read the graph back", "cold"], ["Verdict, in-DB (two MSpaths)", "in_db"]] as [string, string][]).map(([label, k]) => (
                <tr key={k} style={{ borderTop: "1px solid var(--line)" }}><td style={{ padding: "8px 14px 8px 0", fontFamily: "Geist" }}>{label}</td><td style={{ paddingRight: 14 }}>{ms(warm.per_verdict[k].p50)} / {ms(warm.per_verdict[k].p95)}</td><td /></tr>))}
              <tr style={{ borderTop: "1px solid var(--line)" }}><td style={{ padding: "8px 14px 8px 0", fontFamily: "Geist" }}>Verdict, two batched CTEs</td><td /><td>{ms(warm.postgres_per_verdict.p50)} / {ms(warm.postgres_per_verdict.p95)}</td></tr>
            </tbody>
          </table>
          <p style={{ margin: "8px 0 0", fontSize: 13, color: "var(--text-3)" }}>
            Verdicts read from HydraDB through a revision-checked write-through cache; path computation runs in the engine. HydraDB in-DB path mode is slower at these sizes (measured), so it is not used.
            HydraDB writes cost about {ms(warm.per_query.edge_write.hydradb.p50)} ms each (server-side commit).
          </p>
          {loop && (
            <p style={{ margin: "6px 0 0", fontSize: 13, color: "var(--text-3)" }}>
              On the {r.meta.companies} held-out companies, learning on: verdict <b>{ms(loop.verdict_ms_p50)} ms p50 / {ms(loop.verdict_ms_p95)} ms p95</b>
              {loop.before_write_through_cache ? ` (was ${ms(loop.before_write_through_cache.verdict_ms_p50)} / ${ms(loop.before_write_through_cache.verdict_ms_p95)} ms before the write-through cache)` : ""}.
              The learning write, off the verdict path: {ms(loop.learning_write_ms_p50)} ms p50 / {ms(loop.learning_write_ms_p95)} ms p95.
            </p>)}
        </section>
      )}
      {scaleRows.length > 0 && (
        <section className="card" style={{ padding: 18, overflowX: "auto" }}>
          <h2 style={{ margin: 0, fontSize: 16 }}>Path queries at scale: HydraDB vs Postgres</h2>
          <p style={{ margin: "2px 0 10px", fontSize: 13, color: "var(--text-4)" }}>Weighted best path between random reachable pairs, both stores returning the exact same cost every time. Latency only, p50 / p95 in ms, one machine, loopback.</p>
          <table className="mono" style={{ fontSize: 13, borderCollapse: "collapse", minWidth: 640 }}>
            <thead><tr style={{ color: "var(--text-4)", textAlign: "left" }}>{["Services", "HydraDB, 3 hops", "Postgres, 3 hops", "HydraDB, 5 hops", "Postgres, 5 hops", "Whole verdict: HydraDB read / in-DB / Postgres"].map((h) => <th key={h} style={{ padding: "6px 14px 6px 0", fontFamily: "Geist", fontWeight: 500 }}>{h}</th>)}</tr></thead>
            <tbody>{scaleRows.map(([n, e]) => {
              const c = (h: string, k: "hydradb" | "postgres") => `${ms(e.path_query[h][k].p50)} / ${ms(e.path_query[h][k].p95)}`
              const pv = r.scale?.postgres_verdict?.sizes?.[n]
              return (<tr key={n} style={{ borderTop: "1px solid var(--line)" }}><td style={{ padding: "8px 14px 8px 0" }}>{(+n).toLocaleString()}</td>
                <td style={{ paddingRight: 14 }}>{c("hops_3", "hydradb")}</td><td style={{ paddingRight: 14 }}>{c("hops_3", "postgres")}</td><td style={{ paddingRight: 14 }}>{c("hops_5", "hydradb")}</td><td style={{ paddingRight: 14 }}>{c("hops_5", "postgres")}</td>
                <td>{ms(e.verdict.cold_read.p50)} / {ms(e.verdict.in_db.p50)} / {pv ? ms(pv.p50) : "n/a"} ms</td></tr>)
            })}</tbody>
          </table>
          <p style={{ margin: "8px 0 0", fontSize: 13, color: "var(--text-3)" }}>{pgFaster ? "Postgres is faster at every size and hop limit here; " : "Neither store is faster everywhere; "}HydraDB's value in this project is native path algorithms, not speed.{beforeFix ? ` Before a transport fix on this laptop HydraDB read about ${ms(beforeFix)} ms at every size (a client/proxy artefact, diagnosed in results.json).` : ""} See <a href="https://github.com/redcode333/GhostWalk/blob/main/docs/graph-vs-sql.md" style={{ textDecoration: "underline" }}>the queries side by side</a>.</p>
        </section>
      )}
      {r.repeat_vs_novel && (
        <section className="card" style={{ padding: 18, overflowX: "auto" }}>
          <h2 style={{ margin: 0, fontSize: 16 }}>New and repeat incidents</h2>
          <p style={{ margin: "2px 0 10px", fontSize: 13, color: "var(--text-4)" }}>{r.repeat_vs_novel.definition}</p>
          <table className="mono" style={{ fontSize: 13, borderCollapse: "collapse", minWidth: 420 }}>
            <thead><tr style={{ color: "var(--text-4)", textAlign: "left" }}><th style={{ padding: "6px 12px 6px 0", fontFamily: "Geist", fontWeight: 500 }}>AC@1</th><th style={{ fontFamily: "Geist", fontWeight: 500 }}>Repeat</th><th style={{ fontFamily: "Geist", fontWeight: 500 }}>Novel</th></tr></thead>
            <tbody>{Object.entries(r.repeat_vs_novel.methods).map(([k, v]) => (
              <tr key={k} style={{ borderTop: "1px solid var(--line)" }}><td style={{ padding: "8px 12px 8px 0" }}>{k === "tfidf" ? "TF-IDF retrieval" : METHOD_LABEL[k]}</td><td style={{ paddingRight: 16 }}>{f3(v.repeat.point)} <span style={{ color: "var(--text-4)" }}>{ci(v.repeat)}</span></td><td>{f3(v.novel.point)} <span style={{ color: "var(--text-4)" }}>{ci(v.novel)}</span></td></tr>
            ))}</tbody>
          </table>
        </section>
      )}
      {r.latency && (
        <section className="card" style={{ padding: 18, overflowX: "auto" }}>
          <h2 style={{ margin: 0, fontSize: 16 }}>Speed at scale</h2>
          <p style={{ margin: "2px 0 10px", fontSize: 13, color: "var(--text-4)" }}>
            Verdict latency on synthetic graphs with the same tier mix, {r.latency.incidents_per_size.toLocaleString()} incidents each, in-memory engine on {r.latency.meta.cpus} CPUs.
            {r.latency.gate.p95_1000_ms != null && r.latency.gate.stopped_at_1000 && <> At 1,000 services the p95 is <b>{ms(r.latency.gate.p95_1000_ms)} ms</b>, under the 100 ms target, so the engine stays in Python.</>}
            {r.latency.gate.p95_5000_ms != null && <> At 5,000 services it is {ms(r.latency.gate.p95_5000_ms)} ms{r.latency.gate.rust_port === "not needed" ? ", under the 250 ms line that would justify a Rust port." : "."}</>}
          </p>
          <table className="mono" style={{ fontSize: 13, borderCollapse: "collapse", minWidth: 480 }}>
            <thead><tr style={{ color: "var(--text-4)", textAlign: "left" }}>{["Services", "p50", "p95", "p99", "HydraDB"].map((h) => <th key={h} style={{ padding: "6px 14px 6px 0", fontFamily: "Geist", fontWeight: 500 }}>{h}</th>)}</tr></thead>
            <tbody>{Object.entries(r.latency.sizes).sort((a, b) => +a[0] - +b[0]).map(([n, v]) => (
              <tr key={n} style={{ borderTop: "1px solid var(--line)" }}><td style={{ padding: "8px 14px 8px 0" }}>{(+n).toLocaleString()}</td><td style={{ paddingRight: 14 }}>{ms(v.in_memory_ms.p50)} ms</td>
                <td style={{ paddingRight: 14 }}>{ms(v.in_memory_ms.p95)} ms</td><td style={{ paddingRight: 14 }}>{ms(v.in_memory_ms.p99)} ms</td><td style={{ color: "var(--text-4)", fontFamily: "Geist" }}>not measured</td></tr>))}</tbody>
          </table>
          <p style={{ margin: "8px 0 0", fontSize: 12, color: "var(--text-4)" }}>HydraDB: {r.latency.hydradb.status}. Reproduce: <span className="mono">$ make bench</span></p>
        </section>
      )}
      {r.change_evidence && r.change_evidence.main.gain.ci95[0] > 0 && (
        <section className="card" style={{ padding: 18, overflowX: "auto" }}>
          <h2 style={{ margin: 0, fontSize: 16 }}>What changed recently <span className="mono" style={{ fontSize: 11, color: "var(--text-4)" }}>--use-changes</span></h2>
          <p style={{ margin: "2px 0 10px", fontSize: 13, color: "var(--text-4)" }}>
            AC@1 {f3(r.change_evidence.main.without.point)} → {f3(r.change_evidence.main.with.point)} ({pts(r.change_evidence.main.gain.point)}, 95% CI {pts(r.change_evidence.main.gain.ci95[0])} to {pts(r.change_evidence.main.gain.ci95[1])}). {r.change_evidence.helps_only_when}
          </p>
          <table className="mono" style={{ fontSize: 13, borderCollapse: "collapse", minWidth: 460 }}>
            <thead><tr style={{ color: "var(--text-4)", textAlign: "left" }}><th style={{ padding: "6px 12px 6px 0", fontFamily: "Geist", fontWeight: 500 }}>root has a change / distractors per incident</th>{[0.5, 2, 5].map((x) => <th key={x} style={{ fontFamily: "Geist", fontWeight: 500, paddingRight: 16 }}>{x}</th>)}</tr></thead>
            <tbody>{[0.2, 0.5, 0.8].map((p) => (
              <tr key={p} style={{ borderTop: "1px solid var(--line)" }}><td style={{ padding: "8px 12px 8px 0" }}>{Math.round(p * 100)}%</td>
                {[0.5, 2, 5].map((n) => { const c = r.change_evidence!.sensitivity.find((x) => x.p_root === p && x.r_noise === n); return <td key={n} style={{ paddingRight: 16, color: c && c.gain.ci95[0] > 0 ? "var(--ink)" : "var(--text-4)" }}>{c ? pts(c.gain.point) : "—"}</td> })}</tr>))}</tbody>
          </table>
          <p style={{ margin: "8px 0 0", fontSize: 12, color: "var(--text-4)" }}>Gain in AC@1 over the same engine without change events. Grey = 95% CI includes 0.</p>
        </section>
      )}
      {r.poisoning && (
        <section className="card" style={{ padding: 18 }}>
          <h2 style={{ margin: 0, fontSize: 16 }}>When postmortems are wrong</h2>
          <p style={{ margin: "2px 0 10px", fontSize: 13, color: "var(--text-4)" }}>Share of postmortems naming the wrong root: GhostWalk vs learning off, same incidents.</p>
          <div className="mono" style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
            {Object.values(r.poisoning.levels).map((l) => (
              <div key={l.wrong_pm} style={{ flex: "1 1 min(180px, 100%)", border: "1px solid var(--line)", borderRadius: 12, padding: "10px 14px", fontSize: 13 }}>
                <div style={{ color: "var(--text-4)" }}>{pct(l.wrong_pm)} wrong</div>
                <div>{f3(l.ghostwalk.point)} vs {f3(l.learning_off.point)}</div>
                <div style={{ color: "var(--text-4)" }}>{pts(l.gain.point)}</div>
              </div>
            ))}
          </div>
        </section>
      )}
      <div className="mono" style={{ fontSize: 12, color: "var(--text-4)" }}>
        run {r.meta.timestamp_utc.slice(0, 10)} · commit {r.meta.git.short}{r.meta.git.dirty ? " (dirty)" : ""}
      </div>
    </Page>
  )
}
