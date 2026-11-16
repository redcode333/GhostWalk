import { useEffect, useRef } from "react"

const TRAIL = ["41,16,43,14.5", "45,12.9,46.9,11.4", "48.9,9.9,50,9"]   // the dotted trail: three steps of a walk

/** The GhostWalk mark. The sequence (about 1.6 s) plays on mount, and again on hover or focus of the enclosing link (not mid-play).
 *  `once`: play only the first time per session (the app sidebar). Reduced motion: the static final frame. Styles: .lg-* in styles.css. */
export function Logo({ width = 66, word = true, size = 27, once = false }: { width?: number; word?: boolean; size?: number; once?: boolean }) {
  const ref = useRef<HTMLSpanElement>(null)
  useEffect(() => {
    const el = ref.current!, a = el.closest("a")
    let until = 0
    const play = () => {
      if (Date.now() < until) return
      until = Date.now() + 1700
      el.classList.remove("lg-on"); void el.getBoundingClientRect(); el.classList.add("lg-on")
    }
    let seen = false
    try { seen = once && !!sessionStorage.getItem("gw-logo"); if (once) sessionStorage.setItem("gw-logo", "1") } catch { /* storage blocked: just play */ }
    if (!seen) play()
    a?.addEventListener("mouseenter", play); a?.addEventListener("focus", play)
    return () => { a?.removeEventListener("mouseenter", play); a?.removeEventListener("focus", play) }
  }, [once])
  return (
    <span ref={ref} className="inline-flex items-center gap-2" style={{ color: "var(--ink)" }}>
      <svg width={width} height={Math.round((width * 32) / 56)} viewBox="0 0 56 32" aria-hidden="true">
        <g className="lg-g">
          <path d="M2 14a11 11 0 0 1 22 0v14l-3.6-2.6-3.7 2.6-3.7-2.6-3.7 2.6-3.6-2.6L2 28z" fill="currentColor" />
          <g className="lg-b"><g className="lg-i" fill="none" stroke="var(--bg)" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="7,11 10.5,14 7,17" /><line x1="13" y1="18" x2="19" y2="18" />
          </g></g>
        </g>
        <line className="lg-e" x1="24" y1="18" x2="36" y2="18" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
        <circle className="lg-n" cx="38.5" cy="18" r="2.6" fill="currentColor" />
        {TRAIL.map((s, i) => { const [a, b, c, d] = s.split(","); return <line key={s} className="lg-t" x1={a} y1={b} x2={c} y2={d} stroke="var(--accent)" strokeWidth="1.8" strokeLinecap="round" style={{ animationDelay: `${760 + i * 80}ms` }} /> })}
        <circle className="lg-f" cx="51.5" cy="8" r="2.4" fill="var(--accent)" />
        <circle className="lg-r" cx="51.5" cy="8" r="2.4" fill="none" stroke="var(--accent)" strokeWidth="1.2" />
      </svg>
      {word && <span className="mono" style={{ fontWeight: 600, fontSize: size }}>ghost<span className="lg-w" style={{ color: "var(--accent)" }}>walk</span></span>}
    </span>
  )
}
