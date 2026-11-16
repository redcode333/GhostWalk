import { createContext, useContext, useEffect, useState, type ReactNode } from "react"
import { Link, Navigate, useLocation } from "react-router-dom"
import { ClerkProvider, SignIn, SignUp, useAuth } from "@clerk/react"
import { api, demoMode, setDemoMode } from "@/lib/api"
import { Btn, Logo, ThemeToggle, useLoad } from "@/components/common"
import { loadResults, verdictLatency } from "@/lib/results"

type Cfg = { auth_mode: "none" | "clerk"; clerk_publishable_key: string | null }
const Ctx = createContext<Cfg | null>(null)
export const useCfg = () => useContext(Ctx)

/** Loads /api/config. AUTH_MODE=none opens the demo workspace; AUTH_MODE=clerk wraps the app in Clerk. */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [cfg, setCfg] = useState<Cfg | null>(null)
  useEffect(() => { api<Cfg>("/api/config").then((c) => setCfg({ ...c, clerk_publishable_key: (import.meta as any).env?.VITE_CLERK_PUBLISHABLE_KEY || c.clerk_publishable_key })).catch(() => setCfg({ auth_mode: "none", clerk_publishable_key: null })) }, [])
  if (!cfg) return null
  if (cfg.auth_mode === "clerk" && cfg.clerk_publishable_key) {
    return <ClerkProvider publishableKey={cfg.clerk_publishable_key}><Ctx.Provider value={cfg}><TokenBridge>{children}</TokenBridge></Ctx.Provider></ClerkProvider>
  }
  return <Ctx.Provider value={cfg}>{children}</Ctx.Provider>
}

function TokenBridge({ children }: { children: ReactNode }) {
  const { getToken } = useAuth()
  ;(window as any).__gwToken = () => getToken()
  return <>{children}</>
}

function ClerkGate({ children }: { children: ReactNode }) {
  const { isLoaded, isSignedIn } = useAuth()
  if (!isLoaded) return null
  return isSignedIn ? <>{children}</> : <Navigate to="/signin" replace />
}

export function RequireAuth({ children }: { children: ReactNode }) {
  const cfg = useCfg()
  if (demoMode()) return <>{children}</>                                   // /demo is public: no sign-in
  return cfg?.auth_mode === "clerk" ? <ClerkGate>{children}</ClerkGate> : <>{children}</>
}

// Clerk appearance (spec): colorPrimary = --ink, colorBackground = --surface, borderRadius 12px, Geist.
const appearance = { variables: { colorPrimary: "var(--ink)", colorBackground: "var(--surface)", colorText: "var(--ink)", borderRadius: "12px", fontFamily: "Geist, sans-serif" } }

const BULLETS = ["Connect alerts with one webhook", "Every postmortem teaches the graph", "Free and open source, MIT licensed"]

function Side({ headline }: { headline: string }) {
  const { data: r } = useLoad(loadResults, [])
  const lat = verdictLatency(r)
  return (
    <aside className="hide-sm" style={{ flex: "1 1 min(420px, 100%)", position: "relative", overflow: "hidden", padding: 48, display: "flex", flexDirection: "column", justifyContent: "center", gap: 24, borderLeft: "1px solid var(--line)",
      background: "radial-gradient(60% 50% at 20% 10%, rgba(var(--lrgb), 0) 0, transparent 100%), radial-gradient(70% 60% at 85% 0%, color-mix(in srgb, var(--accent) 22%, transparent), transparent 70%), radial-gradient(60% 50% at 0% 100%, color-mix(in srgb, var(--amber) 16%, transparent), transparent 70%), var(--surface-2)" }}>
      <h2 style={{ margin: 0, fontSize: 34, lineHeight: 1.1, letterSpacing: "-0.03em", fontWeight: 600, maxWidth: 420 }}>{headline}</h2>
      <div className="card" style={{ padding: 18, maxWidth: 420 }}>
        <div className="mono" style={{ fontSize: 13, color: "var(--text-4)" }}>INC-1042</div>
        <div style={{ fontSize: 15 }}>checkout-api 5xx · 14 alerts</div>
        <div className="mono" style={{ display: "flex", gap: 10, marginTop: 10, fontSize: 14 }}>
          <span style={{ color: "var(--text-4)" }}>Root cause</span><span style={{ color: "var(--accent-text)" }}>config-svc</span><span style={{ marginLeft: "auto" }} title={lat?.label}>{lat ? lat.text : ""}</span>
        </div>
        <div className="mono" style={{ fontSize: 13, marginTop: 8 }}>config-svc <span style={{ color: "var(--accent-text)" }}>⇢</span> fraud-check → payments → checkout-api</div>
      </div>
      <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 8, fontSize: 15, color: "var(--text-2)" }}>
        {BULLETS.map((b) => <li key={b}><span style={{ color: "var(--ok)" }}>✓</span>&nbsp; {b}</li>)}
      </ul>
    </aside>
  )
}

