import { useEffect, useRef, useState } from "react"
import { NavLink, Outlet, useNavigate } from "react-router-dom"
import { AlertTriangle, BookOpen, LineChart, Network, Rocket, Settings } from "lucide-react"
import { Btn, Logo, useLoad } from "./common"
import { api } from "@/lib/api"

const NAV = [
  { to: "/app/incidents", label: "Incidents", icon: AlertTriangle },
  { to: "/app/map", label: "Map", icon: Network },
  { to: "/app/learn", label: "Learn", icon: BookOpen },
  { to: "/app/proof", label: "Proof", icon: LineChart },
  { to: "/app/onboarding", label: "Set up", icon: Rocket },
  { to: "/app/settings", label: "Settings", icon: Settings },
]

/** The dashboard is always dark. */
export function AppShell() {
  const nav = useNavigate()
  const { data: s } = useLoad(() => api("/api/summary"), [])
  const input = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)

  useEffect(() => {
    const el = document.documentElement
    const had = el.classList.contains("dark")
    el.classList.add("dark")
    const onKey = (e: KeyboardEvent) => { if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); input.current?.focus() } }
    window.addEventListener("keydown", onKey)
    return () => { window.removeEventListener("keydown", onKey); if (!had) el.classList.remove("dark") }
  }, [])

  const ask = async (q: string) => {
    const t = q.trim().replace(/^why\s+/i, "")
    if (!t) return
    setMsg(null)
    if (/^inc-\d+$/i.test(t)) return nav(`/app/incidents/${t.toUpperCase()}`)
    const rows = await api<any[]>("/api/incidents")
    const hit = rows.find((r) => r.symptom.toLowerCase().startsWith(t.toLowerCase()) || r.root === t)
    if (hit) nav(`/app/incidents/${hit.id}`)
    else setMsg(`No incident for “${t}”. Try an incident id or a service that alerted.`)
  }
  const trigger = async () => {
    setBusy(true)
    try { const r = await api("/api/incidents/trigger", { method: "POST" }); nav(`/app/incidents/${r.id}`) } finally { setBusy(false) }
  }

  return (
    <div className="app dark" style={{ background: "var(--bg)", color: "var(--ink)", minHeight: "100vh", display: "flex", flexWrap: "wrap" }}>
      <aside style={{ flex: "1 1 220px", maxWidth: 240, borderRight: "1px solid var(--line)", padding: "16px 12px", display: "flex", flexDirection: "column", gap: 4, boxSizing: "border-box" }}>
        <a href="/" aria-label="GhostWalk home" style={{ padding: "6px 10px 18px" }}><Logo width={36} size={16} /></a>
        <nav aria-label="App" style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          {NAV.map(({ to, label, icon: I }) => (
            <NavLink key={to} to={to} className={({ isActive }) => `side${isActive ? " on" : ""}`}><I size={16} strokeWidth={1.8} />{label}</NavLink>
          ))}
        </nav>
        <div style={{ marginTop: "auto", padding: "12px 10px", fontSize: 12, color: "var(--text-4)", display: "flex", flexDirection: "column", gap: 4 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span style={{ width: 6, height: 6, borderRadius: 99, background: "var(--ok)" }} />{s?.store?.label ?? "…"}
          </div>
          <div className="mono">{s ? `${s.workspace} · ${s.services} services` : ""}</div>
        </div>
      </aside>
      <div style={{ flex: "999 1 560px", minWidth: 0, display: "flex", flexDirection: "column" }}>
        <header style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 12, padding: "12px 24px", borderBottom: "1px solid var(--line)" }}>
          <label htmlFor="cmd" className="sr-only">Ask GhostWalk</label>
          <form onSubmit={(e) => { e.preventDefault(); ask(input.current?.value ?? "") }}
            style={{ flex: "1 1 320px", maxWidth: 520, display: "flex", alignItems: "center", gap: 8, background: "var(--surface-2)", border: "1px solid var(--line)", borderRadius: 12, padding: "0 10px", minHeight: 36 }}>
            <span className="mono" style={{ color: "var(--accent-text)", fontSize: 13 }}>&gt;_</span>
            <input id="cmd" ref={input} className="mono" placeholder="why checkout-api" style={{ flex: 1, minWidth: 0, background: "transparent", border: 0, outline: "none", color: "var(--ink)", fontSize: 13 }} />
            <span className="kbd">⌘</span><span className="kbd">K</span>
          </form>
          <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
            <Btn to="/app/learn" variant="glass">Write postmortem</Btn>
            <Btn onClick={trigger} disabled={busy}>Trigger outage</Btn>
          </div>
          {msg && <div role="status" style={{ flexBasis: "100%", fontSize: 13, color: "var(--amber)" }}>{msg}</div>}
        </header>
        <Outlet />
      </div>
    </div>
  )
}

export const Page = ({ children, max = 1180 }: { children: React.ReactNode; max?: number }) => (
  <main style={{ padding: "28px 24px", display: "flex", flexDirection: "column", gap: 22, maxWidth: max, width: "100%", boxSizing: "border-box" }}>{children}</main>
)
export const H1 = ({ title, sub, right }: { title: string; sub?: string; right?: React.ReactNode }) => (
  <div style={{ display: "flex", flexWrap: "wrap", alignItems: "flex-end", gap: 16 }}>
    <div>
      <h1 style={{ margin: 0, fontSize: 26, fontWeight: 600 }}>{title}</h1>
      {sub && <p style={{ margin: "4px 0 0", color: "var(--text-3)", fontSize: 15 }}>{sub}</p>}
    </div>
    {right && <div style={{ marginLeft: "auto" }}>{right}</div>}
  </div>
)
