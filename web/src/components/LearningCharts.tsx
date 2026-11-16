import type { Results } from "@/lib/results"

/* Two charts from results.json (learning_curve.cumulative_gain and learning_curve.cumulative_acc). Colours come from the site's CSS variables, so light and dark both work.
   Nothing is computed here beyond layout: the series, bands and totals are stored. */

type G = { n: number; gain: number; lo: number; hi: number }
type Cum = { n: number; ac1: number; lo: number; hi: number }

const MONO = "Geist Mono, ui-monospace, monospace"
const pts = (v: number, d = 1) => `${v >= 0 ? "+" : "−"}${Math.abs(v * 100).toFixed(d)} pts`

/** Spread end labels so two close values do not sit on top of each other. */
function spread(items: { y: number; label: string; color: string }[], gap: number) {
  const s = [...items].sort((a, b) => a.y - b.y)
  for (let i = 1; i < s.length; i++) if (s[i].y - s[i - 1].y < gap) s[i].y = s[i - 1].y + gap
  return s
}

function niceStep(span: number) {
  for (const s of [0.01, 0.02, 0.025, 0.05, 0.1]) if (span / s <= 7) return s
  return 0.1
}

export function PairedGainChart({ r, mini = false }: { r: Results | null; mini?: boolean }) {
  const cg = (r as any)?.learning_curve?.cumulative_gain as { series: Record<string, G[]>; band: string; x_label: string; y_label: string } | undefined
  const gw = cg?.series?.ghostwalk_minus_learning_off, pl = cg?.series?.placebo_minus_learning_off
  if (!cg || !gw || !pl) return <p style={{ margin: 0, fontSize: 14, color: "var(--text-4)" }}>The cumulative gain appears once results.json has learning_curve.cumulative_gain.</p>
  const W = mini ? 440 : 780, H = mini ? 190 : 340, L = mini ? 40 : 56, R = mini ? 74 : 92, T = 14, B = mini ? 30 : 48
  const maxN = Math.max(...gw.map((p) => p.n)), minN = Math.min(...gw.map((p) => p.n))
  const all = [...gw, ...pl].flatMap((p) => [p.gain, p.lo, p.hi])
  const step = niceStep(Math.max(...all) - Math.min(...all, 0))
  const lo = Math.floor(Math.min(...all, 0) / step) * step, hi = Math.ceil(Math.max(...all, 0) / step) * step
  const X = (n: number) => L + ((n - minN) / (maxN - minN)) * (W - L - R)
  const Y = (v: number) => T + ((hi - v) / (hi - lo)) * (H - T - B)
  const line = (s: G[]) => s.map((p, i) => `${i ? "L" : "M"}${X(p.n).toFixed(1)},${Y(p.gain).toFixed(1)}`).join(" ")
  const bandPath = (s: G[]) => `${s.map((p, i) => `${i ? "L" : "M"}${X(p.n).toFixed(1)},${Y(p.hi).toFixed(1)}`).join(" ")} ${[...s].reverse().map((p) => `L${X(p.n).toFixed(1)},${Y(p.lo).toFixed(1)}`).join(" ")} Z`
  const ticks: number[] = []
  for (let v = lo; v <= hi + 1e-9; v += step) ticks.push(Math.round(v * 1000) / 1000)
  const last = (s: G[]) => s[s.length - 1]
  const ends = spread([{ y: Y(last(gw).gain), label: pts(last(gw).gain), color: "var(--accent-text)" }, { y: Y(last(pl).gain), label: pts(last(pl).gain), color: "var(--amber-text)" }], 15)
  const xt = mini ? [10, 30, 60] : [10, 20, 30, 40, 50, 60]
  const m = (r as any)?.meta
  const sub = m ? `Cumulative over incidents 1..n. ${m.companies} held-out companies, ${Number(m.incidents).toLocaleString("en-US")} incidents. Band = 95% bootstrap by company.` : ""
  return (
    <figure style={{ margin: 0 }}>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label={`What learning adds: cumulative accuracy gain over no learning by incidents seen per company. GhostWalk ${pts(last(gw).gain)}, placebo postmortems ${pts(last(pl).gain)}.`} style={{ display: "block" }}>
        {ticks.map((v) => (
          <g key={v}>
            <line x1={L} x2={W - R} y1={Y(v)} y2={Y(v)} stroke={Math.abs(v) < 1e-9 ? "var(--text-3)" : "var(--line)"} strokeWidth={Math.abs(v) < 1e-9 ? 1.3 : 1} />
            <text x={L - 8} y={Y(v) + 4} textAnchor="end" fontSize={mini ? 10 : 11} fill="var(--text-4)" fontFamily={MONO}>{v === 0 ? "0" : `${v > 0 ? "+" : "−"}${Math.abs(v * 100).toFixed(0)}`}</text>
          </g>))}
        {xt.map((n) => <text key={n} x={X(n)} y={H - B + 17} textAnchor="middle" fontSize={mini ? 10 : 11} fill="var(--text-4)" fontFamily={MONO}>{n}</text>)}
        {!mini && <text x={(L + W - R) / 2} y={H - 6} textAnchor="middle" fontSize="12" fill="var(--text-3)">{cg.x_label}</text>}
        {!mini && <text transform={`translate(14 ${(T + H - B) / 2}) rotate(-90)`} textAnchor="middle" fontSize="12" fill="var(--text-3)">{cg.y_label}</text>}
        <path d={bandPath(pl)} fill="var(--amber)" opacity="0.12" />
        <path d={bandPath(gw)} fill="var(--accent)" opacity="0.16" />
        <path d={line(pl)} fill="none" stroke="var(--amber)" strokeWidth={mini ? 2 : 2.4} strokeLinecap="round" strokeDasharray="1 6" />
        <path d={line(gw)} fill="none" stroke="var(--accent)" strokeWidth={mini ? 2.6 : 3.2} strokeLinecap="round" strokeLinejoin="round" />
        {ends.map((e) => <text key={e.label + e.color} x={W - R + 8} y={e.y + 4} fontSize={mini ? 12 : 13.5} fontWeight="600" fill={e.color} fontFamily={MONO}>{e.label}</text>)}
      </svg>
      {mini && (
        <figcaption className="mono" style={{ marginTop: 4, display: "flex", flexWrap: "wrap", gap: "4px 14px", fontSize: 11.5, color: "var(--text-3)" }}>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}><svg width="18" height="6" aria-hidden="true"><line x1="1" x2="17" y1="3" y2="3" stroke="var(--accent)" strokeWidth="2.6" strokeLinecap="round" /></svg>real postmortems</span>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}><svg width="18" height="6" aria-hidden="true"><line x1="1" x2="17" y1="3" y2="3" stroke="var(--amber)" strokeWidth="2" strokeLinecap="round" strokeDasharray="1 5" /></svg>random postmortems</span>
          <span>cumulative gain over no learning, pts</span>
        </figcaption>)}
      {!mini && (
        <figcaption style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 6 }}>
          <div className="mono" style={{ display: "flex", flexWrap: "wrap", gap: "6px 20px", fontSize: 12.5, color: "var(--text-3)" }}>
            <span style={{ display: "inline-flex", alignItems: "center", gap: 7 }}><svg width="26" height="8" aria-hidden="true"><line x1="1" x2="25" y1="4" y2="4" stroke="var(--accent)" strokeWidth="3.2" strokeLinecap="round" /></svg>GhostWalk − learning off</span>
            <span style={{ display: "inline-flex", alignItems: "center", gap: 7 }}><svg width="26" height="8" aria-hidden="true"><line x1="1" x2="25" y1="4" y2="4" stroke="var(--amber)" strokeWidth="2.4" strokeLinecap="round" strokeDasharray="1 6" /></svg>Placebo postmortems − learning off</span>
          </div>
          <div style={{ fontSize: 12.5, color: "var(--text-4)" }}>{sub}</div>
        </figcaption>)}
    </figure>
  )
}

