import { useEffect, useRef, useState, type ReactNode } from "react"
import { Link } from "react-router-dom"
import { ArrowRight, Boxes, GitBranch, HelpCircle, Route, Tag, Users } from "lucide-react"
import { LiquidNavbar } from "@/components/ui/liquid-glass-navbar"
import { Btn, Logo, ThemeToggle, useLoad, useTheme } from "@/components/common"
import { Graph, Legend } from "@/components/Graph"
import { OutageGlobe } from "@/components/OutageGlobe"
import { loadResults, proofStrip, type Results } from "@/lib/results"

const GITHUB = "https://github.com/redcode333/GhostWalk"
const Section = ({ id, children, style }: { id?: string; children: ReactNode; style?: React.CSSProperties }) => (
  <section id={id} style={{ maxWidth: 1240, margin: "0 auto", padding: "88px 24px 0", scrollMarginTop: 90, ...style }}>{children}</section>
)
const H2 = ({ children, sub }: { children: ReactNode; sub?: string }) => (
  <div style={{ textAlign: "center", marginBottom: 40 }}>
    <h2 style={{ margin: 0, fontSize: "clamp(30px, 4.4vw, 48px)", lineHeight: 1.08, letterSpacing: "-0.03em", fontWeight: 600 }}>{children}</h2>
    {sub && <p style={{ margin: "12px auto 0", maxWidth: 620, fontSize: 18, color: "var(--text-3)" }}>{sub}</p>}
  </div>
)

function Header() {
  const { dark } = useTheme()
  return (
    <header style={{ position: "sticky", top: 0, zIndex: 30, display: "flex", alignItems: "center", gap: 12, padding: "12px 24px", background: "linear-gradient(var(--bg) 40%, transparent)" }}>
      <Link to="/" aria-label="GhostWalk home"><Logo /></Link>
      <div style={{ flex: 1, display: "flex", justifyContent: "center", minWidth: 0, overflowX: "auto" }}>
        <LiquidNavbar tone={dark ? "dark" : "light"}
          items={[
            { label: "Product", href: "#product", icon: <Boxes size={18} />, fx: "pop" },
            { label: "Customers", href: "#story", icon: <Users size={18} />, fx: "wave" },
            { label: "How it works", href: "#how", icon: <Route size={18} />, fx: "glow" },
            { label: "Pricing", href: "#pricing", icon: <Tag size={18} />, fx: "pop" },
            { label: "FAQ", href: "#faq", icon: <HelpCircle size={18} />, fx: "spin" },
            { label: "GitHub", href: GITHUB, icon: <GitBranch size={18} />, fx: "drop" },
          ]} />
      </div>
      <ThemeToggle />
      <Btn to="/signin" variant="glass">Sign in</Btn>
      <Btn to="/signup">Start free</Btn>
    </header>
  )
}

function Hero() {
  return (
    <div style={{ textAlign: "center", padding: "72px 24px 0", maxWidth: 1000, margin: "0 auto" }}>
      <span className="mono" style={{ display: "inline-flex", alignItems: "center", gap: 8, border: "1px solid var(--line)", borderRadius: 999, padding: "6px 14px", fontSize: 13, color: "var(--text-3)", background: "var(--surface)" }}>
        <span style={{ color: "var(--ink)" }}>Open source</span><span style={{ color: "var(--text-4)" }}>·</span>Root cause analysis on HydraDB <ArrowRight size={14} />
      </span>
      <h1 style={{ margin: "24px 0 0", fontSize: "clamp(44px, 8vw, 84px)", lineHeight: 1.02, letterSpacing: "-0.04em", fontWeight: 600 }}>The outage is never where the pager says.</h1>
      <p style={{ margin: "22px auto 0", maxWidth: 720, fontSize: "clamp(17px, 2vw, 21px)", color: "var(--text-3)" }}>
        GhostWalk walks your service graph from fourteen alerts to the one broken dependency in milliseconds, and learns the dependencies nobody drew from every postmortem.
      </p>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 12, justifyContent: "center", marginTop: 32 }}>
        <Btn to="/signup">Start free</Btn>
        <Btn to="/app/incidents" variant="glass">Watch a live outage <ArrowRight size={16} /></Btn>
      </div>
      <p className="mono" style={{ margin: "20px 0 0", fontSize: 13, color: "var(--text-4)" }}>Free for 25 services · No card needed · docker compose up</p>
    </div>
  )
}

