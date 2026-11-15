import { useMemo, useState } from "react"
import { api } from "@/lib/api"
import { Btn, Err, Muted, useLoad } from "@/components/common"
import { Graph, Legend } from "@/components/Graph"
import { H1, Page } from "@/components/AppShell"

const CAP = 40

export default function MapPage() {
  const { data: m, error } = useLoad(() => api("/api/map"), [])
  const [mode, setMode] = useState<"official" | "both">("both")
  const view = useMemo(() => {
    if (!m) return null
    const edges = m.edges.filter((e: any) => mode === "both" || e.origin === "official")
    // Show where the interesting edges are: endpoints of learned edges and their neighbours, else the best-connected services.
    const seed = new Set<number>(m.learned.flatMap((e: any) => [e.u, e.v]))
    const deg = new Map<number, number>()
    edges.forEach((e: any) => { deg.set(e.u, (deg.get(e.u) ?? 0) + 1); deg.set(e.v, (deg.get(e.v) ?? 0) + 1) })
    const keep = new Set<number>(mode === "both" ? seed : [])
    for (const [id] of [...deg].sort((a, b) => b[1] - a[1])) { if (keep.size >= CAP) break; keep.add(id) }
    const nodes = m.nodes.filter((n: any) => keep.has(n.id))
    return { nodes, edges: edges.filter((e: any) => keep.has(e.u) && keep.has(e.v)) }
  }, [m, mode])
  if (error) return <Page><Err>{error}</Err></Page>
  if (!m || !view) return <Page><Muted>Loading…</Muted></Page>
  const name = (id: number) => m.nodes.find((n: any) => n.id === id)?.name
  return (
    <Page>
      <H1 title="Dependency map" sub={`${m.nodes.length} services · ${m.official} official edges · ${m.learned.length} learned`}
        right={<div style={{ display: "flex", gap: 8 }}>
          <a className="btn btn-glass" href="/api/map/export" download="ghostwalk-graph.json">Export graph</a>
          <Btn to="/app/learn">Review queue</Btn></div>} />
      <div style={{ display: "flex", flexWrap: "wrap", gap: 16, alignItems: "flex-start" }}>
        <section className="card" style={{ flex: "3 1 560px", minWidth: 0, padding: 18, display: "flex", flexDirection: "column", gap: 12 }}>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
            <div role="tablist" aria-label="Edges" style={{ display: "flex", gap: 4 }}>
              <button role="tab" aria-selected={mode === "official"} className={`chip${mode === "official" ? " on" : ""}`} onClick={() => setMode("official")}>Official</button>
              <button role="tab" aria-selected={mode === "both"} className={`chip${mode === "both" ? " on" : ""}`} onClick={() => setMode("both")}>Official + learned</button>
            </div>
            <span className="mono" style={{ marginLeft: "auto", fontSize: 12, color: "var(--text-4)" }}>Showing {view.nodes.length} of {m.nodes.length}</span>
          </div>
          <Graph nodes={view.nodes} edges={view.edges} height={420} />
          <Legend items={["Edge", "Service", "Data", "Infra", "Learned edge"]} />
        </section>
        <aside className="card" style={{ flex: "1 1 300px", padding: 18 }}>
          <h2 style={{ margin: "0 0 8px", fontSize: 16 }}>Learned edges</h2>
          {m.learned.length === 0 && <Muted>None yet. Write a postmortem and the first one lands here.</Muted>}
          {m.learned.map((e: any, i: number) => (
            <div key={i} style={{ padding: "10px 0", borderTop: i ? "1px solid var(--line)" : undefined }}>
              <div className="mono" style={{ fontSize: 13, display: "flex", gap: 8 }}>
                <span style={{ color: "var(--accent-text)" }}>{name(e.u)} ⇢ {name(e.v)}</span>
                <span style={{ marginLeft: "auto", color: e.confirmations >= 2 ? "var(--ok)" : "var(--text-4)" }}>{e.confirmations >= 2 ? "confirmed" : "tentative"}</span>
              </div>
              <div className="mono" style={{ fontSize: 12, color: "var(--text-4)" }}>w {e.w.toFixed(2)} · revision {e.from}</div>
            </div>
          ))}
        </aside>
      </div>
    </Page>
  )
}
