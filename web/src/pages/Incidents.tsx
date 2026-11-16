import { useState } from "react"
import { Link } from "react-router-dom"
import { api, ago } from "@/lib/api"
import { Err, Muted, useLoad } from "@/components/common"
import { ReplayButtons } from "@/components/Replay"
import { H1, Page } from "@/components/AppShell"

export const Stat = ({ label, value, sub }: { label: string; value: string; sub?: string }) => (
  <div className="card" style={{ padding: "16px 18px", flex: "1 1 min(180px, 100%)" }}>
    <div style={{ fontSize: 13, color: "var(--text-4)" }}>{label}</div>
    <div className="mono" style={{ fontSize: 28, fontWeight: 600, marginTop: 2 }}>{value}</div>
    {sub && <div style={{ fontSize: 12, color: "var(--text-4)", marginTop: 2 }}>{sub}</div>}
  </div>
)

export const statusColor = (s: string) => (s === "Open" ? "var(--amber)" : s === "Needs postmortem" ? "var(--accent-text)" : "var(--text-3)")
const COLS = "110px minmax(220px,2fr) minmax(220px,1.3fr) 90px 150px 90px"

export default function Incidents() {
  const [tab, setTab] = useState("All")
  const { data: rows, error } = useLoad(() => api<any[]>("/api/incidents"), [])
  const { data: s } = useLoad(() => api("/api/summary"), [])
  const shown = (rows ?? []).filter((r) => tab === "All" || r.status === tab)
  return (
    <Page>
      <H1 title="Incidents" sub="Every outage GhostWalk has walked, newest first." />
      <div role="tablist" aria-label="Filter" style={{ display: "flex", gap: 4 }}>
        {["All", "Open", "Needs postmortem"].map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)} className={`chip${tab === t ? " on" : ""}`}>{t}</button>
        ))}
      </div>
      <ReplayButtons />
      <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
        <Stat label="Open now" value={s ? String(s.open) : "…"} />
        <Stat label="Top-1 correct, last 30" value={s?.top1_last_30 == null ? "—" : `${Math.round(s.top1_last_30 * 100)}%`} sub={s ? `${s.scored} scored` : undefined} />
        <Stat label="Median time to verdict" value={s?.median_ms == null ? "—" : `${s.median_ms.toFixed(1)} ms`} />
        <Stat label="Learned edges" value={s ? String(s.learned_edges) : "…"} />
      </div>
      {error && <Err>{error}</Err>}
      <div className="card" style={{ overflowX: "auto" }}>
        <div style={{ minWidth: 820 }}>
          <div style={{ display: "grid", gridTemplateColumns: COLS, gap: 16, padding: "10px 16px", fontSize: 12, color: "var(--text-4)" }}>
            <span>Incident</span><span>Symptom</span><span>Root cause</span><span>Confidence</span><span>Status</span><span>Started</span>
          </div>
          {shown.map((r) => (
            <Link key={r.id} to={`/app/incidents/${r.id}`} className="mono"
              style={{ display: "grid", gridTemplateColumns: COLS, gap: 16, alignItems: "center", padding: "12px 16px", borderTop: "1px solid var(--line)", fontSize: 14 }}>
              <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}><span aria-hidden="true" className={r.status === "Open" ? "live" : ""} style={{ width: 7, height: 7, borderRadius: 99, background: r.status === "Open" ? "var(--amber)" : r.status === "Needs postmortem" ? "var(--accent)" : "var(--text-4)", opacity: r.status === "Resolved" ? 0.5 : 1 }} />{r.id}</span>
              <span style={{ fontFamily: "Geist, sans-serif" }}>{r.symptom}</span>
              <span style={{ color: "var(--accent-text)", whiteSpace: "nowrap" }}>{r.root}{r.taught ? <Muted> · taught {r.taught} change{r.taught === 1 ? "" : "s"}</Muted> : null}</span>
              <span>{r.confidence.toFixed(2)}</span>
              <span style={{ color: statusColor(r.status), fontFamily: "Geist, sans-serif" }}>{r.status}</span>
              <span style={{ color: "var(--text-4)" }}>{ago(r.started)}</span>
            </Link>
          ))}
          {rows && !shown.length && <div style={{ padding: 20, color: "var(--text-4)", fontSize: 14 }}>Nothing here. Send an alert, or use “Trigger outage”.</div>}
        </div>
      </div>
    </Page>
  )
}
