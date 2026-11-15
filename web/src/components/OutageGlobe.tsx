import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react"
import createGlobe, { type Globe } from "cobe"
import { OUTAGES } from "@/data/outages"

/* Globe maths reused from design/testimonial-globe.prompt.txt (same rotation cobe applies on the GPU, so HTML pins stay on the map). */
type Vec3 = [number, number, number]
const GLOBE_RADIUS = 0.8
const CYCLE_MS = 4800
const TURN_MS = 1200
const TILT = 0.45
const D2R = Math.PI / 180
const clamp01 = (v: number) => Math.min(1, Math.max(0, v))
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
  return { x: (sx + 1) / 2, y: (1 - sy) / 2, depth }
}
const facingPhi = (lng: number) => (3 * Math.PI) / 2 - lng * D2R
function nearestTurn(from: number, angle: number) {
  const tau = Math.PI * 2
  return angle + tau * Math.round((from - angle) / tau)
}
function slerp(a: Vec3, b: Vec3, t: number): Vec3 {
  const d = Math.acos(Math.max(-1, Math.min(1, a[0] * b[0] + a[1] * b[1] + a[2] * b[2])))
  const s = Math.sin(d) || 1, k1 = Math.sin((1 - t) * d) / s, k2 = Math.sin(t * d) / s
  const lift = 1 + 0.18 * Math.sin(Math.PI * t)
  return [(a[0] * k1 + b[0] * k2) * lift, (a[1] * k1 + b[1] * k2) * lift, (a[2] * k1 + b[2] * k2) * lift]
}

const VIOLET: [number, number, number] = [0.557, 0.463, 1]
const AMBER: [number, number, number] = [0.96, 0.72, 0.25]
const ZERO = (): [number, number, number] => [0, 0, 0]

