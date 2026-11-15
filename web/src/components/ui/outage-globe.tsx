import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react"
import createGlobe, { type Globe } from "cobe"
import { OUTAGES } from "@/data/outages"

/* Engine reused from the testimonial-globe component: toCartesian / project / facingPhi / nearestTurn, pinOpacity / pinScale,
   drag with friction, off-screen pause and a no-WebGL fallback. No testimonials, portraits or review counts. */
type Vec3 = [number, number, number]
const GLOBE_RADIUS = 0.8
const CYCLE_MS = 4800
const TURN_MS = 1200
const TILT = 0.45
const DRAG_FRICTION = 0.92
const D2R = Math.PI / 180
const clamp01 = (v: number) => Math.min(1, Math.max(0, v))
const smooth = (t: number) => t * t * (3 - 2 * t)
const easeOutExpo = (t: number) => (t >= 1 ? 1 : (1 - Math.pow(2, -10 * t)) / (1 - Math.pow(2, -10)))

function toCartesian(lat: number, lng: number): Vec3 {
  const la = lat * D2R, lo = lng * D2R - Math.PI, c = Math.cos(la)
  return [-c * Math.cos(lo), Math.sin(la), c * Math.sin(lo)]
}
function project([x, y, z]: Vec3, phi: number, theta: number, altitude = 0.05) {
  const cp = Math.cos(phi), sp = Math.sin(phi), ct = Math.cos(theta), st = Math.sin(theta)
  const r = GLOBE_RADIUS * (1 + altitude)
  const sx = (cp * x + sp * z) * r
  const sy = (sp * st * x + ct * y - cp * st * z) * r
  const depth = -sp * ct * x + st * y + cp * ct * z
  return { x: (sx + 1) / 2, y: (1 - sy) / 2, depth, rim: Math.hypot(sx, sy) - GLOBE_RADIUS }
}
const facingPhi = (lng: number) => (3 * Math.PI) / 2 - lng * D2R
function nearestTurn(from: number, angle: number) {
  const tau = Math.PI * 2
  return angle + tau * Math.round((from - angle) / tau)
}
function pinOpacity(depth: number, rim: number) {
  if (depth >= 0) return 0.45 + 0.55 * smooth(clamp01(depth / 0.3))
  const exposed = Math.max(clamp01(rim / 0.04), clamp01(1 + depth * 8))
  return 0.45 * exposed * clamp01(1 + depth * 3)
}
const pinScale = (depth: number) => 0.62 + 0.38 * smooth(clamp01((depth + 0.2) / 0.7))
function slerp(a: Vec3, b: Vec3, t: number): Vec3 {
  const d = Math.acos(Math.max(-1, Math.min(1, a[0] * b[0] + a[1] * b[1] + a[2] * b[2])))
  const s = Math.sin(d) || 1, k1 = Math.sin((1 - t) * d) / s, k2 = Math.sin(t * d) / s
  const lift = 1 + 0.16 * Math.sin(Math.PI * t)
  return [(a[0] * k1 + b[0] * k2) * lift, (a[1] * k1 + b[1] * k2) * lift, (a[2] * k1 + b[2] * k2) * lift]
}
const VEC = OUTAGES.map((o) => toCartesian(o.lat, o.lng))

