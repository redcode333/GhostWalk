import type { ReactNode } from "react"

/** Pieces shared by the dashboard pages and the landing page's "Inside GhostWalk" stack. Same components, same look. */
export const SYM: Record<string, string> = { "+": "var(--accent-text)", "~": "var(--amber)", "=": "var(--text-3)", "−": "#D9534F" }

export function RankList({ ranking, hover, onHover, max = 3 }: {
  ranking: { id: number; name: string; confidence: number }[]; hover?: number | null; onHover?: (id: number | null) => void; max?: number
}) {
  return (
    <div role="list" aria-label="Ranked root causes">
      {ranking.slice(0, max).map((r, i) => (
        <div key={r.id} role="listitem" tabIndex={onHover ? 0 : undefined} onMouseEnter={() => onHover?.(r.id)} onMouseLeave={() => onHover?.(null)} onFocus={() => onHover?.(r.id)} onBlur={() => onHover?.(null)}
          className="mono" style={{ display: "grid", gridTemplateColumns: "20px minmax(0,1fr) 52px", gap: 8, alignItems: "center", fontSize: 14, padding: "6px 8px", margin: "0 -8px", borderRadius: 8,
            background: hover === r.id ? "rgba(var(--lrgb), .06)" : "transparent", cursor: onHover ? "default" : undefined, transition: "background-color .15s" }}>
          <span style={{ color: "var(--text-4)" }}>{i + 1}</span>
          <span style={{ display: "flex", flexDirection: "column", gap: 4, minWidth: 0 }}>
            <span style={{ color: i === 0 ? "var(--accent-text)" : "var(--text-2)", overflow: "hidden", textOverflow: "ellipsis" }}>{r.name}</span>
            <span aria-hidden="true" style={{ height: 4, borderRadius: 2, background: "var(--muted)" }}>
              <span style={{ display: "block", height: "100%", width: `${Math.max(2, r.confidence * 100)}%`, borderRadius: 2, background: i === 0 ? "var(--accent)" : "var(--text-4)", transition: "width .4s" }} />
            </span>
          </span>
          <span style={{ textAlign: "right" }}>{r.confidence.toFixed(2)}</span>
        </div>
      ))}
    </div>
  )
}

export type ChangeRow = { index: number; symbol: string; text: string; detail: string; apply?: boolean }

/** Proposed graph changes. `action` renders per-row controls (Reject in Learn, Apply in the landing demo). */
export function ChangeRows({ rows, dimmed, action }: { rows: ChangeRow[]; dimmed?: Set<number>; action: (r: ChangeRow) => ReactNode }) {
  return (
    <div style={{ display: "flex", flexDirection: "column" }}>
      {rows.map((r) => (
        <div key={r.index} className="mono" style={{ display: "grid", gridTemplateColumns: "20px minmax(0,1fr) auto 76px", gap: 12, alignItems: "center", padding: "10px 0", borderTop: "1px solid var(--line)",
          fontSize: 14, opacity: dimmed?.has(r.index) ? 0.45 : 1 }}>
          <span style={{ color: SYM[r.symbol] }}>{r.symbol}</span>
          <span style={{ textDecoration: dimmed?.has(r.index) ? "line-through" : undefined, overflow: "hidden", textOverflow: "ellipsis" }}>{r.text}</span>
          <span style={{ color: "var(--text-4)", fontSize: 13 }}>{r.detail}</span>
          <span style={{ textAlign: "right" }}>{action(r)}</span>
        </div>
      ))}
    </div>
  )
}

export function LearnedList({ edges, name }: { edges: { u: number; v: number; w: number; confirmations?: number; from?: number }[]; name: (id: number) => string | undefined }) {
  return (
    <div>
      {edges.map((e, i) => (
        <div key={`${e.u}-${e.v}`} style={{ padding: "10px 0", borderTop: i ? "1px solid var(--line)" : undefined }}>
          <div className="mono" style={{ fontSize: 13, display: "flex", gap: 8 }}>
            <span style={{ color: "var(--accent-text)" }}>{name(e.u)} ⇢ {name(e.v)}</span>
            <span style={{ marginLeft: "auto", color: (e.confirmations ?? 0) >= 2 ? "var(--ok)" : "var(--text-4)" }}>{(e.confirmations ?? 0) >= 2 ? "confirmed" : "tentative"}</span>
          </div>
          <div className="mono" style={{ fontSize: 12, color: "var(--text-4)" }}>w {e.w.toFixed(2)}{e.from != null ? ` · revision ${e.from}` : ""}</div>
        </div>
      ))}
    </div>
  )
}
