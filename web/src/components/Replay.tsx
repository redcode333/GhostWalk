import { useState } from "react"
import { api } from "@/lib/api"
import { Btn, Err, Muted, useLoad } from "@/components/common"
import { ms } from "@/lib/results"

type Stage = { stage: string; ranking: { name: string; confidence: number }[]; top1: string; confidence: number; top1_is_root: boolean; root_rank: number | null; abstains: boolean; path: { from: string; to: string; origin: string }[]; ms: number }

export function ReplayResult({ r }: { r: any }) {
  const rank = (x: number | null) => (x == null ? "not in the ranking" : x === 1 ? "first" : `rank ${x}`)
  return (
    <div className="card" role="region" aria-label={`Replay: ${r.title}`} style={{ padding: 20, display: "flex", flexDirection: "column", gap: 12 }}>
      <div>
        <h2 style={{ margin: 0, fontSize: 18 }}>{r.title}</h2>
        <div style={{ fontSize: 13, color: "var(--text-4)", marginTop: 2 }}>{r.label} Source: <a href={r.source.url} target="_blank" rel="noreferrer" style={{ color: "var(--accent-text)" }}>{r.source.title}</a></div>
      </div>
      <ul style={{ margin: 0, paddingLeft: 18, fontSize: 14, color: "var(--text-3)", display: "flex", flexDirection: "column", gap: 4 }}>{r.what_happened.map((x: string) => <li key={x}>{x}</li>)}</ul>
      <div style={{ fontSize: 14 }}>Alerts, in the order the postmortem describes: <span className="mono">{r.alerts.join(" → ")}</span>. The actual root was <strong className="mono">{r.root}</strong>, reached through <span className="mono">{r.hidden_edge[0]} → {r.hidden_edge[1]}</span>, which the official map does not list.</div>
      <div style={{ display: "grid", gap: 8 }}>
        {(r.stages as Stage[]).map((s, i) => (
          <div key={s.stage} className="card" style={{ padding: "12px 14px", borderColor: s.top1_is_root ? "var(--ok)" : undefined }}>
            <div style={{ fontSize: 13, color: "var(--text-4)" }}>{i + 1}. {s.stage}</div>
            <div className="mono" style={{ fontSize: 15, marginTop: 2 }}>top-1 {s.top1} · confidence {s.confidence.toFixed(2)}{s.abstains ? " (low: would ask for a second look)" : ""} · the real root is {rank(s.root_rank)} · {ms(s.ms)} ms</div>
            <div className="mono" style={{ fontSize: 12.5, color: "var(--text-3)", marginTop: 4 }}>{s.ranking.slice(0, 4).map((x) => `${x.name} ${x.confidence.toFixed(2)}`).join("  ·  ")}</div>
            {s.path.length > 0 && <div className="mono" style={{ fontSize: 12.5, color: "var(--text-4)", marginTop: 2 }}>path {[s.path[0].from, ...s.path.map((p) => p.to)].join(" → ")}</div>}
          </div>))}
      </div>
      <div style={{ fontSize: 14, color: "var(--text-3)" }}>
        Deepest-alert baseline: <span className="mono">{r.deepest_alert.top1}</span> (the real root is {rank(r.deepest_alert.root_rank)}).
        {r.llm ? <> LLM ({r.llm.provider}, <span className="mono">{r.llm.model}</span>): <span className="mono">{r.llm.top1}</span> (the real root is {rank(r.llm.root_rank)}).</> : " LLM answer not recorded."}
      </div>
      <Muted>Illustrative, not an accuracy measurement: one scenario each, built by us from the public description. GhostWalk is not claimed to have prevented either outage.</Muted>
    </div>
  )
}

export function ReplayButtons() {
  const { data: list } = useLoad(() => api<{ id: string; short: string }[]>("/api/replays"), [])
  const [open, setOpen] = useState<any>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const run = async (id: string) => { setBusy(id); setErr(null); try { setOpen(await api(`/api/replays/${id}`)) } catch (e: any) { setErr(e.message) } finally { setBusy(null) } }
  if (!list?.length) return null
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
        {list.map((x) => <Btn key={x.id} variant="glass" onClick={() => run(x.id)} disabled={busy !== null}>{busy === x.id ? "Replaying…" : `Replay ${x.short}`}</Btn>)}
        <Muted>real outages rebuilt from public postmortems; illustrative</Muted>
      </div>
      {err && <Err>{err}</Err>}
      {open && <ReplayResult r={open} />}
    </div>
  )
}
