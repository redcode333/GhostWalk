import { useEffect, useMemo, useRef, useState } from "react"
import { CircleDot, MessageSquare } from "lucide-react"
import { Graph, Legend, type GEdge } from "@/components/Graph"
import { ChangeRows, LearnedList, RankList } from "@/components/panels"
import { loadDemo, type Demo } from "@/lib/demo"

const TABS = ["Investigate", "Map", "Learn"] as const
const CYCLE_MS = 6000

/** Shortest dependency route from the entry service to `target`, over the edges currently in the graph. */
function routeTo(edges: { u: number; v: number }[], from: number, to: number): Set<string> {
  const prev = new Map<number, number>([[from, -1]])
  const q = [from]
  while (q.length) {
    const x = q.shift()!
    if (x === to) break
    for (const e of edges) if (e.u === x && !prev.has(e.v)) { prev.set(e.v, x); q.push(e.v) }
  }
  const out = new Set<string>()
  let c = to
  while (prev.has(c) && prev.get(c)! >= 0) { out.add(`${prev.get(c)}>${c}`); c = prev.get(c)! }
  return out
}

export function InsideGhostWalk() {
  const [d, setD] = useState<Demo | null>(null)
  const [front, setFront] = useState(0)
  const [applied, setApplied] = useState(false)
  const [pulse, setPulse] = useState(false)
  const [hover, setHover] = useState<number | null>(null)
  const clicked = useRef(false)

  useEffect(() => { loadDemo().then(setD) }, [])
  useEffect(() => {
    if (!d || window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return
    const t = setInterval(() => { if (!clicked.current && !document.hidden) setFront((f) => (f + 1) % 3) }, CYCLE_MS)
    return () => clearInterval(t)
  }, [d])

  const view = useMemo(() => {
    if (!d) return null
    const edges = [...d.edges, ...(applied ? d.learned_edges.map((e) => ({ u: e.u, v: e.v, origin: "learned" })) : [])]
    const ranking = (applied ? d.after : d.before).ranking
    const entry = [...d.nodes].filter((n) => n.alerting).sort((a, b) => a.tier - b.tier)[0].id
    const target = hover ?? ranking[0].id
    const route = routeTo(edges, entry, target)
    const gEdges: GEdge[] = edges.map((e) => ({ u: e.u, v: e.v, origin: e.origin, path: route.has(`${e.u}>${e.v}`),
      pulse: e.origin === "learned" && pulse, flow: e.origin === "learned" && applied }))
    const nodes = d.nodes.map((n) => ({ ...n, root: n.id === ranking[0].id }))
    return { edges: gEdges, nodes, ranking }
  }, [d, applied, hover, pulse])

  if (!d || !view) return null
  const name = (id: number) => d.nodes.find((n) => n.id === id)?.name
  const apply = () => { setApplied(true); setPulse(true); setTimeout(() => setPulse(false), 3600); clicked.current = true }
  const choose = (i: number) => { clicked.current = true; setFront(i) }

  const panelShell = (title: string, sub: string, children: React.ReactNode) => (
    <div className="app dark" style={{ height: "100%", background: "var(--surface)", border: "1px solid var(--line)", borderRadius: 18, padding: 18, overflow: "hidden", color: "var(--ink)",
      WebkitMaskImage: "linear-gradient(to bottom, #000 68%, transparent)", maskImage: "linear-gradient(to bottom, #000 68%, transparent)", boxSizing: "border-box" }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginBottom: 10 }}>
        <strong style={{ fontSize: 15 }}>{title}</strong><span className="mono" style={{ fontSize: 12, color: "var(--text-4)" }}>{sub}</span>
      </div>
      {children}
    </div>
  )

  const panels = [
    panelShell("INC-1042 · checkout-api 5xx", `${d.alerts} alerts`, (
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) minmax(0,1.5fr)", gap: 16 }} className="inside-grid">
        <div><div style={{ fontSize: 12, color: "var(--text-4)", marginBottom: 4 }}>Verdict · hover a candidate</div><RankList ranking={view.ranking} hover={hover} onHover={setHover} /></div>
        <div><Graph nodes={view.nodes} edges={view.edges} height={230} /></div>
      </div>)),
    panelShell("Dependency map", `${d.nodes.length} services`, (
      <div>
        <Graph nodes={view.nodes} edges={view.edges} height={250} tierLabels />
        <Legend items={["Edge", "Service", "Data", "Infra", "Learned edge"]} />
        {applied && <div style={{ marginTop: 8 }}><LearnedList edges={d.learned_edges} name={name} /></div>}
      </div>)),
    panelShell("Learn from INC-1042", "3 fields → graph changes", (
      <div>
        <ChangeRows rows={d.changes} action={(r) => r.apply
          ? (applied ? <span style={{ color: "var(--ok)", fontSize: 13 }}>Applied ✓</span> : <button className="chip on" onClick={apply} style={{ padding: "3px 12px", fontSize: 12 }}>Apply</button>)
          : <span style={{ color: "var(--text-4)", fontSize: 12 }}>with it</span>} />
        <p style={{ fontSize: 12, color: "var(--text-4)", margin: "10px 0 0" }}>New edges start tentative. One more matching incident makes them count in full.</p>
      </div>)),
  ]
  const top = view.ranking[0]
  const slotStyle = (slot: number): React.CSSProperties => slot === 0
    ? { transform: "translateX(0) scale(1) rotate(0deg)", opacity: 1, zIndex: 3, filter: "none" }
    : slot === 1 ? { transform: "translateX(26%) scale(.92) rotate(4deg)", opacity: 0.55, zIndex: 1, filter: "blur(1px)" }
      : { transform: "translateX(-26%) scale(.92) rotate(-4deg)", opacity: 0.55, zIndex: 1, filter: "blur(1px)" }

  return (
    <section id="inside" style={{ maxWidth: 1240, margin: "0 auto", padding: "88px 24px 0", scrollMarginTop: 90, overflowX: "clip" }}>
      <div style={{ textAlign: "center", marginBottom: 28 }}>
        <span className="eyebrow">Inside GhostWalk</span>
        <h2 style={{ margin: "10px 0 0", fontSize: "clamp(30px, 4.4vw, 48px)", lineHeight: 1.08, letterSpacing: "-0.03em", fontWeight: 600 }}>The same app you would run on call</h2>
        <p style={{ margin: "12px auto 0", maxWidth: 620, fontSize: 18, color: "var(--text-3)" }}>These are the real panels. Hover a candidate, then apply the lesson and watch the verdict change.</p>
      </div>
      <div role="tablist" aria-label="Panels" style={{ display: "flex", justifyContent: "center", gap: 8, marginBottom: 24 }}>
        {TABS.map((t, i) => <button key={t} role="tab" aria-selected={front === i} className={`chip${front === i ? " on" : ""}`} onClick={() => choose(i)}>{t}</button>)}
      </div>
      <div style={{ position: "relative", height: 500, maxWidth: 1000, margin: "0 auto" }}>
        {panels.map((p, i) => {
          const slot = (i - front + 3) % 3
          return (
            <div key={i} className="stack-panel" data-slot={slot} onClick={() => slot !== 0 && choose(i)} aria-hidden={slot !== 0}
              style={{ position: "absolute", left: "9%", width: "82%", top: 0, height: 460, transition: "transform .4s cubic-bezier(.34,1.3,.64,1), opacity .4s, filter .4s", cursor: slot ? "pointer" : "default", ...slotStyle(slot) }}>
              {p}
            </div>)
        })}
        <div className="float-card" style={{ position: "absolute", left: -8, bottom: 70, width: 270, zIndex: 5, padding: "12px 14px", borderRadius: 14, background: "var(--surface)", border: "1px solid var(--line)", boxShadow: "0 24px 40px -22px rgba(0,0,0,.5)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: "var(--text-4)" }}><MessageSquare size={14} /><strong style={{ color: "var(--text-2)" }}>ghostwalk</strong><span className="mono">#incidents · 14:02</span></div>
          <div style={{ fontSize: 14, marginTop: 6 }}>Root cause: <span className="mono" style={{ color: "var(--accent-text)" }}>{top.name}</span> <span className="mono" style={{ color: "var(--text-4)" }}>{top.confidence.toFixed(2)}</span></div>
          <div className="mono" style={{ fontSize: 12, color: "var(--text-4)", marginTop: 2 }}>explains {d.alerts} of {d.alerts} alerts</div>
        </div>
        <div className="float-card" style={{ position: "absolute", right: -8, bottom: 40, width: 270, zIndex: 5, padding: "12px 14px", borderRadius: 14, background: "var(--surface)", border: "1px solid var(--line)", boxShadow: "0 24px 40px -22px rgba(0,0,0,.5)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: "var(--text-4)" }}><CircleDot size={14} /><span className="mono">issue #214</span>
            <span className="mono" style={{ marginLeft: "auto", border: "1px solid var(--accent)", color: "var(--accent-text)", borderRadius: 999, padding: "1px 8px" }}>postmortem</span></div>
          <div style={{ fontSize: 14, marginTop: 6 }}>INC-1042: {d.after.ranking[0].name} was the root</div>
          <div className="mono" style={{ fontSize: 12, color: "var(--text-4)", marginTop: 2 }}>3 fields → {d.changes.length} proposed changes</div>
        </div>
      </div>
    </section>
  )
}
