import { useMemo } from "react"
import { KIND_COLOR } from "./common"

export type GNode = { id: number; name: string; kind: string; tier: number; alerting?: boolean; root?: boolean }
export type GEdge = { u: number; v: number; origin: string; w?: number; path?: boolean }

/** Tier-layered SVG graph. Tier colours are for graph elements only: alerting = amber ring, root = violet fill, learned edge = violet dashed. */
export function Graph({ nodes, edges, height = 360, labels = true, onPick }: {
  nodes: GNode[]; edges: GEdge[]; height?: number; labels?: boolean; onPick?: (n: GNode) => void
}) {
  const W = 760
  const layout = useMemo(() => {
    const rows = new Map<number, GNode[]>()
    nodes.forEach((n) => rows.set(n.tier, [...(rows.get(n.tier) ?? []), n]))
    const tiers = [...rows.keys()].sort((a, b) => a - b)
    const pos = new Map<number, { x: number; y: number; dy: number }>()
    tiers.forEach((t, ti) => {
      const row = rows.get(t)!.sort((a, b) => a.name.localeCompare(b.name))
      row.forEach((n, i) => pos.set(n.id, { dy: row.length > 7 ? 20 + (i % 3) * 12 : 22, x: ((i + 1) * W) / (row.length + 1), y: tiers.length === 1 ? height / 2 : 34 + (ti * (height - 68)) / (tiers.length - 1) }))
    })
    return pos
  }, [nodes, height])
  return (
    <svg viewBox={`0 0 ${W} ${height}`} width="100%" role="img" aria-label="Dependency graph" style={{ display: "block" }}>
      {edges.map((e, i) => {
        const a = layout.get(e.u), b = layout.get(e.v)
        if (!a || !b) return null
        const learned = e.origin === "learned"
        return (
          <line key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke={learned ? "var(--accent)" : "var(--g-edge)"}
            strokeWidth={e.path ? 2.4 : 1.2} strokeDasharray={learned ? "5 4" : undefined} opacity={e.path ? 1 : learned ? 0.85 : 0.35} />
        )
      })}
      {nodes.map((n) => {
        const p = layout.get(n.id)!
        const fill = n.root ? "var(--accent)" : KIND_COLOR[n.kind] ?? "var(--g-service)"
        return (
          <g key={n.id} onClick={() => onPick?.(n)} style={{ cursor: onPick ? "pointer" : "default" }}>
            {n.alerting && <circle cx={p.x} cy={p.y} r={n.root ? 12 : 10.5} fill="none" stroke="var(--amber)" strokeWidth="2.4" />}
            <circle cx={p.x} cy={p.y} r={n.root ? 7.5 : 6} fill={fill} />
            {labels && (
              <text x={p.x} y={p.y + p.dy} textAnchor="middle" fontSize="10" fontFamily="Geist Mono, monospace" fill={n.root ? "var(--accent-text)" : "var(--text-3)"}>{n.name}</text>
            )}
          </g>
        )
      })}
    </svg>
  )
}

export function Legend({ items = ["Edge", "Service", "Data", "Infra", "Alerting", "Learned edge", "Root cause"] }: { items?: string[] }) {
  const swatch = (i: string) => {
    const k = i.toLowerCase()
    if (k === "alerting") return <span style={{ width: 12, height: 12, borderRadius: 99, border: "2px solid var(--amber)" }} />
    if (k === "learned edge") return <span style={{ width: 16, borderTop: "2px dashed var(--accent)" }} />
    if (k === "root cause") return <span style={{ width: 11, height: 11, borderRadius: 99, background: "var(--accent)" }} />
    return <span style={{ width: 10, height: 10, borderRadius: 99, background: KIND_COLOR[k] }} />
  }
  return (
    <div className="mono" style={{ display: "flex", flexWrap: "wrap", gap: 14, fontSize: 12, color: "var(--text-3)" }}>
      {items.map((i) => <span key={i} style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>{swatch(i)}{i}</span>)}
    </div>
  )
}
