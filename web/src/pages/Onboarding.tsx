import { useEffect, useMemo, useState } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"
import { api } from "@/lib/api"
import { Btn, Err, KIND_COLOR, Muted, useLoad } from "@/components/common"
import { H1, Page } from "@/components/AppShell"
import { useTestAlert } from "./Settings"

const CONF = { high: "var(--ok)", medium: "var(--amber)", low: "var(--text-4)" } as const
const SOURCES = ["docker-compose", "k8s manifests", "Helm values", "env vars"]
const TABS = ["Grafana", "Alertmanager", "UptimeRobot", "Any webhook"]

function curl(tab: string, url: string) {
  const body: Record<string, string> = {
    Grafana: `{"alerts":[{"status":"firing","labels":{"alertname":"HighErrorRate","service":"checkout-api"},"startsAt":"2026-01-01T14:02:00Z"}]}`,
    Alertmanager: `{"alerts":[{"status":"firing","labels":{"alertname":"HighErrorRate","service":"checkout-api"},"startsAt":"2026-01-01T14:02:00Z"}]}`,
    UptimeRobot: `{"monitorFriendlyName":"checkout-api","alertType":"down"}`,
    "Any webhook": `{"alerts":[{"name":"checkout-api","signal":"error_rate","t":0}]}`,
  }
  const hint = { Grafana: "Contact point → Webhook → URL", Alertmanager: "receivers: - webhook_configs: - url", UptimeRobot: "Alert contacts → Webhook", "Any webhook": "POST application/json" }[tab]
  return { hint, cmd: `curl -X POST ${url} -H 'content-type: application/json' -d '${body[tab]}'` }
}