function Story() {
  const rows = [["11:05", "a ClickHouse access-control change ships"], ["11:20", "core traffic starts failing with 5xx"],
    ["···", "responders suspect a hyper-scale DDoS; an unrelated status-page outage makes it look likelier"],
    ["···", "Turnstile fails, so dashboard logins fail; Workers KV and Access throw errors"], ["14:30", "the bad Bot Management feature file is stopped; core traffic recovers"], ["17:06", "all downstream services restored"]]
  return (
    <Section id="story">
      <div style={{ textAlign: "center", marginBottom: 40 }}>
        <span className="eyebrow">Cloudflare · 18 November 2025</span>
        <h2 style={{ margin: "10px 0 0", fontSize: "clamp(30px, 4.4vw, 48px)", lineHeight: 1.08, letterSpacing: "-0.03em", fontWeight: 600 }}>The pager said DDoS. The cause was a database permission.</h2>
        <p style={{ margin: "12px auto 0", maxWidth: 620, fontSize: 18, color: "var(--text-3)" }}>Five services alerted at once. Every one of them traced back to a file nobody thought of as a dependency.</p>
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 20 }}>
        <div className="card" style={{ flex: "1 1 460px", padding: 28 }}>
          <h3 style={{ margin: 0, fontSize: 20 }}>What happened</h3>
          <p style={{ margin: "2px 0 16px", fontSize: 13, color: "var(--text-4)" }}>from Cloudflare's postmortem, UTC</p>
          {rows.map(([t, s], i) => (
            <div key={i} style={{ display: "grid", gridTemplateColumns: "56px 1fr", gap: 12, padding: "8px 0", fontSize: 15 }}>
              <span className="mono" style={{ color: t === "···" ? "var(--text-4)" : "var(--ink)" }}>{t}</span><span style={{ color: "var(--text-2)" }}>{s}</span>
            </div>
          ))}
          <div style={{ display: "flex", gap: 32, margin: "18px 0", flexWrap: "wrap" }}>
            <div><div className="mono" style={{ fontSize: 34, fontWeight: 600 }}>3h 10m</div><div style={{ fontSize: 13, color: "var(--text-4)" }}>core traffic impact</div></div>
            <div><div className="mono" style={{ fontSize: 34, fontWeight: 600 }}>5h 46m</div><div style={{ fontSize: 13, color: "var(--text-4)" }}>until fully resolved</div></div>
          </div>
          <a href="https://blog.cloudflare.com/18-november-2025-outage/" target="_blank" rel="noreferrer" style={{ color: "var(--accent-text)", fontSize: 15 }}>Read Cloudflare's postmortem →</a>
        </div>
        <div className="card" style={{ flex: "1 1 460px", padding: 28, display: "flex", flexDirection: "column", gap: 14 }}>
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
          <p style={{ margin: 0, fontSize: 14, color: "var(--text-4)" }}>Assumes the feature-file dependency is in the graph. That's exactly the kind of edge a single earlier postmortem teaches GhostWalk.</p>
        </div>
      </div>
    </Section>
  )
}

function Tile({ title, children, span = 1 }: { title: string; children?: ReactNode; span?: number }) {
  return (
    <div className="card" style={{ padding: 24, display: "flex", flexDirection: "column", gap: 12, gridColumn: `span ${span}` }}>
      <h3 style={{ margin: 0, fontSize: 20 }}>{title}</h3>{children}
    </div>
  )
}
const Small = ({ children }: { children: ReactNode }) => <p style={{ margin: 0, fontSize: 15, color: "var(--text-3)" }}>{children}</p>