export function CumulativeChart({ r }: { r: Results | null }) {
  const cu = (r as any)?.learning_curve?.cumulative_acc as { series: Record<string, Cum[]>; band: string } | undefined
  if (!cu?.series?.ghostwalk) return <p style={{ margin: 0, fontSize: 14, color: "var(--text-4)" }}>The cumulative curve appears once results.json has learning_curve.cumulative_acc.</p>
  const W = 820, H = 320, L = 56, R = 150, T = 14, B = 48
  const series: [string, string, string, number, string | undefined, string][] = [
    ["ghostwalk", "GhostWalk", "var(--accent)", 3.2, undefined, "var(--accent-text)"], ["learning_off", "Learning off", "var(--text-3)", 2.2, undefined, "var(--text-3)"],
    ["placebo", "Placebo postmortems", "var(--amber)", 2.4, "1 6", "var(--amber-text)"], ["oracle", "Perfect map", "var(--ink)", 1.8, "6 5", "var(--ink)"]]
  const vals = series.flatMap(([k]) => cu.series[k].map((p) => p.ac1))
  const lo = Math.floor((Math.min(...vals) - 0.02) * 20) / 20, hi = Math.min(1, Math.ceil((Math.max(...vals) + 0.02) * 20) / 20)
  const maxN = Math.max(...cu.series.ghostwalk.map((p) => p.n))
  const minN = Math.min(...cu.series.ghostwalk.map((p) => p.n))
  const X = (n: number) => L + ((n - minN) / (maxN - minN)) * (W - L - R)
  const Y = (v: number) => T + ((hi - v) / (hi - lo)) * (H - T - B)
  const path = (k: string) => cu.series[k].map((p, i) => `${i ? "L" : "M"}${X(p.n).toFixed(1)},${Y(p.ac1).toFixed(1)}`).join(" ")
  const ticks: number[] = []
  for (let v = lo; v <= hi + 1e-9; v += 0.05) ticks.push(Math.round(v * 100) / 100)
  const short: Record<string, string> = { ghostwalk: "GhostWalk", learning_off: "Learning off", placebo: "Placebo", oracle: "Perfect map" }
  const ends = spread(series.map(([k, , , , , tc]) => ({ y: Y(cu.series[k][cu.series[k].length - 1].ac1), label: `${short[k]} ${(cu.series[k][cu.series[k].length - 1].ac1 * 100).toFixed(1)}%`, color: tc })), 15)
  return (
    <figure style={{ margin: 0 }}>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="Cumulative top-1 accuracy up to each incident number for GhostWalk, learning off, placebo postmortems and the perfect map" style={{ display: "block" }}>
        {ticks.map((v) => <g key={v}><line x1={L} x2={W - R} y1={Y(v)} y2={Y(v)} stroke="var(--line)" /><text x={L - 8} y={Y(v) + 4} textAnchor="end" fontSize="11" fill="var(--text-4)" fontFamily={MONO}>{Math.round(v * 100)}%</text></g>)}
        {cu.series.ghostwalk.filter((p) => p.n % 10 === 0).map((p) => <text key={p.n} x={X(p.n)} y={H - B + 17} textAnchor="middle" fontSize="11" fill="var(--text-4)" fontFamily={MONO}>{p.n}</text>)}
        <text x={(L + W - R) / 2} y={H - 6} textAnchor="middle" fontSize="12" fill="var(--text-3)">Incidents seen per company</text>
        <text transform={`translate(14 ${(T + H - B) / 2}) rotate(-90)`} textAnchor="middle" fontSize="12" fill="var(--text-3)">Cumulative AC@1</text>
        {series.map(([k, , c, w, d]) => <path key={k} d={path(k)} fill="none" stroke={c} strokeWidth={w} strokeLinecap="round" strokeLinejoin="round" strokeDasharray={d} />)}
        {ends.map((e) => <text key={e.label} x={W - R + 8} y={e.y + 4} fontSize="12.5" fontWeight="600" fill={e.color} fontFamily={MONO}>{e.label}</text>)}
      </svg>
      <figcaption className="mono" style={{ marginTop: 8, display: "flex", flexWrap: "wrap", gap: "6px 18px", fontSize: 12.5, color: "var(--text-3)" }}>
        {series.map(([k, name, c, w, d]) => <span key={k} style={{ display: "inline-flex", alignItems: "center", gap: 7 }}><svg width="26" height="8" aria-hidden="true"><line x1="1" x2="25" y1="4" y2="4" stroke={c} strokeWidth={w} strokeLinecap="round" strokeDasharray={d} /></svg>{name}</span>)}
      </figcaption>
    </figure>
  )
}
