import { useEffect, useState, type ReactNode } from "react"
import { Link } from "react-router-dom"
import { Moon, Sun } from "lucide-react"

export function Logo({ width = 66, word = true, size = 27 }: { width?: number; word?: boolean; size?: number }) {
  const h = Math.round((width * 32) / 56)
  return (
    <span className="inline-flex items-center gap-2" aria-label="GhostWalk">
      <svg width={width} height={h} viewBox="0 0 56 32" aria-hidden="true">
        <path d="M2 14a11 11 0 0 1 22 0v14l-3.6-2.6-3.7 2.6-3.7-2.6-3.7 2.6-3.6-2.6L2 28z" fill="var(--ink)" />
        <polyline points="7,11 10.5,14 7,17" fill="none" stroke="var(--bg)" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
        <line x1="13" y1="18" x2="24" y2="18" stroke="var(--bg)" strokeWidth="2.2" strokeLinecap="round" />
        <line x1="24" y1="18" x2="36" y2="18" stroke="var(--ink)" strokeWidth="2.2" strokeLinecap="round" />
        <circle cx="38.5" cy="18" r="2.6" fill="var(--ink)" />
        <line x1="41" y1="16" x2="50" y2="9" stroke="var(--accent)" strokeWidth="1.8" strokeDasharray="2.5 2.5" />
        <circle cx="51.5" cy="8" r="2.4" fill="none" stroke="var(--accent)" strokeWidth="1.6" />
      </svg>
      {word && (
        <span className="mono" style={{ fontWeight: 600, fontSize: size }}>
          ghost<span style={{ color: "var(--accent)" }}>walk</span>
        </span>
      )}
    </span>
  )
}

export function useTheme() {
  const [dark, setDark] = useState(() => document.documentElement.classList.contains("dark"))
  const toggle = () => {
    const next = !dark
    document.documentElement.classList.toggle("dark", next)
    try { localStorage.setItem("gw-theme", next ? "dark" : "light") } catch { /* private mode */ }
    setDark(next)
  }
  return { dark, toggle }
}

export function ThemeToggle() {
  const { dark, toggle } = useTheme()
  return (
    <button className="btn btn-glass" style={{ width: 40, padding: 0 }} onClick={toggle} aria-label={dark ? "Switch to light mode" : "Switch to dark mode"}>
      {dark ? <Sun size={18} /> : <Moon size={18} />}
    </button>
  )
}

export function Btn({ to, href, variant = "primary", children, onClick, disabled, className = "", type }: {
  to?: string; href?: string; variant?: "primary" | "glass"; children: ReactNode; onClick?: () => void; disabled?: boolean; className?: string; type?: "button" | "submit"
}) {
  const cls = `btn btn-${variant} ${className}`
  if (to) return <Link to={to} className={cls}>{children}</Link>
  if (href) return <a href={href} className={cls}>{children}</a>
  return <button type={type ?? "button"} className={cls} onClick={onClick} disabled={disabled} style={disabled ? { opacity: 0.55, cursor: "default" } : undefined}>{children}</button>
}

/** Loads something once, exposes error and reload. */
export function useLoad<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [tick, setTick] = useState(0)
  useEffect(() => {
    let live = true
    fn().then((d) => live && (setData(d), setError(null))).catch((e) => live && setError(String(e.message ?? e)))
    return () => { live = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick])
  return { data, error, reload: () => setTick((t) => t + 1) }
}

export const Muted = ({ children }: { children: ReactNode }) => <span style={{ color: "var(--text-4)" }}>{children}</span>
export const Err = ({ children }: { children: ReactNode }) => (
  <div role="alert" className="card" style={{ padding: 16, color: "var(--amber)", fontSize: 14 }}>{children}</div>
)
export const KIND_COLOR: Record<string, string> = { edge: "var(--g-edge)", service: "var(--g-service)", data: "var(--g-data)", infra: "var(--g-infra)" }
