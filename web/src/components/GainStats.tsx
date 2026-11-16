import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { GAIN_TIP, gainStats, loadResults, type Results } from "@/lib/results"

/** The gain stats, big and bold, each linking to its row on the Proof page. Reads results.json; renders nothing if it is missing. */
export function GainStats({ r, compact = false, base = "/proof" }: { r?: Results | null; compact?: boolean; base?: string }) {
  const [own, setOwn] = useState<Results | null>(null)
  useEffect(() => { if (r === undefined) loadResults().then(setOwn) }, [r])
  const stats = gainStats(r === undefined ? own : r)
  if (!stats.length) return null
  return (
    <div role="list" aria-label="Gains, in percentage points of top-1 accuracy" style={{ display: "flex", flexWrap: "wrap", justifyContent: "center", gap: compact ? "6px 20px" : 14 }}>
      {stats.map((s) => (
        <div key={s.key} role="listitem" style={{ display: "flex", flex: compact ? "0 1 auto" : "1 1 min(170px, 100%)" }}>
        <Link to={`${base}${s.href}`} title={GAIN_TIP} aria-label={`${s.value} ${s.label}. ${GAIN_TIP}`}
          style={{ textDecoration: "none", color: "inherit", textAlign: "center", padding: compact ? "0 4px" : "14px 18px", flex: 1, border: compact ? "none" : "1px solid var(--line)", borderRadius: 14, background: compact ? "transparent" : "var(--surface)" }}>
          <div className="mono" style={{ fontSize: compact ? "clamp(18px, 1.9vw, 25px)" : 28, fontWeight: 700, letterSpacing: "-0.02em", color: "var(--ink)", lineHeight: 1.1 }}>{s.value}</div>
          <div style={{ fontSize: compact ? 12.5 : 14, fontWeight: 600, color: "var(--text-2)", marginTop: 1 }}>{s.label}</div>
          {s.sub && <div style={{ fontSize: compact ? 11.5 : 12, color: "var(--text-4)", lineHeight: 1.25 }}>{s.sub}</div>}
        </Link></div>))}
    </div>
  )
}