function MiniCurve({ r }: { r: Results | null }) {
  const s = r?.learning_curve?.series
  if (!s?.ghostwalk) return <Small>Runs on held-out companies; see the proof page.</Small>
  const W = 360, H = 90
  const lo = Math.min(...s.ghostwalk.map((p) => p.ac1), ...(s.learning_off ?? []).map((p) => p.ac1)) - 0.03, hi = Math.max(...s.ghostwalk.map((p) => p.ac1)) + 0.03
  const path = (k: string) => (s[k] ?? []).map((p, i, a) => `${i ? "L" : "M"}${(i * (W - 8)) / (a.length - 1) + 4},${H - 6 - ((p.ac1 - lo) / (hi - lo)) * (H - 12)}`).join(" ")
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="Accuracy by incident number: GhostWalk rising above learning off">
      <path d={path("learning_off")} fill="none" stroke="var(--text-4)" strokeWidth="1.6" /><path d={path("ghostwalk")} fill="none" stroke="var(--accent)" strokeWidth="2.4" />
    </svg>
  )
}

function Bento({ r }: { r: Results | null }) {
  const p95 = r?.ops?.ghostwalk
  return (
    <Section id="product">
      <H2 sub="Deterministic, explainable, and fast enough to answer before the second page goes out.">Root cause analysis that gets sharper every incident</H2>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: 16 }}>
        <Tile title="Walks the graph live" span={2}>
          <div style={{ fontFamily: "Geist Mono", fontSize: 13, color: "var(--text-4)" }}>{p95 && typeof p95 === "object" ? `p95 ${p95.verdict_ms_p95 < 10 ? p95.verdict_ms_p95.toFixed(1) : Math.round(p95.verdict_ms_p95)} ms` : ""}</div>
          <Graph height={170} labels={false} nodes={[
            { id: 1, name: "edge", kind: "edge", tier: 0 }, { id: 2, name: "api", kind: "service", tier: 1, alerting: true }, { id: 3, name: "cart", kind: "service", tier: 1, alerting: true },
            { id: 4, name: "db", kind: "data", tier: 2, alerting: true }, { id: 5, name: "config", kind: "infra", tier: 3, root: true, alerting: true }]}
            edges={[{ u: 1, v: 2, origin: "official" }, { u: 1, v: 3, origin: "official" }, { u: 2, v: 4, origin: "official" }, { u: 3, v: 4, origin: "official" }, { u: 4, v: 5, origin: "learned", path: true }]} />
          <Legend />
          <Small>Every alerting service is scored by how well a failure there explains all the alerts, along the strongest paths and in the order they fired.</Small>
        </Tile>
        <Tile title="Explains itself">
          <div className="mono" style={{ fontSize: 14, display: "flex", flexDirection: "column", gap: 4 }}>
            {[["config-svc", "0.81"], ["fraud-check", "0.12"], ["payments", "0.05"]].map(([a, b], i) => <span key={a} style={{ display: "flex", justifyContent: "space-between", color: i === 0 ? "var(--accent-text)" : "var(--text-3)" }}><span>{a}</span><span>{b}</span></span>)}
          </div>
          <Small>Ranked causes, confidence, the path, and why. No black box.</Small>
        </Tile>
        <Tile title="Learns from postmortems">
          <div className="mono" style={{ fontSize: 13, display: "flex", flexDirection: "column", gap: 4 }}>
            <span style={{ color: "var(--accent-text)" }}>+ config-svc ⇢ fraud-check</span><span style={{ color: "var(--amber)" }}>~ fraud-check → payments 0.73</span><span style={{ color: "var(--text-3)" }}>= "cfg" alias of config-svc</span>
          </div>
          <Small>Three fields become reviewed graph changes. New edges need a second incident to count in full.</Small>
        </Tile>
        <Tile title="Proves it gets better" span={2}>
          <span className="mono" style={{ fontSize: 12, color: "var(--text-4)" }}>{r ? `held-out, ${r.meta.companies} companies` : "sample shape"}</span>
          <MiniCurve r={r} />
          <Small>Accuracy rises with each postmortem on held-out companies. Random postmortems teach nothing, and that flat line is part of the proof.</Small>
        </Tile>
        <Tile title="Plugs into your alerts">
          <div className="mono" style={{ display: "flex", flexWrap: "wrap", gap: 6, fontSize: 12 }}>{["webhook", "REST API", "gw CLI", "MCP · soon"].map((t) => <span key={t} style={{ border: "1px solid var(--line)", borderRadius: 999, padding: "3px 10px" }}>{t}</span>)}</div>
          <Small>Any tool that can POST a webhook. CLI and HTTP API included.</Small>
        </Tile>
        <Tile title="No LLM in the hot path"><Small>Verdicts are graph math. A model can help import old postmortems; it proposes, the graph decides, you approve.</Small></Tile>
        <Tile title="Open source core"><Small>Self-host the engine with Docker Compose, or let us run it on HydraDB for you.</Small><a className="mono" href={GITHUB} style={{ fontSize: 13, color: "var(--accent-text)" }}>github.com/redcode333/GhostWalk</a></Tile>
      </div>
    </Section>
  )
}

