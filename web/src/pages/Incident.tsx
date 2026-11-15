import { useMemo, useState } from "react"
import { Link, useParams } from "react-router-dom"
import { api } from "@/lib/api"
import { Btn, Err, Muted, useLoad } from "@/components/common"
import { Graph, Legend, type GEdge, type GNode } from "@/components/Graph"
import { H1, Page } from "@/components/AppShell"
import { Stat } from "./Incidents"
import { RankList } from "@/components/panels"

export default function Incident() {
  const { id = "" } = useParams()
  const { data: inc, error } = useLoad(() => api(`/api/incidents/${id}`), [id])
  const { data: map } = useLoad(() => api("/api/map"), [])
  const [copied, setCopied] = useState(false)
  const v = inc?.verdict

  const { nodes, edges } = useMemo(() => {
    if (!v || !map) return { nodes: [] as GNode[], edges: [] as GEdge[] }
    const tier = new Map<number, number>(map.nodes.map((n: any) => [n.id, n.tier]))
    const ns: GNode[] = v.blast.map((b: any) => ({ id: b.id, name: b.name, kind: b.kind, tier: tier.get(b.id) ?? 1, alerting: b.alerting, root: b.root }))
    const ids = new Set(ns.map((n) => n.id))
    const onPath = new Set(v.path.map((p: any) => `${p.u}>${p.v}`))
    const es: GEdge[] = map.edges.filter((e: any) => ids.has(e.u) && ids.has(e.v)).map((e: any) => ({ u: e.u, v: e.v, origin: e.origin, path: onPath.has(`${e.u}>${e.v}`) }))
    return { nodes: ns, edges: es }
  }, [v, map])

  if (error) return <Page><Err>{error}</Err></Page>
  if (!inc) return <Page><Muted>Loading…</Muted></Page>

  const summary = `${inc.id} ${inc.symptom}: root cause ${v.root_name} (${v.confidence.toFixed(2)}), ${v.explains} of ${v.of} alerts explained, verdict in ${v.ms} ms.`
  const onsets = v.blast.filter((b: any) => b.alerting && b.onset != null).sort((a: any, b: any) => a.onset - b.onset)
  const span = Math.max(1, ...onsets.map((b: any) => b.onset))
  const pathIds = v.path.length ? [v.path[0].u, ...v.path.map((p: any) => p.v)] : []
  const inOrder = onsets.filter((o: any) => pathIds.includes(o.id)).map((o: any) => o.id)
  const ordered = inOrder.length > 1 && JSON.stringify(inOrder) === JSON.stringify([...pathIds].reverse().filter((x: number) => inOrder.includes(x)))

  return (
    <Page>
      <div className="mono" style={{ fontSize: 13, color: "var(--text-4)" }}><Link to="/app/incidents">Incidents</Link> / {inc.id}</div>
      <H1 title={`${inc.id}  ${inc.symptom.split(" · ")[0]}`}
        right={<div style={{ display: "flex", gap: 8 }}>
          <Btn variant="glass" onClick={() => navigator.clipboard?.writeText(summary).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500) })}>{copied ? "Copied" : "Copy summary"}</Btn>
          <Btn to={`/app/learn/${inc.id}`}>{inc.status === "Resolved" ? "Edit postmortem" : "Resolve and write postmortem"}</Btn>
        </div>} />
      <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
        <Stat label="Alerts" value={String(inc.alerts.length)} />
        <Stat label="Services in blast radius" value={String(v.blast.length)} />
        <Stat label="Time to verdict" value={`${v.ms} ms`} />
        <Stat label="Checks to root" value={inc.checks_to_root ? String(inc.checks_to_root) : "—"} sub={inc.checks_to_root ? undefined : "after the postmortem"} />
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 16, alignItems: "flex-start" }}>
        <section className="card" style={{ flex: "3 1 520px", minWidth: 0, padding: 18, display: "flex", flexDirection: "column", gap: 12 }}>
          <h2 style={{ margin: 0, fontSize: 16 }}>Blast radius</h2>
          {nodes.length ? <Graph nodes={nodes} edges={edges} height={Math.max(260, 70 * new Set(nodes.map((n) => n.tier)).size + 60)} /> : <Muted>Nothing matched the map.</Muted>}
          <Legend items={["Alerting", "Root cause", "Learned edge"]} />
        </section>
        <aside style={{ flex: "2 1 320px", minWidth: 0, display: "flex", flexDirection: "column", gap: 16 }}>
          <section className="card" style={{ padding: 18 }}>
            <h2 style={{ margin: "0 0 10px", fontSize: 16 }}>Verdict</h2>
            <RankList ranking={v.ranking} />
            {!v.ranking.length && <Muted>No alert name matched a service in the map{v.unresolved.length ? `: ${v.unresolved.slice(0, 4).join(", ")}` : ""}.</Muted>}
          </section>
          <section className="card" style={{ padding: 18, display: "flex", flexDirection: "column", gap: 8, fontSize: 14 }}>
            <h2 style={{ margin: 0, fontSize: 16 }}>Why this root</h2>
            <p style={{ margin: 0, color: "var(--text-3)" }}>Explains {v.explains} of {v.of} alerts along the strongest paths.</p>
            {v.learned_on_path.map((l: any, i: number) => (
              <p key={i} style={{ margin: 0, color: "var(--text-3)" }}>
                <span className="mono" style={{ color: "var(--accent-text)" }}>{nodes.find((n) => n.id === l.u)?.name} → {nodes.find((n) => n.id === l.v)?.name}</span>{" "}
                is a learned edge{l.incident ? `, from ${l.incident}` : ""}, confirmed {l.confirmations === 2 ? "twice" : l.confirmations === 1 ? "once" : `${l.confirmations} times`}.
              </p>
            ))}
            {ordered && <p style={{ margin: 0, color: "var(--text-3)" }}>Alerts fired in path order: {inOrder.map((x: number) => nodes.find((n) => n.id === x)?.name).join(", then ")}.</p>}
            {v.path.length > 0 && (
              <p className="mono" style={{ margin: "4px 0 0", fontSize: 13 }}>
                {v.path[0].u_name}{v.path.map((p: any, i: number) => (
                  <span key={i}><span style={{ color: p.origin === "learned" ? "var(--accent-text)" : undefined }}>{p.origin === "learned" ? " ⇢ " : " → "}</span>{p.v_name}</span>
                ))}
              </p>
            )}
          </section>
        </aside>
      </div>
      <section className="card" style={{ padding: 18 }}>
        <h2 style={{ margin: "0 0 12px", fontSize: 16 }}>Alert onset</h2>
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {onsets.slice(0, 12).map((o: any) => (
            <div key={o.id} className="mono" style={{ display: "grid", gridTemplateColumns: "150px 1fr 60px", gap: 12, alignItems: "center", fontSize: 12 }}>
              <span style={{ color: o.root ? "var(--accent-text)" : "var(--text-3)", overflow: "hidden", textOverflow: "ellipsis" }}>{o.name}</span>
              <span style={{ position: "relative", height: 8, background: "var(--muted)", borderRadius: 4 }}>
                <span style={{ position: "absolute", left: `${(o.onset / span) * 92}%`, width: "8%", top: 0, bottom: 0, background: "var(--amber)", borderRadius: 4 }} />
              </span>
              <span style={{ color: "var(--text-4)", textAlign: "right" }}>+{Math.round(o.onset)}s</span>
            </div>
          ))}
        </div>
      </section>
    </Page>
  )
}
