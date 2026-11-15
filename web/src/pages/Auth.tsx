import { createContext, useContext, useEffect, useState, type ReactNode } from "react"
import { Link, Navigate } from "react-router-dom"
import { ClerkProvider, SignIn, SignUp, useAuth } from "@clerk/react"
import { api } from "@/lib/api"
import { Btn, Logo } from "@/components/common"

type Cfg = { auth_mode: "none" | "clerk"; clerk_publishable_key: string | null }
const Ctx = createContext<Cfg | null>(null)
export const useCfg = () => useContext(Ctx)

/** Loads /api/config. AUTH_MODE=none opens the demo workspace; AUTH_MODE=clerk wraps the app in Clerk. */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [cfg, setCfg] = useState<Cfg | null>(null)
  useEffect(() => { api<Cfg>("/api/config").then(setCfg).catch(() => setCfg({ auth_mode: "none", clerk_publishable_key: null })) }, [])
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
  return cfg?.auth_mode === "clerk" ? <ClerkGate>{children}</ClerkGate> : <>{children}</>
}

// Clerk appearance (spec): colorPrimary = --ink, colorBackground = --surface, borderRadius 12px, Geist.
const appearance = { variables: { colorPrimary: "var(--ink)", colorBackground: "var(--surface)", colorText: "var(--ink)", borderRadius: "12px", fontFamily: "Geist, sans-serif" } }

const BULLETS = ["Connect alerts with one webhook", "Every postmortem teaches the graph", "Upgrade only when you pass 25 services"]

function Side({ headline }: { headline: string }) {
  return (
    <aside style={{ flex: "1 1 420px", background: "var(--surface-2)", borderLeft: "1px solid var(--line)", padding: 48, display: "flex", flexDirection: "column", justifyContent: "center", gap: 24 }}>
      <h2 style={{ margin: 0, fontSize: 34, lineHeight: 1.1, letterSpacing: "-0.03em", fontWeight: 600, maxWidth: 420 }}>{headline}</h2>
      <div className="card" style={{ padding: 18, maxWidth: 420 }}>
        <div className="mono" style={{ fontSize: 13, color: "var(--text-4)" }}>INC-1042</div>
        <div style={{ fontSize: 15 }}>checkout-api 5xx · 14 alerts</div>
        <div className="mono" style={{ display: "flex", gap: 10, marginTop: 10, fontSize: 14 }}>
          <span style={{ color: "var(--text-4)" }}>Root cause</span><span style={{ color: "var(--accent-text)" }}>config-svc</span><span style={{ marginLeft: "auto" }}>38 ms</span>
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
    <div style={{ minHeight: "100vh", display: "flex", flexWrap: "wrap", background: "var(--bg)" }}>
      <main style={{ flex: "1 1 460px", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 24, padding: 32 }}>
        <Link to="/" aria-label="GhostWalk home"><Logo width={44} size={22} /></Link>
        {children}
      </main>
      <Side headline={headline} />
    </div>
  )
}

function NoAuth({ title, sub }: { title: string; sub: string }) {
  return (
    <div className="card" style={{ width: "min(420px, 100%)", padding: 28, display: "flex", flexDirection: "column", gap: 14 }}>
      <h1 style={{ margin: 0, fontSize: 26, fontWeight: 600 }}>{title}</h1>
      <p style={{ margin: 0, color: "var(--text-3)", fontSize: 15 }}>{sub}</p>
      <p style={{ margin: 0, color: "var(--text-3)", fontSize: 14 }}>Sign-in is off on this server (<span className="mono">AUTH_MODE=none</span>), so there is no account to create. It opens the demo workspace.</p>
      <Btn to="/app/incidents">Open the demo workspace</Btn>
    </div>
  )
}

export function SignInPage() {
  const cfg = useCfg()
  const clerk = cfg?.auth_mode === "clerk" && cfg.clerk_publishable_key
  return (
    <Shell headline="The pager says checkout. The graph says config-svc.">
      {clerk ? <SignIn routing="path" path="/signin" signUpUrl="/signup" forceRedirectUrl="/app/incidents" appearance={appearance} /> : <NoAuth title="Welcome back" sub="Sign in to your workspace." />}
      {!clerk && <div style={{ fontSize: 14, color: "var(--text-3)" }}>New to GhostWalk? <Link to="/signup" style={{ color: "var(--accent-text)" }}>Create a free account</Link></div>}
    </Shell>
  )
}

export function SignUpPage() {
  const cfg = useCfg()
  const clerk = cfg?.auth_mode === "clerk" && cfg.clerk_publishable_key
  return (
    <Shell headline="Next time it breaks, you'll know where in milliseconds.">
      {clerk ? <SignUp routing="path" path="/signup" signInUrl="/signin" forceRedirectUrl="/app/onboarding" appearance={appearance} /> : <NoAuth title="Create your account" sub="Free for up to 25 services. No card needed." />}
      {!clerk && <div style={{ fontSize: 14, color: "var(--text-3)" }}>Already have an account? <Link to="/signin" style={{ color: "var(--accent-text)" }}>Sign in</Link></div>}
    </Shell>
  )
}
