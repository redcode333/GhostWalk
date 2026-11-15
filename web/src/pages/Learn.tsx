import { useEffect, useState } from "react"
import { Navigate, useNavigate, useParams } from "react-router-dom"
import { api } from "@/lib/api"
import { Btn, Err, Muted, useLoad } from "@/components/common"
import { H1, Page } from "@/components/AppShell"
import { ChangeRows } from "@/components/panels"

const field = { padding: "10px 12px", borderRadius: 8, border: "1px solid var(--line)", background: "var(--surface-2)", color: "var(--ink)", font: "14px Geist, sans-serif" } as const

function Changes({ shown, rejected, toggle }: { shown: any[]; rejected: Set<number>; toggle: (i: number) => void }) {
  return <ChangeRows rows={shown} dimmed={rejected} action={(r) => <button className="chip" onClick={() => toggle(r.index)} style={{ padding: "3px 10px", fontSize: 12 }}>{rejected.has(r.index) ? "Keep" : "Reject"}</button>} />
}

export default function Learn() {
  const { id } = useParams()
  const nav = useNavigate()
  const { data: list } = useLoad(() => api<any[]>("/api/incidents"), [])
  const queue = useLoad(() => api<any[]>("/api/learn/queue"), [])
  const inc = useLoad(() => (id ? api(`/api/incidents/${id}`) : Promise.resolve(null)), [id])
  const [f, setF] = useState({ root: "", path: "", missed: "" })
  const [pv, setPv] = useState<any>(null)
  const [rej, setRej] = useState<Set<number>>(new Set())
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState<string | null>(null)

  useEffect(() => {
    const v = inc.data?.verdict
    if (v) setF({ root: v.root_name ?? "", path: v.path.length ? [v.path[0].u_name, ...v.path.map((p: any) => p.v_name)].join(" -> ") : "", missed: "" })
    setPv(null); setDone(null)
  }, [inc.data?.id])

  if (!id) {
    if (!list) return <Page><Muted>Loading…</Muted></Page>
    const target = list.find((r) => r.status !== "Resolved") ?? list[0]
    return target ? <Navigate to={`/app/learn/${target.id}`} replace /> : <Page><H1 title="Learn" /><Muted>No incidents yet. Send an alert first.</Muted></Page>
  }

  const preview = async () => {
    setErr(null); setBusy(true); setRej(new Set())
    try { setPv(await api(`/api/learn/${id}/preview`, { method: "POST", json: f })) } catch (e: any) { setErr(e.message); setPv(null) } finally { setBusy(false) }
  }
  const apply = async () => {
    setBusy(true); setErr(null)
    try {
      const q = await api(`/api/learn/${id}/queue`, { method: "POST", json: f })
      const r = await api(`/api/learn/pending/${q.id}/apply`, { method: "POST", json: { reject: [...rej] } })
      setDone(`Graph updated · revision ${r.revision}`); setPv(null)
    } catch (e: any) { setErr(e.message) } finally { setBusy(false) }
  }
  const toggle = (set: Set<number>, i: number) => { const n = new Set(set); n.has(i) ? n.delete(i) : n.add(i); return n }

  return (
    <Page max={980}>
      <H1 title={`Learn from ${id}`} sub="Three fields. GhostWalk turns them into graph changes you review before they apply." />
      {queue.data && queue.data.length > 0 && (
        <section className="card" style={{ padding: 18 }} aria-label="Review queue">
          <h2 style={{ margin: "0 0 4px", fontSize: 16 }}>Waiting for review</h2>
          <p style={{ margin: "0 0 8px", fontSize: 14, color: "var(--text-3)" }}>Proposed from postmortems elsewhere (GitHub issues). Nothing applies until you do.</p>
          {queue.data.map((q) => <QueueItem key={q.id} q={q} onDone={() => { queue.reload(); inc.reload(); setDone("Graph updated") }} />)}
        </section>
      )}
      <div className="card" style={{ padding: 20, display: "flex", flexDirection: "column", gap: 14 }}>
        <div style={{ display: "flex", gap: 6 }}>
          <button className="chip on">Write postmortem</button>
          <button className="chip" disabled title="Not built yet" style={{ opacity: 0.5, cursor: "default" }}>Import old postmortems <span className="mono" style={{ fontSize: 11 }}>beta</span></button>
        </div>
        <label style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 14 }}>Actual root cause
          <input className="mono" style={field} value={f.root} onChange={(e) => setF({ ...f, root: e.target.value })} placeholder="config-svc" /></label>
        <label style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 14 }}>How it reached the alerting service
          <input className="mono" style={field} value={f.path} onChange={(e) => setF({ ...f, path: e.target.value })} placeholder="config-svc -> fraud-check -> checkout-api" />
          <span style={{ fontSize: 12, color: "var(--text-4)" }}>Service names or aliases. Unknown names are matched for you.</span></label>
        <label style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 14 }}>What the map got wrong (optional)
          <textarea rows={3} style={{ ...field, resize: "vertical" }} value={f.missed} onChange={(e) => setF({ ...f, missed: e.target.value })}
            placeholder={'fraud-check reads feature flags from config-svc on every request. "cfg" is config-svc.'} /></label>
        <div style={{ display: "flex", gap: 8 }}>
          <Btn onClick={preview} disabled={busy || !f.root}>Preview changes</Btn>
          <Btn variant="glass" onClick={() => nav(`/app/incidents/${id}`)}>Cancel</Btn>
        </div>
        {err && <Err>{err}</Err>}
      </div>
      {done && <div role="status" className="mono" style={{ color: "var(--ok)", fontSize: 14 }}>✓ {done}</div>}
      {pv && (
        <section className="card" style={{ padding: 20 }} aria-label="Proposed graph changes">
          <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
            <h2 style={{ margin: 0, fontSize: 17 }}>Proposed graph changes</h2><span className="mono" style={{ color: "var(--text-4)", fontSize: 13 }}>{pv.shown.length} changes</span>
          </div>
          {pv.unresolved.length > 0 && <p style={{ color: "var(--amber)", fontSize: 13 }}>Not in the map, ignored: {pv.unresolved.join(", ")}</p>}
          {pv.shown.length ? <Changes shown={pv.shown} rejected={rej} toggle={(i) => setRej(toggle(rej, i))} /> : <Muted>The map already explains this incident. Applying still records the confirmed root.</Muted>}
          <p style={{ fontSize: 13, color: "var(--text-4)" }}>New edges start tentative. One more matching incident makes them count in full.</p>
          <Btn onClick={apply} disabled={busy}>Apply {pv.shown.length - rej.size} changes</Btn>
        </section>
      )}
      <section className="card" style={{ padding: 18 }}>
        <h2 style={{ margin: "0 0 4px", fontSize: 16 }}>Import old postmortems <span className="mono" style={{ fontSize: 11, color: "var(--text-4)" }}>beta, not built yet</span></h2>
        <p style={{ margin: 0, fontSize: 14, color: "var(--text-3)" }}>Drop in Markdown or Confluence exports. A language model fills in the same three fields for each one, and every proposed edge lands in this review queue. It never writes to the graph on its own.</p>
      </section>
    </Page>
  )
}

