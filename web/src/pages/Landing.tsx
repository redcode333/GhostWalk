import { useEffect, useState, type ReactNode } from "react"
import { Link } from "react-router-dom"
import { ArrowRight, Boxes, GitBranch, HelpCircle, MapPinned, Route, Tag } from "lucide-react"
import { LiquidNavbar } from "@/components/ui/liquid-glass-navbar"
import { OutageGlobe } from "@/components/ui/outage-globe"
import { PairedGainChart } from "@/components/LearningCharts"
import { Btn, Logo, ThemeToggle, useLoad, useTheme } from "@/components/common"
import { Graph, Legend } from "@/components/Graph"
import { InsideGhostWalk } from "@/components/InsideGhostWalk"
import { CLOUDFLARE, OUTAGES, savedM } from "@/data/outages"
import { loadDemo, type Demo } from "@/lib/demo"
import { loadResults, proofStrip, verdictLatency, type Results } from "@/lib/results"

const GITHUB = "https://github.com/redcode333/GhostWalk"
const compact = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}k` : String(n))
const f3 = (x: number) => x.toFixed(3)

const Section = ({ id, children, style }: { id?: string; children: ReactNode; style?: React.CSSProperties }) => (
  <section id={id} style={{ maxWidth: 1240, margin: "0 auto", padding: "88px 24px 0", scrollMarginTop: 90, ...style }}>{children}</section>
)
const H2 = ({ children, sub, eyebrow }: { children: ReactNode; sub?: string; eyebrow?: ReactNode }) => (
  <div style={{ textAlign: "center", marginBottom: 40 }}>
    {eyebrow}
    <h2 style={{ margin: eyebrow ? "10px 0 0" : 0, fontSize: "clamp(30px, 4.4vw, 48px)", lineHeight: 1.08, letterSpacing: "-0.03em", fontWeight: 600 }}>{children}</h2>
    {sub && <p style={{ margin: "12px auto 0", maxWidth: 640, fontSize: 18, color: "var(--text-3)" }}>{sub}</p>}
  </div>
)
const Small = ({ children }: { children: ReactNode }) => <p style={{ margin: 0, fontSize: 15, color: "var(--text-3)" }}>{children}</p>
const Pill = ({ children }: { children: ReactNode }) => <span className="mono" style={{ border: "1px solid var(--line)", borderRadius: 999, padding: "3px 10px", fontSize: 12 }}>{children}</span>

/* ------------------------------------------------------------------ header + hero */
function Header() {
  const { dark } = useTheme()
  const stars = typeof __GH_STARS__ === "number" && __GH_STARS__ > 0 ? __GH_STARS__ : null      // a real count only: never "GitHub · 0"
  const [compactNav, setCompactNav] = useState(false)
  useEffect(() => {
    const mq = window.matchMedia("(max-width: 1100px)")
    const on = () => setCompactNav(mq.matches)
    on()
    mq.addEventListener("change", on)
    return () => mq.removeEventListener("change", on)
  }, [])
  return (
    <header className="site-header" style={{ position: "sticky", top: 0, zIndex: 30, display: "flex", alignItems: "center", gap: 12, padding: "10px 24px", background: "linear-gradient(var(--bg) 40%, transparent)" }}>
      <Link to="/" aria-label="GhostWalk home" style={{ flex: "none", display: "inline-flex" }}>
        <span className="hide-xs"><Logo width={66} /></span>
        <span className="show-xs"><Logo width={66} word={false} /></span>
      </Link>
      <div className="nav-wrap">
        <LiquidNavbar tone={dark ? "dark" : "light"} compact={compactNav} items={[
          { label: "Product", href: "#product", icon: <Boxes size={18} />, fx: "pop" },
          { label: "Outages", href: "#outages", icon: <MapPinned size={18} />, fx: "spin" },
          { label: "How it works", href: "#how", icon: <Route size={18} />, fx: "glow" },
          { label: "Pricing", href: "#pricing", icon: <Tag size={18} />, fx: "pop" },
          { label: "FAQ", href: "#faq", icon: <HelpCircle size={18} />, fx: "wave" },
          { label: stars != null ? `GitHub · ${compact(stars)}` : "GitHub", href: GITHUB, icon: <GitBranch size={18} />, fx: "drop" },
        ]} />
      </div>
      <span style={{ marginLeft: "auto", display: "inline-flex" }}><ThemeToggle /></span>
      <span className="hide-md"><Btn to="/signin" variant="ghost">Sign in</Btn></span>
      <Btn to="/signup">Start free</Btn>
    </header>
  )
}

function Hero() {
  return (
    <div className="hero" style={{ textAlign: "center", padding: "clamp(14px, 3vh, 30px) 24px 0", maxWidth: 1000, margin: "0 auto" }}>
      <span className="btn-glass mono" style={{ display: "inline-flex", alignItems: "center", gap: 8, border: "1px solid var(--line)", borderRadius: 999, padding: "6px 14px", fontSize: 13, color: "var(--text-3)" }}>
        <span style={{ color: "var(--ink)" }}>Open source</span><span style={{ color: "var(--text-4)" }}>·</span>Root cause analysis on HydraDB <ArrowRight size={14} />
      </span>
      <h1 style={{ margin: "clamp(10px, 2vh, 16px) 0 0", fontSize: "clamp(40px, 6vw, 84px)", lineHeight: 1.02, letterSpacing: "-0.04em", fontWeight: 600 }}>The outage is never where the pager says.</h1>
      <p style={{ margin: "clamp(10px, 2vh, 16px) auto 0", maxWidth: 760, fontSize: "clamp(16px, 1.5vw, 20px)", lineHeight: 1.45, color: "var(--text-3)" }}>
        GhostWalk walks your service graph from fourteen alerts to the one broken dependency in milliseconds, and learns the dependencies nobody drew from every postmortem.
      </p>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 12, justifyContent: "center", marginTop: "clamp(14px, 2.6vh, 22px)" }}>
        <Btn to="/signup">Start free</Btn>
        <Btn to="/demo" variant="glass">Watch a live outage <ArrowRight size={16} /></Btn>
      </div>
      <p className="mono" style={{ margin: "clamp(8px, 1.6vh, 14px) 0 0", fontSize: 13, color: "var(--text-4)" }}>Free for 25 services · No card needed · docker compose up</p>
    </div>
  )
}

/* ------------------------------------------------------------------ story */
const BILL = [
  { v: "$250M–$300M", who: "Cloudflare · Nov 2025", by: "Forrester", href: OUTAGES[0].costSource! },
  { v: "$500M–$650M", who: "AWS us-east-1 · Oct 2025, US companies", by: "Parametrix", href: OUTAGES[1].costSource! },
  { v: "$5.4B", who: "CrowdStrike · Jul 2024, Fortune 500 alone", by: "Parametrix", href: OUTAGES[2].costSource! },
]

function Story() {
  const [mins, setMins] = useState(15)
  const saved = savedM(mins)
  const rows = [["11:05", "a ClickHouse access-control change ships"], ["11:20", "core traffic starts failing with 5xx"],
    ["···", "responders suspect a hyper-scale DDoS; an unrelated status-page outage makes it look likelier"],
    ["···", "Turnstile fails, so dashboard logins fail; Workers KV and Access throw errors"], ["14:30", "the bad Bot Management feature file is stopped; core traffic recovers"], ["17:06", "all downstream services restored"]]
  return (
    <Section id="story">
      <H2 eyebrow={<span className="eyebrow">Cloudflare · 18 November 2025</span>} sub="Five services alerted at once. Every one of them traced back to a file nobody thought of as a dependency.">
        The pager said DDoS. The cause was a database permission.
      </H2>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 20 }}>
        <div className="card" style={{ flex: "1 1 min(460px, 100%)", padding: 28 }}>
          <h3 style={{ margin: 0, fontSize: 20 }}>What happened</h3>
          <p style={{ margin: "2px 0 16px", fontSize: 13, color: "var(--text-4)" }}>from Cloudflare's postmortem, UTC</p>
          {rows.map(([t, x], i) => (
            <div key={i} style={{ display: "grid", gridTemplateColumns: "56px 1fr", gap: 12, padding: "8px 0", fontSize: 15 }}>
              <span className="mono" style={{ color: t === "···" ? "var(--text-4)" : "var(--ink)" }}>{t}</span><span style={{ color: "var(--text-2)" }}>{x}</span>
            </div>
          ))}
          <div style={{ display: "flex", gap: 32, margin: "18px 0", flexWrap: "wrap" }}>
            <div><div className="mono" style={{ fontSize: 34, fontWeight: 600 }}>3h 10m</div><div style={{ fontSize: 13, color: "var(--text-4)" }}>core traffic impact</div></div>
            <div><div className="mono" style={{ fontSize: 34, fontWeight: 600 }}>5h 46m</div><div style={{ fontSize: 13, color: "var(--text-4)" }}>until fully resolved</div></div>
          </div>
          <div style={{ border: "1px solid var(--amber)", borderRadius: 14, padding: "14px 16px", marginBottom: 16 }}>
            <div className="mono" style={{ fontSize: 28, fontWeight: 600, color: "var(--amber-text)" }}>$250M–$300M</div>
            <div style={{ fontSize: 14, color: "var(--text-3)" }}>estimated direct and indirect losses (Forrester) · roughly $1.4M for every minute of core impact</div>
          </div>
          <div style={{ display: "flex", gap: 20, flexWrap: "wrap", fontSize: 15 }}>
            <a href="https://blog.cloudflare.com/18-november-2025-outage/" target="_blank" rel="noreferrer" style={{ color: "var(--accent-text)" }}>blog.cloudflare.com/18-november-2025-outage →</a>
            <a href={CLOUDFLARE.techinformed} target="_blank" rel="noreferrer" style={{ color: "var(--accent-text)" }}>techinformed.com on the Forrester estimate →</a>
          </div>
        </div>
        <div className="card" style={{ flex: "1 1 min(460px, 100%)", padding: 28, display: "flex", flexDirection: "column", gap: 14 }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}><h3 style={{ margin: 0, fontSize: 20 }}>How GhostWalk walks it</h3><span className="mono" style={{ fontSize: 12, color: "var(--text-4)" }}>illustrative</span></div>
          <div><div style={{ fontSize: 13, color: "var(--text-4)", marginBottom: 6 }}>Alerts in</div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>{["proxy 5xx", "Turnstile", "dashboard login", "Workers KV", "Access"].map((a) => (
              <span key={a} className="mono" style={{ border: "1.5px solid var(--amber)", borderRadius: 999, padding: "3px 10px", fontSize: 12 }}>{a}</span>))}</div></div>
          <div><div style={{ fontSize: 13, color: "var(--text-4)", marginBottom: 6 }}>Walk upstream</div>
            <div className="mono" style={{ fontSize: 13, display: "flex", flexDirection: "column", gap: 6 }}>
              <span>5 alerting services → core proxy</span>
              <span><span style={{ color: "var(--accent-text)" }}>core proxy ⇢ bot feature file</span> <span style={{ color: "var(--text-4)" }}>learned edge</span></span>
              <span>feature file → ClickHouse <span style={{ color: "var(--text-4)" }}>changed 11:05</span></span></div></div>
          <div style={{ borderTop: "1px solid var(--line)", paddingTop: 14 }}>
            <div style={{ fontSize: 13, color: "var(--text-4)" }}>Verdict</div>
            <div style={{ fontSize: 22, fontWeight: 600, color: "var(--accent-text)" }}>ClickHouse permission change</div>
            <div className="mono" style={{ fontSize: 13 }}>explains 5 of 5</div>
          </div>
          <div style={{ borderTop: "1px solid var(--line)", paddingTop: 14 }}>
            <label htmlFor="mins" style={{ fontSize: 14, color: "var(--text-2)" }}>If the root had been found in <span className="mono" style={{ color: "var(--ink)", fontWeight: 600 }}>{mins} min</span> instead of 3h 10m</label>
            <input id="mins" type="range" min={5} max={180} step={5} value={mins} onChange={(e) => setMins(+e.target.value)} style={{ width: "100%", accentColor: "var(--accent)", margin: "8px 0" }} />
            <div style={{ fontSize: 15 }}>≈ <span className="mono" style={{ color: "var(--amber-text)", fontWeight: 600 }}>${saved.toFixed(0)}M</span> of that estimate wouldn't have happened</div>
            <p style={{ margin: "6px 0 0", fontSize: 12, color: "var(--text-4)" }}>Back-of-envelope: $275M midpoint ÷ 190 min, assuming cost scales with minutes down.</p>
          </div>
          <p style={{ margin: 0, fontSize: 14, color: "var(--text-4)" }}>Assumes the feature-file dependency is in the graph. That's exactly the kind of edge a single earlier postmortem teaches GhostWalk.</p>
        </div>
      </div>
      <h3 style={{ textAlign: "center", fontSize: 22, margin: "48px 0 16px" }}>The bill for one dependency nobody watched</h3>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(260px, 100%), 1fr))", gap: 16 }}>
        {BILL.map((b) => (
          <a key={b.who} href={b.href} target="_blank" rel="noreferrer" className="card" style={{ padding: 22, display: "block" }}>
            <div className="mono" style={{ fontSize: 30, fontWeight: 600, color: "var(--amber-text)" }}>{b.v}</div>
            <div style={{ fontSize: 15, marginTop: 4 }}>{b.who}</div>
            <div className="mono" style={{ fontSize: 12, color: "var(--text-4)", marginTop: 6 }}>estimate by {b.by} · source →</div>
          </a>))}
      </div>
    </Section>
  )
}

/* ------------------------------------------------------------------ bento */
function Tile({ title, children, span = 1 }: { title: string; children?: ReactNode; span?: number }) {
  return (
    <div className="card bento" style={{ padding: 24, display: "flex", flexDirection: "column", gap: 12, gridColumn: `span ${span}` }}>
      <h3 style={{ margin: 0, fontSize: 20 }}>{title}</h3>{children}
    </div>
  )
}

function Bento({ r, d }: { r: Results | null; d: Demo | null }) {
  const p95 = r?.ops?.ghostwalk
  const g = (id: number, name: string, kind: string, tier: number, extra = {}) => ({ id, name, kind, tier, ...extra })
  return (
    <Section id="product">
      <H2 sub="Deterministic, explainable, and fast enough to answer before the second page goes out.">Root cause analysis that gets sharper every incident</H2>
      <div className="bento-grid" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(300px, 100%), 1fr))", gap: 16 }}>
        <Tile title="Walks the graph live" span={2}>
          {p95 && typeof p95 === "object" && <div className="mono" style={{ fontSize: 13, color: "var(--text-4)" }}>p95 {p95.verdict_ms_p95 < 10 ? p95.verdict_ms_p95.toFixed(1) : Math.round(p95.verdict_ms_p95)} ms</div>}
          <Graph height={210} nodes={[g(1, "web-edge", "edge", 0, { alerting: true }), g(2, "checkout-api", "service", 1, { alerting: true }), g(3, "cart", "service", 1), g(4, "payments", "service", 2, { alerting: true }),
            g(5, "redis", "data", 2), g(6, "fraud-check", "service", 2, { alerting: true }), g(7, "config", "infra", 3, { root: true, alerting: false })]}
            edges={[{ u: 1, v: 2, origin: "official", path: true, flow: true }, { u: 2, v: 3, origin: "official" }, { u: 2, v: 4, origin: "official", path: true, flow: true }, { u: 3, v: 5, origin: "official" },
              { u: 4, v: 6, origin: "official", path: true, flow: true }, { u: 6, v: 7, origin: "learned", path: true, flow: true }]} />
          <Legend />
          <Small>Every alerting service is scored by how well a failure there explains all the alerts, along the strongest paths and in the order they fired.</Small>
        </Tile>
        <Tile title="Explains itself">
          <div className="mono" style={{ display: "flex", flexDirection: "column", gap: 8, fontSize: 14 }}>
            {(d ? d.after.ranking.slice(0, 3).map((x) => [x.name, x.confidence]) : []).map(([a, b], i) => (
              <div key={a as string} style={{ display: "grid", gridTemplateColumns: "1fr 40px", gap: 8, alignItems: "center", color: i === 0 ? "var(--accent-text)" : "var(--text-3)" }}>
                <span style={{ display: "flex", flexDirection: "column", gap: 3 }}>{a}<span style={{ height: 4, borderRadius: 2, background: "var(--muted)" }}><span style={{ display: "block", height: "100%", width: `${(b as number) * 100}%`, borderRadius: 2, background: i === 0 ? "var(--accent)" : "var(--text-4)" }} /></span></span>
                <span>{(b as number).toFixed(2)}</span>
              </div>))}
          </div>
          <Small>Ranked causes, confidence, the path, and why. No black box.</Small>
        </Tile>
        <Tile title="Learns from postmortems">
          <div className="mono" style={{ fontSize: 13, display: "flex", flexDirection: "column", gap: 6 }}>
            {(d?.changes ?? []).slice(0, 3).map((c, i) => (
              <span key={c.index} className="fade-line" style={{ color: c.symbol === "+" ? "var(--accent-text)" : c.symbol === "~" ? "var(--amber-text)" : "var(--text-3)", animationDelay: `${0.2 + i * 0.7}s` }}>{c.symbol} {c.text}{c.symbol === "~" ? ` ${c.detail.split("→ ")[1] ?? ""}` : ""}</span>))}
          </div>
          <Small>Three fields become reviewed graph changes. New edges need a second incident to count in full.</Small>
        </Tile>
        <Tile title="Proves it gets better" span={2}>
          <span className="mono" style={{ fontSize: 12, color: "var(--text-4)" }}>{r ? `held-out, ${r.meta.companies} companies` : ""}</span>
          <PairedGainChart r={r} mini />
          <Small>Each postmortem adds accuracy on companies it never saw. Random postmortems add nothing.</Small>
        </Tile>
        <Tile title="Plugs into your alerts">
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}><Pill>webhook</Pill><Pill>REST API</Pill><Pill>gw CLI</Pill><a href="#mcp"><Pill>MCP server</Pill></a></div>
          <Small>Any tool that can POST a webhook. CLI, HTTP API and an MCP server included.</Small>
        </Tile>
        <Tile title="No LLM in the hot path"><Small>Verdicts are graph math. A model can help import old postmortems; it proposes, the graph decides, you approve.</Small></Tile>
        <Tile title="Open source core"><Small>Self-host the engine with Docker Compose, or let us run it on HydraDB for you.</Small><a className="mono" href={GITHUB} style={{ fontSize: 13, color: "var(--accent-text)", textDecoration: "underline", textUnderlineOffset: 3 }}>github.com/redcode333/GhostWalk</a></Tile>
      </div>
      <Architecture />
    </Section>
  )
}

function Architecture() {
  const dot = (c: string) => <span aria-hidden="true" style={{ width: 8, height: 8, borderRadius: 99, background: c, display: "inline-block" }} />
  const steps: [string, ReactNode][] = [
    ["alerts", <span style={{ display: "inline-flex", gap: 3 }}>{dot("var(--g-edge)")}{dot("var(--g-service)")}{dot("var(--g-data)")}</span>],
    ["resolve aliases", null], ["walk", <span style={{ fontSize: 11, color: "var(--text-4)" }}>weighted paths in the store</span>], ["verdict", null],
    ["postmortem", null], ["learner", <span style={{ fontSize: 11, color: "var(--text-4)" }}>tentative → confirmed</span>],
    ["graph", <span style={{ display: "inline-flex", gap: 3 }}>{dot("var(--g-service)")}{dot("var(--g-infra)")}</span>],
  ]
  return (
    <div style={{ marginTop: 40 }}>
      <p className="mono" style={{ textAlign: "center", fontSize: 12, color: "var(--text-4)", margin: "0 0 12px" }}>how a verdict is made, and how the graph learns</p>
      <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "center", alignItems: "stretch", gap: 8 }}>
        {steps.map(([t, sub], i) => (
          <div key={t} style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <div className="card mono" style={{ padding: "10px 14px", fontSize: 13, display: "flex", flexDirection: "column", alignItems: "center", gap: 4, minWidth: 96, borderRadius: 12,
              borderColor: t === "verdict" ? "var(--accent)" : undefined }}>{t}{sub}</div>
            {i < steps.length - 1 && <ArrowRight size={16} aria-hidden="true" style={{ color: "var(--text-4)" }} />}
          </div>))}
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ MCP */
function Mcp({ d }: { d: Demo | null }) {
  const top = d?.after.ranking[0]
  const learned = d?.after.path.some((p) => p.origin === "learned")
  const tools = [["why", "alerts in, ranked roots with confidence, the path and the reasons out"], ["path", "how one service depends on a root, hop by hop"],
    ["blast_radius", "everything that goes down with a service, within N hops"], ["propose_edge", "suggest a lesson; a human approves it"]]
  const nm = (id: number) => d?.nodes.find((n) => n.id === id)?.name
  return (
    <Section id="mcp">
      <div style={{ display: "flex", flexWrap: "wrap", gap: 40, alignItems: "center" }}>
        <div style={{ flex: "1 1 min(460px, 100%)", minWidth: 0, display: "flex", flexDirection: "column", gap: 18 }}>
          <span className="mono" style={{ alignSelf: "flex-start", border: "1px solid var(--accent)", color: "var(--accent-text)", borderRadius: 999, padding: "3px 12px", fontSize: 12 }}>MCP server · beta</span>
          <h2 style={{ margin: 0, fontSize: "clamp(30px, 4.4vw, 48px)", lineHeight: 1.08, letterSpacing: "-0.03em", fontWeight: 600 }}>Ask why from Claude, Cursor or any MCP client.</h2>
          <p style={{ margin: 0, fontSize: 18, color: "var(--text-3)" }}>GhostWalk ships an MCP server, so your AI assistant gets the verdict from the graph instead of guessing from logs. The model asks; the graph answers.</p>
          <code className="mono" style={{ fontSize: 13, background: "var(--surface)", border: "1px solid var(--line)", borderRadius: 12, padding: "12px 14px", overflowX: "auto", whiteSpace: "nowrap" }}>claude mcp add ghostwalk -- gw mcp</code>
          <pre className="mono" style={{ margin: 0, fontSize: 12.5, background: "var(--surface)", border: "1px solid var(--line)", borderRadius: 12, padding: "12px 14px", overflowX: "auto" }}>{`{"mcpServers":{"ghostwalk":{"command":"gw","args":["mcp"]}}}`}</pre>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(200px, 100%), 1fr))", gap: 10 }}>
            {tools.map(([t, x]) => <div key={t} className="card" style={{ padding: "12px 14px", borderRadius: 14 }}><div className="mono" style={{ fontSize: 14, color: "var(--accent-text)" }}>{t}</div><div style={{ fontSize: 13, color: "var(--text-3)", marginTop: 2 }}>{x}</div></div>)}
          </div>
        </div>
        <div className="card" style={{ flex: "1 1 min(420px, 100%)", padding: 20, display: "flex", flexDirection: "column", gap: 12, minHeight: 360 }} aria-label="Example conversation">
          <div className="fade-line" style={{ alignSelf: "flex-end", maxWidth: "85%", background: "var(--muted)", borderRadius: 14, padding: "10px 14px", fontSize: 15, animationDelay: ".2s" }}>checkout is throwing 5xx. What broke?</div>
          <div className="fade-line mono" style={{ alignSelf: "flex-start", border: "1px dashed var(--accent)", color: "var(--accent-text)", borderRadius: 999, padding: "4px 12px", fontSize: 12, animationDelay: "1.1s" }}>
            ghostwalk.why · {d ? `${d.alerts} alerts · ${d.ms < 10 ? d.ms.toFixed(1) : Math.round(d.ms)} ms` : "…"}</div>
          {top && (
            <div className="fade-line" style={{ alignSelf: "flex-start", maxWidth: "92%", fontSize: 15, display: "flex", flexDirection: "column", gap: 8, animationDelay: "2s" }}>
              <span>The root cause is <strong className="mono" style={{ color: "var(--accent-text)" }}>{top.name}</strong> ({top.confidence.toFixed(2)} confidence), not checkout itself.</span>
              <span className="mono" style={{ fontSize: 13 }}>{d!.after.path.length ? nm(d!.after.path[0].u) + d!.after.path.map((p) => ` ${p.origin === "learned" ? "⇢" : "→"} ${nm(p.v)}`).join("") : ""}</span>
              {learned && <span style={{ color: "var(--text-3)" }}>That last hop was learned from INC-0931 and isn't in your service catalog. Want the blast radius before you roll {top.name} back?</span>}
            </div>)}
        </div>
      </div>
    </Section>
  )
}

/* ------------------------------------------------------------------ how */
const termLines = (latency: string): [string, string][] => [
  ["cmd", "$ docker compose up -d"], ["ok", "✓ hydradb · 2 nodes   ✓ api   ✓ dashboard → localhost:8080"],
  ["cmd", "$ gw map import services.yaml"], ["ok", "✓ 84 services · 212 edges · 3 tiers"],
  ["cmd", "$ gw why --alerts alerts.json"], ["out", `root   config-svc   ${latency}`], ["out", "path   config-svc ⇢ fraud-check → payments → checkout-api"],
  ["cmd", "$ gw learn INC-1042 --root config-svc"], ["out", "+ config-svc ⇢ fraud-check   tentative 0.35"],
]

function Terminal({ title, lines, loop = false }: { title: string; lines: [string, string][]; loop?: boolean }) {
  const col = (k: string) => (k === "ok" ? "#12B5A0" : k === "cmd" ? "#F6F5F1" : k === "dim" ? "#8F8E9A" : k === "hot" ? "#AC9BFF" : "#A6A5B1")
  return (
    <div style={{ position: "relative", borderRadius: 18, border: "1px solid var(--line)", background: "#0F0F16", color: "#DAD9E2", overflow: "hidden", display: "flex", flexDirection: "column", minHeight: 320 }}>
      <div className="mono" style={{ padding: "12px 16px", fontSize: 12, color: "#8F8E9A", borderBottom: "1px solid rgba(255,255,255,.07)" }}>{title}</div>
      <div className="mono" style={{ padding: "16px 20px", fontSize: 13.5, lineHeight: 1.9, flex: 1, WebkitMaskImage: "linear-gradient(to bottom, #000 62%, transparent)", maskImage: "linear-gradient(to bottom, #000 62%, transparent)" }}>
        {lines.map(([k, l], i) => (
          <div key={i} className={loop ? "" : "fade-line"} style={{ color: col(k), whiteSpace: "pre-wrap", animation: loop ? `termloop 12s ease ${(i * 0.9).toFixed(1)}s infinite` : undefined, animationDelay: loop ? `${(i * 0.9).toFixed(1)}s` : `${i * 0.35}s`, opacity: loop ? 0 : undefined }}>{l}</div>))}
        {loop && <span aria-hidden="true" style={{ display: "inline-block", width: 8, height: 16, background: "#AC9BFF", verticalAlign: "middle", animation: "caret 1s steps(1) infinite" }} />}
      </div>
    </div>
  )
}

function SearchVsWalk({ r, d }: { r: Results | null; d: Demo | null }) {
  if (!r || !d) return null
  const tf = r.methods.retrieval?.ac1.point, gw = r.methods.ghostwalk?.ac1.point
  const o = r.ops as any
  const tok = o?.tokens_per_verdict ?? o?.llm_tokens
  const foot = (acc: number | undefined, p95: number | undefined, tokens: number | undefined) => (
    <div className="mono" style={{ display: "flex", flexWrap: "wrap", gap: 16, fontSize: 12.5, color: "#A6A5B1", borderTop: "1px solid rgba(255,255,255,.07)", padding: "12px 20px" }}>
      <span>top-1 accuracy <b style={{ color: "#F6F5F1" }}>{acc != null ? f3(acc) : "n/a"}</b></span>
      <span>LLM tokens per verdict <b style={{ color: "#F6F5F1" }}>{tokens ?? "n/a"}</b></span>
      <span>p95 time <b style={{ color: "#F6F5F1" }}>{p95 != null ? `${p95 < 10 ? p95.toFixed(1) : Math.round(p95)} ms` : "n/a"}</b></span>
    </div>)
  const top = d.after.ranking[0]
  const left: [string, string][] = [["cmd", "$ search-postmortems \"" + d.search.query.slice(0, 3).join(", ") + " …\""], ["dim", "top matches (tf-idf over past postmortems)"],
    ...d.search.matches.map((m, i): [string, string] => ["out", `${i + 1}  ${m.incident}   root ${m.root}`]), ["dim", "no past postmortem blames this service"], ["dim", "→ no path, no blast radius, a guess to verify by hand"]]
  const right: [string, string][] = [["cmd", "$ gw why --alerts alerts.json"], ["hot", `root   ${top.name}   ${top.confidence.toFixed(2)}   ${d.ms < 10 ? d.ms.toFixed(1) : Math.round(d.ms)} ms`],
    ["out", "path   " + (d.after.path.length ? d.nodes.find((n) => n.id === d.after.path[0].u)!.name + d.after.path.map((p) => ` ${p.origin === "learned" ? "⇢" : "→"} ${d.nodes.find((n) => n.id === p.v)!.name}`).join("") : "")],
    ["out", `blast  ${d.blast.join(", ")}`]]
  return (
    <div style={{ marginTop: 64 }}>
      <h3 style={{ textAlign: "center", fontSize: 26, margin: "0 0 6px" }}>Search vs walk</h3>
      <p style={{ textAlign: "center", color: "var(--text-3)", margin: "0 0 20px" }}>A first-time cause. Searching old postmortems finds nothing like it; the graph gets there through the dependency it learned.</p>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(340px, 100%), 1fr))", gap: 16 }}>
        <div className="card" style={{ background: "#0F0F16", overflow: "hidden", borderRadius: 18 }}><Terminal title="Search old postmortems" lines={left} />{foot(tf, (o?.retrieval as any)?.verdict_ms_p95, tok?.retrieval)}</div>
        <div className="card" style={{ background: "#0F0F16", overflow: "hidden", borderRadius: 18 }}><Terminal title="gw why" lines={right} />{foot(gw, (o?.ghostwalk as any)?.verdict_ms_p95, tok?.ghostwalk)}</div>
      </div>
      <p style={{ textAlign: "center", fontSize: 12, color: "var(--text-4)", marginTop: 10 }}>Accuracy and time from the held-out run in results.json. The scenario above is computed by the real engine on a nine-service example.</p>
    </div>
  )
}

function StoreTable({ r }: { r: Results | null }) {
  const sw = r?.store_swap
  if (!sw) return null
  const rows: [string, string][] = [...(sw.backends.hydradb ? [["hydradb", "HydraDB, weighted paths"] as [string, string]] : []), ["kv_1hop", "Key-value, 1 hop"], ["pgvector", "pgvector, nearest postmortem"], ["pg_cte", "Postgres, recursive CTE"], ...(sw.reference !== "hydradb" ? [["inmemory", "In-memory graph"] as [string, string]] : [])]
  const ms = (x: number) => `${x < 10 ? x.toFixed(1) : Math.round(x)} ms`
  const th: React.CSSProperties = { padding: "8px 10px", fontWeight: 500, textAlign: "left", fontFamily: "Geist", color: "var(--text-4)" }
  return (
    <div style={{ marginTop: 56 }}>
      <h3 style={{ textAlign: "center", fontSize: 26, margin: "0 0 6px" }}>Without a graph, and with one</h3>
      <p style={{ textAlign: "center", color: "var(--text-3)", margin: "0 0 20px" }}>Same incidents, same learner. Only the store changes.</p>
      <div className="card" style={{ overflowX: "auto", maxWidth: 820, margin: "0 auto", padding: 8 }}>
        <table className="mono" style={{ width: "100%", minWidth: 520, fontSize: 13.5, borderCollapse: "collapse" }}>
          <thead><tr><th style={th}>Store</th><th style={th}>AC@1</th><th style={th}>vs reference</th><th style={th}>p95</th></tr></thead>
          <tbody>
            {rows.map(([k, label]) => { const b = sw.backends[k]; if (!b) return null
              return <tr key={k} style={{ borderTop: "1px solid var(--line)" }}><td style={{ padding: "9px 10px", fontFamily: "Geist" }}>{label}</td><td style={{ padding: "9px 10px" }}>{f3(b.ac1.point)}</td>
                <td style={{ padding: "9px 10px", color: "var(--text-3)" }}>{b.delta_vs_reference ? `${b.delta_vs_reference.point >= 0 ? "+" : "−"}${Math.abs(b.delta_vs_reference.point * 100).toFixed(1)} pts` : "reference"}</td><td style={{ padding: "9px 10px" }}>{ms(b.verdict_ms_p95)}</td></tr> })}
            {!sw.backends.hydradb && <tr style={{ borderTop: "1px solid var(--line)" }}><td style={{ padding: "9px 10px", fontFamily: "Geist" }}>HydraDB paths</td><td colSpan={3} style={{ padding: "9px 10px", color: "var(--text-4)", fontFamily: "Geist", fontSize: 12.5 }}>{sw.hydradb.status}</td></tr>}
          </tbody>
        </table>
      </div>
      <p style={{ textAlign: "center", fontSize: 12, color: "var(--text-4)", marginTop: 10 }}>Reference store: {sw.reference === "hydradb" ? "HydraDB" : "the in-memory graph"} ({f3(sw.backends[sw.reference]?.ac1.point ?? NaN)} AC@1).</p>
    </div>
  )
}

function How({ r, d }: { r: Results | null; d: Demo | null }) {
  const strip = proofStrip(r)
  return (
    <Section id="how">
      <H2 sub="No agents to install, no telemetry pipeline to rebuild. A map, your alerts, and one webhook.">From clone to first verdict in three commands</H2>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 32, alignItems: "stretch" }}>
        <ol style={{ flex: "1 1 min(360px, 100%)", margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 28 }}>
          {[["01", "Start it", "HydraDB, the API and the dashboard come up together.", "docker compose up -d"],
            ["02", "Load your map", "A service catalog, even a partial one. Missing edges get learned.", "gw map import services.yaml"],
            ["03", "Ask why", "From the CLI, the API, or automatically on every alert webhook.", "gw why --alerts alerts.json"]].map(([n, t, x, c]) => (
            <li key={n} style={{ display: "grid", gridTemplateColumns: "44px 1fr", gap: 12 }}>
              <span className="mono" style={{ color: "var(--accent-text)", fontSize: 15 }}>{n}</span>
              <div><h3 style={{ margin: 0, fontSize: 20 }}>{t}</h3><p style={{ margin: "4px 0 8px", color: "var(--text-3)" }}>{x}</p><code className="mono" style={{ fontSize: 13, color: "var(--text-2)" }}>{c}</code></div>
            </li>))}
          <li style={{ display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center", fontSize: 14, color: "var(--text-4)" }}>Alerts from <Pill>Alertmanager</Pill><Pill>Grafana</Pill><Pill>PagerDuty</Pill><Pill>Datadog</Pill> or any webhook</li>
        </ol>
        <div style={{ flex: "1 1 min(480px, 100%)" }}><Terminal title="~/acme · zsh" lines={termLines(verdictLatency(r) ? `${verdictLatency(r)!.text} (${verdictLatency(r)!.label})` : "")} loop /></div>
      </div>
      <SearchVsWalk r={r} d={d} />
      <StoreTable r={r} />
      <div style={{ marginTop: 56 }}>
        {strip.length > 0 ? (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(220px, 100%), 1fr))", gap: 16 }}>
            {strip.map((t) => (
              <div key={t.label} style={{ borderTop: "1px solid var(--line)", paddingTop: 16 }}>
                <div className="mono" style={{ fontSize: 40, fontWeight: 600, letterSpacing: "-0.02em" }}>{t.value}</div>
                <div style={{ fontSize: 14, color: "var(--text-3)" }}>{t.label}</div>
                {t.note && <div className="mono" style={{ fontSize: 11, color: "var(--text-4)", marginTop: 4 }}>{t.note}</div>}
              </div>))}
          </div>
        ) : <p className="mono" style={{ fontSize: 13, color: "var(--text-4)" }}>No results.json yet. Run make eval.</p>}
        <div style={{ display: "flex", flexWrap: "wrap", gap: 16, alignItems: "center", marginTop: 20, fontSize: 14, color: "var(--text-4)" }}>
          <span>Every number reruns with <span className="mono" style={{ color: "var(--text-2)" }}>$ make eval-quick</span></span>
          <Link to="/app/proof" style={{ color: "var(--accent-text)" }}>See the full proof →</Link>
        </div>
      </div>
    </Section>
  )
}

/* ------------------------------------------------------------------ pricing, faq, footer */
function Pricing() {
  const plans = [
    { n: "Free", d: "For side projects and a first real trial", p: "$0", per: "", note: "Free forever, no card needed", cta: "Start free", to: "/signup", f: ["Up to 25 services", "3 seats", "30-day incident history", "Webhook, CLI and API", "Community support"] },
    { n: "Team", d: "For startups with an on-call rotation", p: "$49", per: "/ month", note: "Flat per workspace · 14-day free trial", cta: "Start free trial", to: "/signup", hot: true, f: ["Up to 150 services", "Unlimited seats", "1-year incident history", "Postmortems from GitHub Issues", "Email support"] },
    { n: "Enterprise", d: "For large estates with strict security", p: "Custom", per: "", note: "Annual contract, volume pricing", cta: "Talk to us", to: "mailto:sales@ghostwalk.dev", f: ["Unlimited services", "SSO, SAML and audit log", "Self-hosted or private VPC", "SLA and priority support", "Onboarding with an engineer"] },
  ]
  return (
    <Section id="pricing">
      <H2 sub="Priced by the size of your service graph, not your headcount. Everyone on call gets a seat.">Simple pricing. No per-seat tax.</H2>
      <p style={{ textAlign: "center", margin: "-16px 0 28px" }}><Pill>Draft pricing</Pill></p>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(290px, 100%), 1fr))", gap: 16 }}>
        {plans.map((p) => (
          <div key={p.n} className="card" style={{ padding: 28, display: "flex", flexDirection: "column", gap: 14, borderColor: p.hot ? "var(--accent)" : undefined }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}><h3 style={{ margin: 0, fontSize: 22 }}>{p.n}</h3>{p.hot && <span style={{ fontSize: 12, color: "var(--accent-text)", border: "1px solid var(--accent)", borderRadius: 999, padding: "1px 10px" }}>Most popular</span>}</div>
            <p style={{ margin: 0, color: "var(--text-3)" }}>{p.d}</p>
            <div><span style={{ fontSize: 44, fontWeight: 600, letterSpacing: "-0.02em" }}>{p.p}</span> <span style={{ color: "var(--text-4)" }}>{p.per}</span><div style={{ fontSize: 14, color: "var(--text-4)" }}>{p.note}</div></div>
            <Btn to={p.to.startsWith("mailto") ? undefined : p.to} href={p.to.startsWith("mailto") ? p.to : undefined} variant={p.hot ? "primary" : "glass"}>{p.cta}</Btn>
            <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 8, fontSize: 15, color: "var(--text-2)" }}>
              {p.f.map((x) => <li key={x}><span style={{ color: "var(--ok)" }}>✓</span>&nbsp; {x}</li>)}
            </ul>
          </div>))}
      </div>
      <p style={{ textAlign: "center", color: "var(--text-4)", marginTop: 20 }}>Rather run it yourself? The engine is open source and free forever. <a href={GITHUB} style={{ color: "var(--accent-text)" }}>Self-host guide</a></p>
    </Section>
  )
}

const FAQ: [string, string][] = [
  ["What does GhostWalk actually do?", "When an alert storm hits, it ranks which service most likely caused it, shows the path from that service to every alert, and tells you why. After the incident, your postmortem teaches it dependencies your map was missing."],
  ["Do I need a complete service map?", "No. Start with what you have. Hidden and stale dependencies are exactly what it learns."],
  ["Can a wrong postmortem poison the graph?", "New edges enter at low weight and only count in full once a second incident confirms them. Edges that keep misleading decay and drop out. You review every change before it applies."],
  ["Do you use an LLM on my incidents?", "Not for verdicts. Those are graph computations you can reproduce. The optional postmortem importer uses a model to fill in three fields, and you approve what it proposes."],
  ["Where does my data live?", "Hosted plans keep the graph in HydraDB on object storage. Enterprise customers pick the region, or self-host so nothing leaves their infrastructure."],
  ["What happens when I outgrow the free tier?", "Nothing breaks. Verdicts keep running for your first 25 services and we let you know when an upgrade would cover the rest."],
  ["Can I cancel anytime?", "Yes. Team is billed monthly, and you can export your graph and incident history whenever you like."],
  ["Is it open source?", "The engine, learner, CLI, MCP server and eval suite are. The hosted dashboard adds teams, SSO and managed HydraDB."],
]

function Faq() {
  return (
    <Section id="faq">
      <div style={{ display: "flex", flexWrap: "wrap", gap: 48 }}>
        <div style={{ flex: "1 1 min(280px, 100%)" }}>
          <h2 style={{ margin: 0, fontSize: "clamp(30px, 4vw, 44px)", letterSpacing: "-0.03em", fontWeight: 600, lineHeight: 1.1 }}>Frequently asked questions</h2>
          <p style={{ color: "var(--text-3)", fontSize: 17 }}>Something else on your mind? We answer within a working day.</p>
          <Btn href="mailto:support@ghostwalk.dev" variant="glass">Contact support</Btn>
        </div>
        <div style={{ flex: "2 1 min(460px, 100%)", display: "flex", flexDirection: "column" }}>
          {FAQ.map(([q, a], i) => (
            <details key={q} style={{ borderTop: i ? "1px solid var(--line)" : undefined, padding: "18px 4px" }}>
              <summary style={{ cursor: "pointer", fontSize: 18, fontWeight: 500, listStyle: "none", display: "flex", justifyContent: "space-between", gap: 12 }}>{q}<span aria-hidden="true" style={{ color: "var(--text-4)" }}>+</span></summary>
              <p style={{ margin: "10px 0 0", color: "var(--text-3)", fontSize: 16 }}>{a}</p>
            </details>))}
        </div>
      </div>
    </Section>
  )
}

function Footer() {
  const col = (t: string, links: [string, string][]) => (
    <nav aria-label={t} style={{ flex: "1 1 min(140px, 100%)", display: "flex", flexDirection: "column", gap: 10 }}>
      <span style={{ fontSize: 14, color: "var(--text-4)" }}>{t}</span>{links.map(([l, h]) => <a key={l} href={h} style={{ fontSize: 15 }}>{l}</a>)}
    </nav>)
  return (
    <footer style={{ marginTop: 96, borderTop: "1px solid var(--line)" }}>
      <div style={{ maxWidth: 1240, margin: "0 auto", padding: "56px 24px 40px", display: "flex", flexWrap: "wrap", gap: 48 }}>
        <div style={{ flex: "2 1 min(260px, 100%)", display: "flex", flexDirection: "column", gap: 12 }}>
          <span className="mono" style={{ fontSize: 24, fontWeight: 600 }}>ghost<span style={{ color: "var(--accent)" }}>walk</span></span>
          <p style={{ margin: 0, color: "var(--text-4)", maxWidth: 280 }}>Root cause analysis that learns the dependencies nobody drew.</p>
        </div>
        {col("Product", [["Features", "#product"], ["Pricing", "#pricing"], ["Proof", "/app/proof"], ["FAQ", "#faq"]])}
        {col("Developers", [["GitHub", GITHUB], ["Docs", "#how"], ["API", "/api/docs"], ["MCP server", "#mcp"], ["HydraDB", "https://github.com/hydra-db/hydradb"]])}
        {col("Company", [["Outages", "#outages"], ["Contact", "mailto:support@ghostwalk.dev"], ["Privacy", "#top"], ["Terms", "#top"]])}
      </div>
      <div style={{ maxWidth: 1240, margin: "0 auto", padding: "20px 24px 32px", borderTop: "1px solid var(--line)", display: "flex", flexWrap: "wrap", gap: 16, fontSize: 14, color: "var(--text-4)" }}>
        <span>© 2026 GhostWalk</span><span style={{ marginLeft: "auto" }}>Open source · see LICENSE</span>
      </div>
    </footer>
  )
}

export default function Landing() {
  const { data: r } = useLoad(loadResults, [])
  const [d, setD] = useState<Demo | null>(null)
  const [ready, setReady] = useState(false)
  useEffect(() => { document.title = "GhostWalk — the outage is never where the pager says"; setReady(true); loadDemo().then(setD) }, [])
  return (
    <div id="top" style={{ background: "var(--bg)", color: "var(--ink)", minHeight: "100vh" }}>
      <Header />
      <Hero />
      <div id="outages" style={{ marginTop: 8, scrollMarginTop: 90 }}>{ready && <OutageGlobe />}</div>
      <InsideGhostWalk />
      <Story />
      <Bento r={r} d={d} />
      <Mcp d={d} />
      <How r={r} d={d} />
      <Pricing />
      <Faq />
      <Section>
        <div style={{ textAlign: "center", padding: "56px 24px", borderRadius: 28, border: "1px solid var(--line)", background: "var(--surface)" }}>
          <h2 style={{ margin: 0, fontSize: "clamp(28px, 4vw, 44px)", letterSpacing: "-0.03em", fontWeight: 600 }}>Your next outage is already on its way. Meet it with a map.</h2>
          <p style={{ color: "var(--text-3)", fontSize: 18 }}>Free for 25 services. Set up in an afternoon.</p>
          <div style={{ display: "flex", gap: 12, justifyContent: "center", flexWrap: "wrap" }}><Btn to="/signup">Start free</Btn><Btn to="/app/incidents" variant="glass">Watch a live outage</Btn></div>
        </div>
      </Section>
      <Footer />
    </div>
  )
}