function Shell({ children, headline }: { children: ReactNode; headline: string }) {
  return (
    <div style={{ minHeight: "100vh", display: "flex", flexWrap: "wrap", background: "var(--bg)", position: "relative" }}>
      <div style={{ position: "absolute", top: 16, right: 16, zIndex: 5 }}><ThemeToggle /></div>
      <main style={{ flex: "1 1 min(460px, 100%)", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 24, padding: 32 }}>
        <Link to="/" aria-label="GhostWalk home"><Logo width={66} size={27} /></Link>
        {children}
      </main>
      <Side headline={headline} />
    </div>
  )
}

/** AUTH_MODE=none has no accounts: explain the shared workspace and offer an honest demo entry. */
function DemoForm({ up }: { up: boolean }) {
  return (
    <section className="card" aria-labelledby="demo-entry-title" style={{ width: "min(420px, 100%)", padding: 28, display: "flex", flexDirection: "column", gap: 14 }}>
      <div><h1 id="demo-entry-title" style={{ margin: 0, fontSize: 26, fontWeight: 600 }}>{up ? "Explore GhostWalk" : "Open the demo workspace"}</h1>
        <p style={{ margin: "4px 0 0", color: "var(--text-3)", fontSize: 15 }}>This server has sign-in disabled. No account or password is created.</p></div>
      <div role="note" style={{ border: "1px solid var(--line)", borderRadius: 10, padding: 12, fontSize: 13, color: "var(--text-3)" }}>
        <strong style={{ color: "var(--ink)" }}>Shared workspace.</strong> This self-hosted server uses <span className="mono">AUTH_MODE=none</span>; anyone with access to it shares the same workspace and its data. This is not an isolated customer account.
      </div>
      <Btn to="/demo">{up ? "Explore the sample workspace" : "Continue to the workspace"}</Btn>
      <p style={{ margin: 0, fontSize: 12, color: "var(--text-4)" }}>For isolated user workspaces, configure Clerk and set <span className="mono">AUTH_MODE=clerk</span>.</p>
    </section>
  )
}

export function DemoEntry({ to = "/app/incidents" }: { to?: string }) {
  setDemoMode(true)                                                          // /demo and /proof are public: they open the shared sandbox, no sign-in
  return <Navigate to={to + useLocation().hash} replace />
}

export function SignInPage() {
  setDemoMode(false)
  const cfg = useCfg()
  const clerk = cfg?.auth_mode === "clerk" && cfg.clerk_publishable_key
  return (
    <Shell headline="The pager says checkout. The graph says config-svc.">
      {clerk ? <SignIn routing="path" path="/signin" signUpUrl="/signup" forceRedirectUrl="/app/incidents" appearance={appearance} /> : <DemoForm up={false} />}
      <div style={{ fontSize: 14, color: "var(--text-3)" }}>New to GhostWalk? <Link to="/signup" style={{ color: "var(--accent-text)" }}>Create an account</Link></div>
    </Shell>
  )
}

export function SignUpPage() {
  setDemoMode(false)
  const cfg = useCfg()
  const clerk = cfg?.auth_mode === "clerk" && cfg.clerk_publishable_key
  return (
    <Shell headline="Next time it breaks, you'll know where in milliseconds.">
      {clerk ? <SignUp routing="path" path="/signup" signInUrl="/signin" forceRedirectUrl="/app/onboarding" appearance={appearance} /> : <DemoForm up />}
      <div style={{ fontSize: 14, color: "var(--text-3)" }}>Already have an account? <Link to="/signin" style={{ color: "var(--accent-text)" }}>Sign in</Link></div>
    </Shell>
  )
}