export function OutageGlobe() {
  const [ix, setIx] = useState(0)
  const [w, setW] = useState(0)
  const [gl, setGl] = useState<"pending" | "ready" | "unavailable">("pending")
  const root = useRef<HTMLDivElement>(null)
  const host = useRef<HTMLDivElement>(null)
  const card = useRef<HTMLDivElement>(null)
  const pins = useRef<(HTMLButtonElement | null)[]>([])
  const arcs = useRef<(SVGPathElement | null)[]>([])
  const s = useRef({ phi: facingPhi(OUTAGES[0].lng), theta: OUTAGES[0].lat * D2R - TILT, vel: 0, dragging: false, start: 0, ix: 0, visible: true, reduced: false,
    from: { phi: 0, theta: 0 }, to: { phi: 0, theta: 0 }, last: 0, moved: 0 })
  const timer = useRef<number | null>(null)
  const raf = useRef(0)
  const kick = useRef<() => void>(() => {})
  const H = 500
  const D = Math.round(Math.min(1100, Math.max(640, w * 1.15)))     // a square wider than the crop, so only the upper part shows: a horizon

  useLayoutEffect(() => {
    const el = root.current
    if (!el) return
    const ro = new ResizeObserver(() => setW(el.clientWidth))
    ro.observe(el)
    setW(el.clientWidth)
    return () => ro.disconnect()
  }, [])

  const aim = useCallback((i: number) => {
    const e = s.current
    e.ix = i
    e.from = { phi: e.phi, theta: e.theta }
    e.to = { phi: nearestTurn(e.phi, facingPhi(OUTAGES[i].lng)), theta: OUTAGES[i].lat * D2R - TILT }
    e.vel = 0
    if (e.reduced) { e.phi = e.to.phi; e.theta = e.to.theta; e.start = 0 } else e.start = performance.now()
    kick.current()
  }, [])

  const stopTimer = () => { if (timer.current) { clearInterval(timer.current); timer.current = null } }
  const startTimer = useCallback(() => {
    stopTimer()
    if (s.current.reduced) return
    timer.current = window.setInterval(() => {
      if (s.current.visible && !document.hidden && !s.current.dragging) { const n = (s.current.ix + 1) % OUTAGES.length; setIx(n); aim(n) }
    }, CYCLE_MS)
  }, [aim])

  const pick = (i: number) => { setIx(i); aim(i); startTimer() }

  useEffect(() => {
    const host_ = host.current
    if (!host_ || !w) return
    const e = s.current
    e.reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false
    const canvas = document.createElement("canvas")
    canvas.style.cssText = "width:100%;height:100%;display:block"
    host_.appendChild(canvas)
    let globe: Globe | null = null
    try {
      globe = createGlobe(canvas, { devicePixelRatio: Math.min(window.devicePixelRatio || 1, 2), width: D, height: D, phi: e.phi, theta: e.theta, dark: 1, diffuse: 1.2,
        mapSamples: 16000, mapBrightness: 6, baseColor: [0.3, 0.3, 0.3], markerColor: [0.557, 0.463, 1], glowColor: [0.5, 0.5, 0.5], markers: [] })
    } catch { globe = null }
    const ctx = globe ? (canvas.getContext("webgl2") ?? canvas.getContext("webgl")) : null
    setGl(ctx ? "ready" : "unavailable")
    const theme = () => {
      const dark = document.documentElement.classList.contains("dark")
      globe?.update({ dark: dark ? 1 : 0, diffuse: dark ? 1.2 : 0.4, mapBrightness: dark ? 6 : 1.2,
        baseColor: dark ? [0.3, 0.3, 0.3] : [0.93, 0.92, 0.89], glowColor: dark ? [0.45, 0.4, 0.8] : [0.6, 0.55, 0.9] })
    }
    theme()
    const mo = new MutationObserver(() => { theme(); kick.current() })
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] })

    const place = () => {
      const left0 = (D - (root.current?.clientWidth ?? w)) / 2
      OUTAGES.forEach((_, i) => {
        const el = pins.current[i]
        if (!el) return
        const p = project(VEC[i], e.phi, e.theta)
        const o = pinOpacity(p.depth, p.rim)
        const active = i === e.ix
        el.style.opacity = String(active ? Math.max(o, 0) : o)
        el.style.visibility = o < 0.03 ? "hidden" : "visible"
        el.style.transform = `translate(${(p.x * D - left0).toFixed(1)}px, ${(p.y * D).toFixed(1)}px) scale(${(pinScale(p.depth) * (active ? 1.25 : 1)).toFixed(3)})`
        el.style.zIndex = String(Math.round(p.depth * 10) + (active ? 20 : 0))
      })
      const a = project(VEC[e.ix], e.phi, e.theta)
      const cw = card.current
      if (cw) {
        const cwid = Math.min(300, (root.current?.clientWidth ?? w) - 24)
        const ax = a.x * D - left0, ay = a.y * D
        const rightFree = ax + 30 + cwid < (root.current?.clientWidth ?? w) - 8
        cw.style.transform = `translate(${Math.max(12, rightFree ? ax + 30 : ax - 30 - cwid)}px, ${Math.max(14, Math.min(H - 215, ay - 70))}px)`
        cw.style.opacity = a.depth > 0.05 ? "1" : "0"
      }
      // dashed arcs from the active pin: amber to two others, violet to a third
      const targets = [(e.ix + 1) % OUTAGES.length, (e.ix + 2) % OUTAGES.length, (e.ix + 3) % OUTAGES.length]
      targets.forEach((t, k) => {
        let d = "", pen = false
        for (let n = 0; n <= 36; n++) {
          const q = project(slerp(VEC[e.ix], VEC[t], n / 36), e.phi, e.theta, 0)
          if (q.depth < 0.03) { pen = false; continue }
          d += `${pen ? "L" : "M"}${(q.x * D - left0).toFixed(1)},${(q.y * D).toFixed(1)} `
          pen = true
        }
        arcs.current[k]?.setAttribute("d", d)
      })
    }

    const frame = (now: number) => {
      raf.current = 0
      const dt = e.last ? Math.min((now - e.last) / 1000, 0.1) : 0
      e.last = now
      if (e.start) {
        const t = clamp01((now - e.start) / TURN_MS), k = easeOutExpo(t)
        e.phi = e.from.phi + (e.to.phi - e.from.phi) * k
        e.theta = e.from.theta + (e.to.theta - e.from.theta) * k
        if (t >= 1) e.start = 0
      } else if (!e.dragging && Math.abs(e.vel) > 1e-4) {
        const steps = dt * 60
        e.phi += e.vel * steps
        e.vel *= Math.pow(DRAG_FRICTION, steps)
        if (Math.abs(e.vel) <= 1e-4) {            // settled: the pin now facing the viewer becomes the featured one
          e.vel = 0
          let best = e.ix, bd = -2
          VEC.forEach((v, i) => { const d = project(v, e.phi, e.theta).depth; if (d > bd) { bd = d; best = i } })
          if (best !== e.ix) { e.ix = best; setIx(best) }
        }
      }
      globe?.update({ phi: e.phi, theta: e.theta })
      place()
      if ((e.start || e.dragging || Math.abs(e.vel) > 1e-4) && e.visible && !document.hidden) raf.current = requestAnimationFrame(frame)
      else e.last = 0
    }
    kick.current = () => { if (!raf.current) raf.current = requestAnimationFrame(frame) }
    kick.current()
    const retries = [150, 600, 1500].map((ms) => window.setTimeout(() => kick.current(), ms))   // cobe uploads its land texture late

    const io = new IntersectionObserver(([en]) => { e.visible = en.isIntersecting; if (en.isIntersecting) kick.current() }, { threshold: 0.05 })
    io.observe(root.current!)
    const vis = () => { if (!document.hidden) kick.current() }
    document.addEventListener("visibilitychange", vis)
    startTimer()
    return () => {
      cancelAnimationFrame(raf.current); raf.current = 0
      retries.forEach(clearTimeout); stopTimer()
      io.disconnect(); mo.disconnect()
      document.removeEventListener("visibilitychange", vis)
      globe?.destroy()
      host_.replaceChildren()
    }
  }, [w > 0, D])

  // drag to spin, with friction on release
  const drag = useRef({ x: 0, id: -1 })
  const down = (ev: React.PointerEvent) => {
    if ((ev.target as HTMLElement).closest("a,[data-snip]")) return
    drag.current = { x: ev.clientX, id: ev.pointerId }
    s.current.dragging = true; s.current.start = 0; s.current.vel = 0; s.current.moved = 0
    ;(ev.currentTarget as HTMLElement).setPointerCapture(ev.pointerId)
    stopTimer(); kick.current()
  }
  const move = (ev: React.PointerEvent) => {
    if (!s.current.dragging) return
    const dx = ev.clientX - drag.current.x
    drag.current.x = ev.clientX
    s.current.phi += dx * 0.005
    s.current.vel = dx * 0.005 * 0.6
    s.current.moved += Math.abs(dx)
    kick.current()
  }
  const up = () => {
    if (!s.current.dragging) return
    s.current.dragging = false
    if (Math.abs(s.current.vel) <= 1e-4) s.current.vel = 1e-3
    startTimer(); kick.current()
  }

  const o = OUTAGES[ix]
  return (
    <div>
      <div ref={root} onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={up}
        style={{ position: "relative", height: H, overflow: "hidden", maxWidth: 1240, margin: "0 auto", touchAction: "pan-y", cursor: "grab" }}>
        {gl === "unavailable" && <div aria-hidden="true" style={{ position: "absolute", left: "50%", top: 60, width: 760, height: 760, marginLeft: -380, borderRadius: "50%", background: "radial-gradient(circle at 35% 30%, var(--surface), var(--muted))", border: "1px solid var(--line)" }} />}
        <div ref={host} aria-hidden="true" style={{ position: "absolute", top: 0, left: "50%", width: D, height: D, transform: "translateX(-50%)" }} />
        <svg aria-hidden="true" width="100%" height={H} style={{ position: "absolute", inset: 0, pointerEvents: "none", overflow: "visible" }}>
          <path ref={(n) => { arcs.current[0] = n }} fill="none" stroke="var(--amber)" strokeWidth="1.8" strokeDasharray="5 5" strokeLinecap="round" />
          <path ref={(n) => { arcs.current[1] = n }} fill="none" stroke="var(--amber)" strokeWidth="1.8" strokeDasharray="5 5" strokeLinecap="round" />
          <path ref={(n) => { arcs.current[2] = n }} fill="none" stroke="var(--accent)" strokeWidth="2" strokeDasharray="5 5" strokeLinecap="round" />
        </svg>
        {OUTAGES.map((x, i) => (
          <button key={x.company} ref={(n) => { pins.current[i] = n }} aria-label={`Show ${x.company}, ${x.when}`} aria-pressed={i === ix} onClick={() => { if (s.current.moved < 6) pick(i) }}
            style={{ position: "absolute", left: 0, top: 0, width: 16, height: 16, margin: "-8px 0 0 -8px", padding: 0, border: 0, background: "transparent", cursor: "pointer", willChange: "transform" }}>
            <span className="ring" aria-hidden="true" style={{ position: "absolute", inset: 0, borderRadius: 99, border: `2px solid ${i === ix ? "var(--accent)" : "var(--amber)"}` }} />
            <span aria-hidden="true" style={{ position: "absolute", inset: 3, borderRadius: 99, background: i === ix ? "var(--accent)" : "var(--amber)", boxShadow: "0 0 0 2px var(--bg)" }} />
          </button>
        ))}
        <div ref={card} data-snip role="status" aria-live="polite" style={{ position: "absolute", left: 0, top: 0, width: "min(300px, calc(100% - 24px))", padding: "14px 16px", borderRadius: 16, zIndex: 40,
          border: "1px solid var(--line)", background: "linear-gradient(180deg, rgba(var(--lrgb),.08), rgba(var(--lrgb),.03))", backdropFilter: "blur(14px)", WebkitBackdropFilter: "blur(14px)",
          boxShadow: "inset 0 1px 0 rgba(255,255,255,.22), 0 20px 40px -22px rgba(0,0,0,.5)", transition: "opacity .25s" }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}><strong style={{ fontSize: 15 }}>{o.company}</strong><span className="mono" style={{ fontSize: 12, color: "var(--text-4)" }}>{o.when}</span></div>
          <p style={{ margin: "6px 0 8px", fontSize: 14, color: "var(--text-2)", lineHeight: 1.4 }}>{o.what}</p>
          <div className="mono" style={{ fontSize: 12, color: "var(--accent-text)", display: "flex", alignItems: "center", gap: 8 }}>
            <span aria-hidden="true" style={{ width: 16, borderTop: "2px dashed var(--accent)" }} />{o.edge}
          </div>
          {o.cost && <a href={o.costSource} target="_blank" rel="noreferrer" className="mono" style={{ display: "block", marginTop: 6, fontSize: 12, color: "var(--amber-text)" }}>{o.cost}</a>}
          <a href={o.source} target="_blank" rel="noreferrer" style={{ display: "inline-block", marginTop: 6, fontSize: 12, color: "var(--text-4)", textDecoration: "underline" }}>source</a>
        </div>
        <div aria-hidden="true" style={{ position: "absolute", inset: "auto 0 0 0", height: 150, background: "linear-gradient(to bottom, transparent, var(--bg))", pointerEvents: "none", zIndex: 20 }} />
      </div>
      <div role="group" aria-label="Outages" style={{ display: "flex", flexWrap: "wrap", justifyContent: "center", gap: 8, marginTop: 4, padding: "0 16px" }}>
        {OUTAGES.map((x, i) => <button key={x.company} className={`chip${i === ix ? " on" : ""}`} aria-pressed={i === ix} onClick={() => pick(i)}>{x.company}</button>)}
      </div>
      <p style={{ textAlign: "center", color: "var(--text-4)", fontSize: 15, margin: "16px 16px 0" }}>Real outages from public postmortems. Each one spread through a dependency.</p>
    </div>
  )
}