export default function Onboarding() {
  const nav = useNavigate()
  const [qs] = useSearchParams()
  const { data: o, reload } = useLoad(() => api("/api/onboarding"), [])
  const { data: cfg } = useLoad(() => api("/api/config"), [])
  const { data: st } = useLoad(() => api("/api/settings"), [])
  const [checked, setChecked] = useState<Set<string>>(new Set())
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [accepted, setAccepted] = useState<any>(null)
  const [tab, setTab] = useState("Grafana")
  const [pr, setPr] = useState<any>(null)
  const [repo, setRepo] = useState("")
  const test = useTestAlert()
  const prop = o?.proposals

  useEffect(() => {
    const inst = qs.get("installation_id")
    if (inst) api("/api/onboarding/github/connect", { method: "POST", json: { installation_id: inst } }).then(() => api("/api/onboarding/scan", { method: "POST", json: { source: "github" } }).then(reload)).catch((e) => setErr(e.message))
  }, [])
  useEffect(() => { if (prop) setChecked(new Set(prop.edges.filter((e: any) => e.accepted).map((e: any) => e.id))) }, [prop?.edges?.length])
  useEffect(() => { if (o?.repo && !repo) setRepo(o.repo) }, [o?.repo])
  useEffect(() => { if (!o?.steps?.alert && accepted) { const t = setInterval(reload, 4000); return () => clearInterval(t) } }, [o?.steps?.alert, accepted])

  const kinds = useMemo(() => Object.fromEntries((prop?.services ?? []).map((s: any) => [s.name, s.kind])), [prop])
  const [upgrade, setUpgrade] = useState<any>(null)
  const run = async (fn: () => Promise<any>) => { setBusy(true); setErr(null); setUpgrade(null); try { await fn() } catch (e: any) { if (String(e.message).includes("plan_limit")) { try { setUpgrade(JSON.parse(e.message)) } catch { setErr(e.message) } } else setErr(e.message) } finally { setBusy(false) } }
  const scan = (source: string) => run(async () => { await api("/api/onboarding/scan", { method: "POST", json: { source } }); setAccepted(null); reload() })
  const installGithub = () => run(async () => { window.location.href = (await api("/api/onboarding/github/install-url")).url })
  const accept = () => run(async () => { setAccepted(await api("/api/onboarding/accept", { method: "POST", json: { edge_ids: [...checked] } })); reload() })
  const openPr = () => run(async () => setPr(await api("/api/onboarding/postmortem-pr", { method: "POST", json: { repo } })))
  const url = st?.webhook_url ?? ""
  const step = !prop ? 1 : !accepted && !o.steps.map ? 2 : !o.steps.alert ? 3 : 4
  const steps = ["Connect GitHub", "Review your map", "Send alerts", "Postmortems"]
  const total = prop?.summary

  return (
    <Page>
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "flex-end", gap: 16 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 26, fontWeight: 600 }}>Set up your workspace</h1>
          <p style={{ margin: "4px 0 0", color: "var(--text-3)", fontSize: 15 }}>About 10 minutes. Everything is read-only, and you can skip any step.</p>
        </div>
        {o && <span className="mono" style={{ marginLeft: "auto", fontSize: 13, color: "var(--text-4)" }}>Free plan · {o.summary.services} of 25 services</span>}
      </div>
      <ol style={{ margin: 0, padding: 0, listStyle: "none", display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 8 }}>
        {steps.map((s, i) => {
          const n = i + 1, done = n < step, on = n === step
          return (
            <li key={s} aria-current={on ? "step" : undefined} style={{ display: "flex", alignItems: "center", gap: 10, padding: "12px 14px", borderRadius: 12, fontSize: 14, background: on ? "rgba(142,118,255,.12)" : "var(--surface-2)",
              border: `1px solid ${done ? "rgba(18,181,160,.35)" : on ? "rgba(142,118,255,.5)" : "var(--line)"}`, color: on || done ? "var(--ink)" : "var(--text-3)" }}>
              <span className="mono" style={{ width: 22, height: 22, borderRadius: 99, display: "grid", placeItems: "center", fontSize: 12, fontWeight: 700, background: on ? "var(--accent)" : "transparent", color: on ? "#fff" : done ? "var(--ok)" : "var(--text-3)", border: on ? 0 : "1px solid var(--line)" }}>{done ? "✓" : n}</span>{s}
            </li>
          )
        })}
      </ol>
      {err && <Err>{err}</Err>}
      {upgrade && (
        <div role="alert" className="card" style={{ padding: 20, display: "flex", flexWrap: "wrap", gap: 12, alignItems: "center", borderColor: "var(--accent)" }}>
          <div style={{ flex: 1, minWidth: 240 }}><strong>This map is over the free plan</strong><div style={{ fontSize: 14, color: "var(--text-3)" }}>{upgrade.message} Team covers up to 150 services, or accept fewer edges to stay on Free.</div></div>
          <Btn href="/#pricing">See plans</Btn>
        </div>)}

      <div style={{ display: "flex", flexWrap: "wrap", gap: 16, alignItems: "flex-start" }}>
        <section aria-labelledby="map-h" className="card" style={{ flex: "3 1 560px", minWidth: 0 }}>
          {!prop ? (
            <div style={{ padding: 24, display: "flex", flexDirection: "column", gap: 12 }}>
              <h2 id="map-h" style={{ margin: 0, fontSize: 17 }}>Connect GitHub</h2>
              <p style={{ margin: 0, fontSize: 14, color: "var(--text-3)" }}>Install the GhostWalk GitHub App. It asks for read-only access to repository contents and issues, nothing else. We read docker-compose files, Kubernetes Service and Ingress manifests, Helm values and <span className="mono">*_URL</span> variables, and propose a map. Nothing is saved until you accept.</p>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <Btn onClick={installGithub} disabled={busy || !cfg?.github?.configured}>Install the GitHub App</Btn>
                <Btn variant="glass" onClick={() => scan("sample")} disabled={busy}>Scan the sample acme repos</Btn>
              </div>
              {cfg && !cfg.github.configured && <Muted>This server has no GitHub App configured (GITHUB_APP_ID, GITHUB_APP_PRIVATE_KEY), so only the sample repos can be scanned.</Muted>}
            </div>
          ) : (
            <>
              <div style={{ padding: "18px 20px", borderBottom: "1px solid var(--line)", display: "flex", flexWrap: "wrap", gap: 12, alignItems: "center" }}>
                <div>
                  <h2 id="map-h" style={{ margin: 0, fontSize: 17 }}>We found {total.services} services and {total.dependencies} dependencies</h2>
                  <p style={{ margin: "4px 0 0", fontSize: 14, color: "var(--text-3)" }}>Read from {total.repos.length} repos{prop.source === "sample" ? " (sample)" : ""}. Nothing is saved until you accept.</p>
                </div>
                <div className="mono" style={{ marginLeft: "auto", display: "flex", gap: 6, fontSize: 12, flexWrap: "wrap" }}>
                  {SOURCES.filter((s) => total.by_source[s]).map((s) => <span key={s} style={{ border: "1px solid var(--line)", borderRadius: 999, padding: "4px 10px" }}>{s} · {total.by_source[s]}</span>)}
                </div>
              </div>
              <div className="mono" style={{ fontSize: 14, maxHeight: 460, overflowY: "auto" }}>
                <div style={{ display: "grid", gridTemplateColumns: "24px minmax(0,1fr) minmax(0,1fr) 80px", gap: 12, padding: "10px 20px", color: "var(--text-4)", fontSize: 12, fontFamily: "Geist" }}>
                  <span /><span>Dependency</span><span>Found in</span><span>Confidence</span>
                </div>
                {prop.edges.map((e: any) => (
                  <label key={e.id} style={{ display: "grid", gridTemplateColumns: "24px minmax(0,1fr) minmax(0,1fr) 80px", gap: 12, alignItems: "center", padding: "12px 20px", borderTop: "1px solid var(--line)", cursor: "pointer" }}>
                    <input type="checkbox" checked={checked.has(e.id)} style={{ accentColor: "var(--accent)", width: 16, height: 16 }}
                      onChange={() => setChecked((s) => { const n = new Set(s); n.has(e.id) ? n.delete(e.id) : n.add(e.id); return n })} />
                    <span><span style={{ color: KIND_COLOR[kinds[e.src]] }}>●</span> {e.src} → <span style={{ color: KIND_COLOR[kinds[e.dst]] }}>●</span> {e.dst}</span>
                    <span style={{ color: "var(--text-4)", fontSize: 13 }}>{e.repo} · {e.file} · {e.evidence}</span>
                    <span style={{ color: CONF[e.confidence as keyof typeof CONF], fontFamily: "Geist" }}>{e.confidence}</span>
                  </label>
                ))}
              </div>
              <div style={{ padding: "14px 20px", borderTop: "1px solid var(--line)", display: "flex", flexWrap: "wrap", gap: 10, alignItems: "center", fontSize: 14, color: "var(--text-3)" }}>
                {accepted ? <span style={{ color: "var(--ok)" }} role="status">✓ Official map set: {accepted.services} services, {accepted.dependencies} dependencies.</span>
                  : <span>Dependencies that live only in code or config files are what GhostWalk learns later from postmortems.</span>}
                <span style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
                  {accepted ? <Btn to="/app/map" variant="glass">Open in map</Btn> : null}
                  <Btn onClick={accepted ? () => nav("/app/incidents") : accept} disabled={busy || (!accepted && checked.size === 0)}>{accepted ? "Continue" : `Accept ${checked.size} and continue`}</Btn>
                </span>
              </div>
            </>
          )}
        </section>

        <aside style={{ flex: "2 1 320px", minWidth: 0, display: "flex", flexDirection: "column", gap: 16 }}>
          <section aria-labelledby="al-h" className="card" style={{ padding: "18px 20px", display: "flex", flexDirection: "column", gap: 12 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}><span className="mono" style={{ fontSize: 12, color: "var(--text-4)" }}>Next</span><h2 id="al-h" style={{ margin: 0, fontSize: 16 }}>Send alerts</h2></div>
            <div role="tablist" aria-label="Alert source" style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
              {TABS.map((t) => <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)} style={{ minHeight: 30, padding: "0 10px", borderRadius: 7, border: 0, background: tab === t ? "var(--muted)" : "transparent", color: tab === t ? "var(--ink)" : "var(--text-3)", font: "500 13px Geist", cursor: "pointer" }}>{t}</button>)}
            </div>
            <div className="mono" style={{ fontSize: 13, background: "var(--surface-2)", border: "1px solid var(--line)", borderRadius: 8, padding: "10px 12px", overflowX: "auto", whiteSpace: "nowrap" }}>{url}</div>
            <div style={{ fontSize: 12, color: "var(--text-4)" }}>{curl(tab, url).hint}</div>
            <pre className="mono" style={{ margin: 0, fontSize: 11, color: "var(--text-3)", whiteSpace: "pre-wrap", wordBreak: "break-all", background: "var(--surface-2)", padding: 10, borderRadius: 8 }}>{curl(tab, url).cmd}</pre>
            <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, color: "var(--text-3)" }}>
              {o?.steps.alert ? <><span style={{ width: 8, height: 8, borderRadius: 99, background: "var(--ok)" }} />First alert received</> : <><span className="live" style={{ width: 8, height: 8, borderRadius: 99, background: "var(--amber)" }} />Waiting for the first alert…</>}
              <span style={{ marginLeft: "auto" }}><Btn variant="glass" onClick={() => test.send().then(reload)} disabled={test.busy}>Send test alert</Btn></span>
            </div>
            {test.msg && <div role="status" className="mono" style={{ fontSize: 12, color: "var(--ok)" }}>✓ {test.msg}{test.id ? <> · <a href={`/app/incidents/${test.id}`} style={{ textDecoration: "underline" }}>open</a></> : null}</div>}
            {test.err && <Err>{test.err}</Err>}
          </section>

          <section aria-labelledby="pm-h" className="card" style={{ padding: "18px 20px", display: "flex", flexDirection: "column", gap: 12 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}><span className="mono" style={{ fontSize: 12, color: "var(--text-4)" }}>Then</span><h2 id="pm-h" style={{ margin: 0, fontSize: 16 }}>Postmortems from GitHub</h2></div>
            <p style={{ margin: 0, fontSize: 14, color: "var(--text-3)" }}>We add a 3-field issue form to <span className="mono" style={{ color: "var(--text-2)" }}>{repo || "your repo"}</span>. Any issue labelled <span className="mono" style={{ color: "var(--accent-text)" }}>postmortem</span> becomes proposed graph changes for you to review.</p>
            <div className="mono" style={{ fontSize: 12, background: "var(--surface-2)", border: "1px solid var(--line)", borderRadius: 8, padding: "10px 12px", color: "var(--text-4)", lineHeight: 1.7 }}>
              .github/ISSUE_TEMPLATE/postmortem.yml<br /><span style={{ color: "var(--text-2)" }}>root cause · path · what the map missed</span>
            </div>
            <input className="mono" value={repo} onChange={(e) => setRepo(e.target.value)} placeholder="owner/repo" aria-label="Repository" style={{ padding: "8px 10px", borderRadius: 8, border: "1px solid var(--line)", background: "var(--surface-2)", color: "var(--ink)", fontSize: 13 }} />
            <Btn variant="glass" onClick={openPr} disabled={busy || !repo.includes("/")}>Open pull request with template</Btn>
            {pr?.mode === "pr" && <div role="status" style={{ fontSize: 13 }}>✓ <a href={pr.url} style={{ color: "var(--accent-text)", textDecoration: "underline" }}>Pull request opened</a></div>}
            {pr?.mode === "link" && (
              <div role="status" style={{ fontSize: 13, color: "var(--text-3)", display: "flex", flexDirection: "column", gap: 6 }}>
                <span>{pr.why}</span>
                <a href={pr.url} target="_blank" rel="noreferrer" style={{ color: "var(--accent-text)", textDecoration: "underline" }}>Create the file on GitHub →</a>
              </div>
            )}
            <div style={{ fontSize: 12, color: "var(--text-4)" }}>Webhook for the App: <span className="mono">/api/webhooks/github</span> (Issues event). Proposals land in <a href="/app/learn" style={{ textDecoration: "underline" }}>Learn</a>.</div>
          </section>
        </aside>
      </div>
    </Page>
  )
}