const TERM: [string, string][] = [
  ["cmd", "$ docker compose up -d"], ["ok", "✓ hydradb · 2 nodes   ✓ api   ✓ dashboard → localhost:8080"],
  ["cmd", "$ gw map import services.yaml"], ["ok", "✓ 84 services · 212 edges · 3 tiers"],
  ["cmd", "$ gw why --alerts alerts.json"], ["out", "root   config-svc   0.81   38 ms"], ["out", "path   config-svc ⇢ fraud-check → payments → checkout-api"],
  ["cmd", "$ gw learn INC-1042 --root config-svc"], ["out", "+ config-svc ⇢ fraud-check   tentative 0.35"], ["cmd", "$"],
]

function Steps({ r }: { r: Results | null }) {
  const strip = proofStrip(r)
  return (
    <Section id="how">
      <H2 sub="No agents to install, no telemetry pipeline to rebuild. A map, your alerts, and one webhook.">From clone to first verdict in three commands</H2>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 32, alignItems: "stretch" }}>
        <ol style={{ flex: "1 1 360px", margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 28 }}>
          {[["01", "Start it", "HydraDB, the API and the dashboard come up together.", "docker compose up -d"],
            ["02", "Load your map", "A service catalog, even a partial one. Missing edges get learned.", "gw map import services.yaml"],
            ["03", "Ask why", "From the CLI, the API, or automatically on every alert webhook.", "gw why --alerts alerts.json"]].map(([n, t, d, c]) => (
            <li key={n} style={{ display: "grid", gridTemplateColumns: "44px 1fr", gap: 12 }}>
              <span className="mono" style={{ color: "var(--accent-text)", fontSize: 15 }}>{n}</span>
              <div><h3 style={{ margin: 0, fontSize: 20 }}>{t}</h3><p style={{ margin: "4px 0 8px", color: "var(--text-3)" }}>{d}</p><code className="mono" style={{ fontSize: 13, color: "var(--text-2)" }}>{c}</code></div>
            </li>))}
          <li style={{ fontSize: 14, color: "var(--text-4)" }}>Alerts from <span style={{ color: "var(--text-2)" }}>Alertmanager · Grafana · PagerDuty · Datadog</span> or any webhook</li>
        </ol>
        <div style={{ flex: "1 1 480px", position: "relative", borderRadius: 18, border: "1px solid var(--line)", background: "#0F0F16", color: "#DAD9E2", overflow: "hidden", minHeight: 360 }}>
          <div className="mono" style={{ padding: "12px 16px", fontSize: 12, color: "#8F8E9A", borderBottom: "1px solid rgba(255,255,255,.07)" }}>~/acme · zsh</div>
          <div className="mono" style={{ padding: "16px 20px", fontSize: 13.5, lineHeight: 1.9, WebkitMaskImage: "linear-gradient(to bottom, #000 62%, transparent)", maskImage: "linear-gradient(to bottom, #000 62%, transparent)" }}>
            {TERM.map(([k, l], i) => <div key={i} className="fade-line" style={{ animationDelay: `${i * 0.35}s`, color: k === "ok" ? "#12B5A0" : k === "cmd" ? "#F6F5F1" : "#A6A5B1", whiteSpace: "pre-wrap" }}>{l}</div>)}
          </div>
        </div>
      </div>
      <div style={{ marginTop: 56 }}>
        {strip.length > 0 ? (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 16 }}>
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