export function OutageGlobe() {
  const [ix, setIx] = useState(0)
  const [box, setBox] = useState({ w: 0 })
  const [pin, setPin] = useState<{ x: number; y: number; ok: boolean }>({ x: 0.5, y: 0.5, ok: true })
  const [dashed, setDashed] = useState("")
  const root = useRef<HTMLDivElement>(null)
  const host = useRef<HTMLDivElement>(null)
  const st = useRef({ phi: facingPhi(OUTAGES[0].lng), theta: OUTAGES[0].lat * D2R - TILT, from: { phi: 0, theta: 0 }, to: { phi: 0, theta: 0 }, start: 0, ix: 0, visible: true, reduced: false })
  const globeRef = useRef<Globe | null>(null)
  const timer = useRef<number | null>(null)
  const raf = useRef(0)
  const kick = useRef<() => void>(() => {})

  const D = Math.min(1100, Math.max(640, box.w * 1.15))     // globe canvas is a square wider than the crop: a horizon
  const H = 500

  useLayoutEffect(() => {
    const el = root.current
    if (!el) return
    const ro = new ResizeObserver(() => setBox({ w: el.clientWidth }))
    ro.observe(el)
    setBox({ w: el.clientWidth })
    return () => ro.disconnect()
  }, [])

  const arcsFor = (i: number) => {
    const o = OUTAGES, n = o.length
    const from: [number, number] = [o[i].lat, o[i].lng]
    return [1, 2].map((k) => ({ from, to: [o[(i + k) % n].lat, o[(i + k) % n].lng] as [number, number], color: AMBER }))
  }

  const aim = useCallback((i: number, instant = false) => {
    const s = st.current
    const t = { phi: nearestTurn(s.phi, facingPhi(OUTAGES[i].lng)), theta: OUTAGES[i].lat * D2R - TILT }
    s.ix = i
    s.from = { phi: s.phi, theta: s.theta }
    s.to = t
    s.start = performance.now()
    if (s.reduced || instant) { s.phi = t.phi; s.theta = t.theta; s.start = 0 }
    kick.current()
  }, [])

  const go = useCallback((i: number, manual: boolean) => {
    setIx(i)
    aim(i)
    if (manual && timer.current) { clearInterval(timer.current); timer.current = null; start() }
  }, [aim])

  const start = () => {
    if (st.current.reduced || timer.current) return
    timer.current = window.setInterval(() => { if (st.current.visible && !document.hidden) { const n = (st.current.ix + 1) % OUTAGES.length; setIx(n); aim(n) } }, CYCLE_MS)
  }

  // the cobe globe
  useEffect(() => {
    const h = host.current
    if (!h || !box.w) return
    const s = st.current
    s.reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false
    const canvas = document.createElement("canvas")
    canvas.style.cssText = "width:100%;height:100%;display:block"
    h.appendChild(canvas)
    let globe: Globe | null = null
    try {
      globe = createGlobe(canvas, { devicePixelRatio: Math.min(window.devicePixelRatio || 1, 2), width: D, height: D, phi: s.phi, theta: s.theta, dark: 1, diffuse: 1.2,
        mapSamples: 16000, mapBrightness: 6, baseColor: [0.3, 0.3, 0.3], markerColor: VIOLET, glowColor: [0.5, 0.5, 0.5], markers: [], arcs: [], arcColor: AMBER, arcWidth: 0.5, arcHeight: 0.25, markerElevation: 0.01 })
    } catch { globe = null }
    globeRef.current = globe
    const theme = () => {
      const dark = document.documentElement.classList.contains("dark")
      globe?.update({ dark: dark ? 1 : 0, diffuse: dark ? 1.2 : 0.4, mapBrightness: dark ? 6 : 1.2,
        baseColor: dark ? [0.3, 0.3, 0.3] : [0.93, 0.92, 0.9], glowColor: dark ? [0.5, 0.5, 0.5] : [0.7, 0.68, 0.64],
        markerColor: dark ? VIOLET : [0.416, 0.294, 1], arcColor: dark ? AMBER : [0.85, 0.59, 0.08] })
    }
    theme()
    const mo = new MutationObserver(() => { theme(); kick.current() })
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] })

    let last = 0
    const frame = (now: number) => {
      raf.current = 0
      const e = st.current
      if (e.start) {
        const t = clamp01((now - e.start) / TURN_MS), k = easeOutExpo(t)
        e.phi = e.from.phi + (e.to.phi - e.from.phi) * k
        e.theta = e.from.theta + (e.to.theta - e.from.theta) * k
        if (t >= 1) e.start = 0
      }
      globe?.update({ phi: e.phi, theta: e.theta, markers: [{ location: [OUTAGES[e.ix].lat, OUTAGES[e.ix].lng], size: 0.07 }], arcs: arcsFor(e.ix) })
      const p = project(toCartesian(OUTAGES[e.ix].lat, OUTAGES[e.ix].lng), e.phi, e.theta)
      setPin({ x: p.x, y: p.y, ok: p.depth > 0 })
      // the dashed violet arc to a third outage, drawn as an overlay (cobe arcs are solid)
      const a = toCartesian(OUTAGES[e.ix].lat, OUTAGES[e.ix].lng), b = toCartesian(OUTAGES[(e.ix + 3) % OUTAGES.length].lat, OUTAGES[(e.ix + 3) % OUTAGES.length].lng)
      let d = "", pen = false
      for (let i = 0; i <= 40; i++) {
        const q = project(slerp(a, b, i / 40), e.phi, e.theta, 0)
        if (q.depth < 0.02) { pen = false; continue }
        d += `${pen ? "L" : "M"}${(q.x * D).toFixed(1)},${(q.y * D).toFixed(1)} `
        pen = true
      }
      setDashed(d)
      last = now
      if (e.start && e.visible && !document.hidden) raf.current = requestAnimationFrame(frame)
    }
    kick.current = () => { if (!raf.current) raf.current = requestAnimationFrame(frame) }
    kick.current()
    const retry = [150, 600, 1500].map((ms) => window.setTimeout(() => kick.current(), ms))   // cobe loads its land texture late

    const io = new IntersectionObserver(([en]) => { s.visible = en.isIntersecting; if (en.isIntersecting) kick.current() }, { threshold: 0.05 })
    io.observe(root.current!)
    const onVis = () => { if (!document.hidden) kick.current() }
    document.addEventListener("visibilitychange", onVis)
    start()
    return () => {
      cancelAnimationFrame(raf.current); raf.current = 0
      retry.forEach(clearTimeout)
      if (timer.current) { clearInterval(timer.current); timer.current = null }
      io.disconnect(); mo.disconnect()
      document.removeEventListener("visibilitychange", onVis)
      globe?.destroy()
      h.replaceChildren()
      void last
    }
  }, [box.w > 0, D])

  const o = OUTAGES[ix]
  const cardW = 300
  const px = pin.x * D - (D - box.w) / 2
  const left = Math.max(12, Math.min(box.w - cardW - 12, px + 24))
  const top = Math.max(16, Math.min(H - 150, pin.y * D - 60))

  return (
    <div>
      <div ref={root} style={{ position: "relative", height: H, overflow: "hidden", maxWidth: 1240, margin: "0 auto" }}>
        <div ref={host} aria-hidden="true" style={{ position: "absolute", top: 0, left: "50%", width: D, height: D, transform: "translateX(-50%)" }} />
        <svg aria-hidden="true" width={D} height={D} viewBox={`0 0 ${D} ${D}`} style={{ position: "absolute", top: 0, left: "50%", transform: "translateX(-50%)", pointerEvents: "none" }}>
          <path d={dashed} fill="none" stroke="var(--accent)" strokeWidth="2" strokeDasharray="6 6" strokeLinecap="round" opacity="0.9" />
        </svg>
        {pin.ok && (
          <span aria-hidden="true" style={{ position: "absolute", left: px, top: pin.y * D, width: 14, height: 14, marginLeft: -7, marginTop: -7, borderRadius: 99, border: "2px solid var(--accent)", background: "var(--bg)" }} />
        )}
        <div data-snip role="status" aria-live="polite" style={{ position: "absolute", left, top, width: cardW, padding: "14px 16px", borderRadius: 16, border: "1px solid var(--line)",
          background: "linear-gradient(180deg, rgba(var(--lrgb),.07), rgba(var(--lrgb),.03))", backdropFilter: "blur(14px)", WebkitBackdropFilter: "blur(14px)", boxShadow: "inset 0 1px 0 rgba(255,255,255,.18), 0 20px 40px -20px rgba(0,0,0,.45)" }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
            <strong style={{ fontSize: 15 }}>{o.company}</strong><span className="mono" style={{ fontSize: 12, color: "var(--text-4)" }}>{o.when}</span>
          </div>
          <p style={{ margin: "6px 0 8px", fontSize: 14, color: "var(--text-2)", lineHeight: 1.4 }}>{o.what}</p>
          <div className="mono" style={{ fontSize: 12, color: "var(--accent-text)" }}>{o.edge}</div>
          <a href={o.source} target="_blank" rel="noreferrer" style={{ fontSize: 12, color: "var(--text-4)", textDecoration: "underline" }}>source</a>
        </div>
        <div aria-hidden="true" style={{ position: "absolute", inset: "auto 0 0 0", height: 140, background: "linear-gradient(to bottom, transparent, var(--bg))", pointerEvents: "none" }} />
      </div>
      <div role="group" aria-label="Outages" style={{ display: "flex", flexWrap: "wrap", justifyContent: "center", gap: 8, marginTop: 4, padding: "0 16px" }}>
        {OUTAGES.map((x, i) => <button key={x.company} className={`chip${i === ix ? " on" : ""}`} aria-pressed={i === ix} onClick={() => go(i, true)}>{x.company}</button>)}
      </div>
      <p style={{ textAlign: "center", color: "var(--text-4)", fontSize: 15, margin: "16px 16px 0" }}>Real outages from public postmortems. Each one spread through a dependency.</p>
    </div>
  )
}