function QueueItem({ q, onDone }: { q: any; onDone: () => void }) {
  const [rej, setRej] = useState<Set<number>>(new Set())
  const [busy, setBusy] = useState(false)
  return (
    <div style={{ borderTop: "1px solid var(--line)", paddingTop: 10 }}>
      <div className="mono" style={{ fontSize: 13, color: "var(--text-3)" }}>{q.source}{q.incident ? ` → ${q.incident}` : ""} · root {q.root_name}</div>
      {q.unresolved.length > 0 && <div style={{ color: "var(--amber)", fontSize: 13 }}>Not in the map: {q.unresolved.join(", ")}</div>}
      <Changes shown={q.shown} rejected={rej} toggle={(i) => setRej((s) => { const n = new Set(s); n.has(i) ? n.delete(i) : n.add(i); return n })} />
      <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
        <Btn disabled={busy} onClick={async () => { setBusy(true); await api(`/api/learn/pending/${q.id}/apply`, { method: "POST", json: { reject: [...rej] } }); onDone() }}>Apply {q.shown.length - rej.size} changes</Btn>
        <Btn variant="glass" onClick={async () => { await api(`/api/learn/pending/${q.id}`, { method: "DELETE" }); onDone() }}>Discard</Btn>
      </div>
    </div>
  )
}