function Pricing() {
  const plans = [
    { n: "Free", d: "For trying it on a real system", p: "$0", per: "forever", cta: "Start free", to: "/signup", f: ["Up to 25 services", "1 workspace, 3 seats", "30-day incident history", "Webhook, CLI and API", "Community support"] },
    { n: "Team", d: "For teams that carry a pager", p: "$500", per: "/ month", cta: "Start 14-day trial", to: "/signup", hot: true, f: ["Up to 200 services", "Unlimited seats and history", "Hosted HydraDB, your region", "Postmortem import (beta)", "Email support"] },
    { n: "Business", d: "For large estates and strict security", p: "$2,000", per: "/ month", cta: "Talk to us", to: "#faq", f: ["Unlimited services", "SSO and SAML, audit log", "Private VPC or self-hosted", "Priority support and SLA", "Onboarding with an engineer"] },
  ]
  return (
    <Section id="pricing">
      <H2 sub="One avoided war room covers a year of Team. Draft pricing">Start free. Pay when it pays for itself.</H2>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(290px, 1fr))", gap: 16 }}>
        {plans.map((p) => (
          <div key={p.n} className="card" style={{ padding: 28, display: "flex", flexDirection: "column", gap: 14, borderColor: p.hot ? "var(--accent)" : undefined }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}><h3 style={{ margin: 0, fontSize: 22 }}>{p.n}</h3>{p.hot && <span className="mono" style={{ fontSize: 11, color: "var(--accent-text)" }}>Most teams</span>}</div>
            <p style={{ margin: 0, color: "var(--text-3)" }}>{p.d}</p>
            <div><span className="mono" style={{ fontSize: 40, fontWeight: 600 }}>{p.p}</span> <span style={{ color: "var(--text-4)" }}>{p.per}</span></div>
            <Btn to={p.to.startsWith("#") ? undefined : p.to} href={p.to.startsWith("#") ? p.to : undefined} variant={p.hot ? "primary" : "glass"}>{p.cta}</Btn>
            <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 8, fontSize: 15, color: "var(--text-2)" }}>
              {p.f.map((x) => <li key={x}><span style={{ color: "var(--ok)" }}>✓</span>&nbsp; {x}</li>)}
            </ul>
          </div>))}
      </div>
      <p style={{ textAlign: "center", color: "var(--text-4)", marginTop: 20 }}>Prefer to run it yourself? The engine is open source. <a href={GITHUB} style={{ color: "var(--accent-text)" }}>Self-host guide</a></p>
    </Section>
  )
}

const FAQ: [string, string][] = [
  ["What does GhostWalk actually do?", "When an alert storm hits, it ranks which service most likely caused it, shows the path from that service to every alert, and tells you why. After the incident, your postmortem teaches it dependencies your map was missing."],
  ["Do I need a complete service map?", "No. Start with what you have. Hidden and stale dependencies are exactly what it learns."],
  ["Can a wrong postmortem poison the graph?", "New edges enter at low weight and only count in full once a second incident confirms them. Edges that keep misleading decay and drop out. You review every change before it applies."],
  ["Do you use an LLM on my incidents?", "Not for verdicts. Those are graph computations you can reproduce. The optional postmortem importer uses a model to fill in three fields, and you approve what it proposes."],
  ["Where does my data live?", "Hosted plans keep the graph in HydraDB on object storage in the region you choose. Self-hosted, nothing leaves your infrastructure."],
  ["What happens when I outgrow the free tier?", "Nothing breaks. Verdicts keep running for your first 25 services and we let you know when an upgrade would cover the rest."],
  ["Can I cancel anytime?", "Yes. Plans are monthly, and you can export your graph and incident history whenever you like."],
  ["Is it open source?", "The engine, learner, CLI and eval suite are. The hosted dashboard adds teams, SSO and managed HydraDB."],
]

