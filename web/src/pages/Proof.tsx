import { loadResults, METHOD_LABEL, ms, pct, proofStrip, pts, type CI, type Results } from "@/lib/results"
import { Err, Muted, useLoad } from "@/components/common"
import { H1, Page } from "@/components/AppShell"

const f3 = (x: number) => x.toFixed(3)
const ci = (c: CI) => `${f3(c.ci95[0])}–${f3(c.ci95[1])}`

function CurveChart({ r }: { r: Results }) {
  const lc = r.learning_curve
  if (!lc) return <Muted>No learning-curve series in results.json.</Muted>
  const W = 720, H = 260, L = 44, B = 28, T = 10
  const series: [string, string, string?][] = [["ghostwalk", "var(--accent)"], ["learning_off", "var(--text-3)"], ["placebo", "var(--amber)", "4 3"], ["oracle", "var(--ink)", "2 3"]]
  const all = series.flatMap(([k]) => lc.series[k] ?? [])
  const lo = Math.floor(Math.min(...all.map((p) => p.ci95[0])) * 10) / 10, hi = Math.min(1, Math.ceil(Math.max(...all.map((p) => p.ci95[1])) * 10) / 10)
  const n = (lc.series.ghostwalk ?? []).length
  const x = (i: number) => L + (i * (W - L - 12)) / Math.max(1, n - 1)
  const y = (v: number) => T + ((hi - v) * (H - T - B)) / (hi - lo)
  const line = (k: string) => (lc.series[k] ?? []).map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.ac1).toFixed(1)}`).join(" ")
  const band = (lc.series.ghostwalk ?? [])
  const bandPath = band.length ? `${band.map((p, i) => `${i ? "L" : "M"}${x(i)},${y(p.ci95[1])}`).join(" ")} ${[...band].reverse().map((p, i) => `L${x(band.length - 1 - i)},${y(p.ci95[0])}`).join(" ")} Z` : ""
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="Top-1 accuracy by incident number">
        {Array.from({ length: Math.round((hi - lo) / 0.1) + 1 }, (_, i) => lo + i * 0.1).map((v) => (
          <g key={v}><line x1={L} x2={W - 12} y1={y(v)} y2={y(v)} stroke="var(--line)" /><text x={L - 8} y={y(v) + 4} textAnchor="end" fontSize="11" fill="var(--text-4)" fontFamily="Geist Mono">{v.toFixed(1)}</text></g>
        ))}
        {band.map((p, i) => (i % 2 === 0 ? <text key={i} x={x(i)} y={H - 8} textAnchor="middle" fontSize="11" fill="var(--text-4)" fontFamily="Geist Mono">{p.from}</text> : null))}
        <path d={bandPath} fill="var(--accent)" opacity="0.14" />
        {series.map(([k, c, d]) => <path key={k} d={line(k)} fill="none" stroke={c} strokeWidth={k === "ghostwalk" ? 2.4 : 1.6} strokeDasharray={d} />)}
      </svg>
      <div className="mono" style={{ display: "flex", flexWrap: "wrap", gap: 16, fontSize: 12, color: "var(--text-3)" }}>
        {[["GhostWalk, 95% band", "var(--accent)"], ["Learning off", "var(--text-3)"], ["Placebo postmortems", "var(--amber)"], ["Perfect map", "var(--ink)"]].map(([l, c]) => (
          <span key={l} style={{ display: "inline-flex", alignItems: "center", gap: 6 }}><span style={{ width: 14, height: 2, background: c }} />{l}</span>
        ))}
        <span style={{ marginLeft: "auto" }}>incident number, bins of {lc.bin}</span>
      </div>
    </div>
  )
}

export default function Proof() {
  const { data: r, error } = useLoad(loadResults, [])
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
  return (
    <Page>
      <H1 title="Proof" sub={`Held-out ${r.meta.split} split: ${r.meta.companies} companies, ${r.meta.incidents.toLocaleString()} incidents. 95% bootstrap intervals.`}
        right={<a className="btn btn-glass" href="/results.json" download>Download results.json</a>} />
      <p style={{ margin: 0, padding: "14px 18px", border: "1px solid var(--accent)", borderRadius: 14, fontSize: 17, fontWeight: 500, background: "rgba(var(--lrgb), .03)" }}>
        Evaluated on {r.meta.companies} held-out companies never used for development or tuning; learning starts from zero at each company.
      </p>
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
      <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
        {strip.map((t) => (
          <div key={t.label} className="card" style={{ flex: "1 1 min(220px, 100%)", padding: "16px 18px" }}>
            <div className="mono" style={{ fontSize: 30, fontWeight: 600 }}>{t.value}</div>
            <div style={{ fontSize: 14, color: "var(--text-3)" }}>{t.label}</div>
            {t.note && <div className="mono" style={{ fontSize: 11, color: "var(--text-4)", marginTop: 4 }}>{t.note}</div>}
          </div>
        ))}
      </div>
      <section className="card" style={{ padding: 18 }}>
        <h2 style={{ margin: 0, fontSize: 16 }}>Learning curve</h2>
        <p style={{ margin: "2px 0 10px", fontSize: 13, color: "var(--text-4)" }}>top-1 accuracy by incident number</p>
        <CurveChart r={r} />
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
          <p style={{ margin: "8px 0 0", fontSize: 13, color: "var(--text-3)" }}>Postgres keeps up here and is faster at every size; HydraDB's value in this project is native path algorithms, not speed. See <a href="https://github.com/redcode333/GhostWalk/blob/main/docs/graph-vs-sql.md" style={{ textDecoration: "underline" }}>the queries side by side</a>.</p>
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