function Faq() {
  return (
    <Section id="faq" style={{ maxWidth: 860 }}>
      <H2 sub="Something else on your mind? We answer within a working day.">Frequently asked questions</H2>
      <div style={{ display: "flex", flexDirection: "column" }}>
        {FAQ.map(([q, a]) => (
          <details key={q} style={{ borderTop: "1px solid var(--line)", padding: "18px 4px" }}>
            <summary style={{ cursor: "pointer", fontSize: 18, fontWeight: 500, listStyle: "none", display: "flex", justifyContent: "space-between" }}>{q}<span aria-hidden="true" style={{ color: "var(--text-4)" }}>+</span></summary>
            <p style={{ margin: "10px 0 0", color: "var(--text-3)", fontSize: 16 }}>{a}</p>
          </details>))}
      </div>
      <div style={{ textAlign: "center", marginTop: 20 }}><Btn href="mailto:support@ghostwalk.dev" variant="glass">Contact support</Btn></div>
    </Section>
  )
}

function Footer() {
  const col = (t: string, links: [string, string][]) => (
    <nav aria-label={t} style={{ flex: "1 1 140px", display: "flex", flexDirection: "column", gap: 10 }}>
      <span style={{ fontSize: 14, color: "var(--text-4)" }}>{t}</span>{links.map(([l, h]) => <a key={l} href={h} style={{ fontSize: 15 }}>{l}</a>)}
    </nav>)
  return (
    <footer style={{ marginTop: 96, borderTop: "1px solid var(--line)" }}>
      <div style={{ maxWidth: 1240, margin: "0 auto", padding: "56px 24px 40px", display: "flex", flexWrap: "wrap", gap: 48 }}>
        <div style={{ flex: "2 1 260px", display: "flex", flexDirection: "column", gap: 12 }}>
          <span className="mono" style={{ fontSize: 24, fontWeight: 600 }}>ghost<span style={{ color: "var(--accent)" }}>walk</span></span>
          <p style={{ margin: 0, color: "var(--text-4)", maxWidth: 280 }}>Root cause analysis that learns the dependencies nobody drew.</p>
        </div>
        {col("Product", [["Features", "#product"], ["Pricing", "#pricing"], ["Proof", "/app/proof"], ["FAQ", "#faq"]])}
        {col("Developers", [["GitHub", GITHUB], ["Docs", "#how"], ["API", "/api/docs"], ["HydraDB", "https://github.com/hydra-db/hydradb"]])}
        {col("Company", [["Customers", "#story"], ["Contact", "#faq"], ["Privacy", "#top"], ["Terms", "#top"]])}
      </div>
      <div style={{ maxWidth: 1240, margin: "0 auto", padding: "20px 24px 32px", borderTop: "1px solid var(--line)", display: "flex", flexWrap: "wrap", gap: 16, fontSize: 14, color: "var(--text-4)" }}>
        <span>© 2026 GhostWalk</span><span style={{ marginLeft: "auto" }}>Open source · see LICENSE</span>
      </div>
    </footer>
  )
}

export default function Landing() {
  const { data: r } = useLoad(loadResults, [])
  const top = useRef<HTMLDivElement>(null)
  useEffect(() => { document.title = "GhostWalk — the outage is never where the pager says" }, [])
  const [ready, setReady] = useState(false)
  useEffect(() => setReady(true), [])
  return (
    <div id="top" ref={top} style={{ background: "var(--bg)", color: "var(--ink)", minHeight: "100vh" }}>
      <Header />
      <Hero />
      <div style={{ marginTop: 40 }}>{ready && <OutageGlobe />}</div>
      <Story />
      <Bento r={r} />
      <Steps r={r} />
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
