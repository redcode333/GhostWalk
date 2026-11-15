import { useState } from "react"
import { api } from "@/lib/api"
import { Btn, Err, Muted, useLoad } from "@/components/common"
import { H1, Page } from "@/components/AppShell"

const Row = ({ k, v }: { k: string; v: React.ReactNode }) => (
  <div style={{ display: "flex", justifyContent: "space-between", gap: 12, padding: "8px 0", borderTop: "1px solid var(--line)", fontSize: 14 }}>
    <span style={{ color: "var(--text-3)" }}>{k}</span><span className="mono">{v}</span>
  </div>
)

export function useTestAlert() {
  const [state, setState] = useState<{ busy: boolean; msg: string | null; id?: string; err?: string }>({ busy: false, msg: null })
  const send = async () => {
    setState({ busy: true, msg: null })
    try {
      const r = await api("/api/test-alert", { method: "POST" })
      setState({ busy: false, id: r.id, msg: `${r.id}: verdict ${r.root} in ${r.ms} ms (planted root: ${r.planted_root})` })
    } catch (e: any) { setState({ busy: false, msg: null, err: e.message }) }
  }
  return { ...state, send }
}

export default function Settings() {
  const { data: s, error, reload } = useLoad(() => api("/api/settings"), [])
  const [tok, setTok] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const t = useTestAlert()
  if (error) return <Page><Err>{error}</Err></Page>
  if (!s) return <Page><Muted>Loading…</Muted></Page>
  return (
    <Page max={860}>
      <H1 title="Settings" sub="Connect alerts in, get verdicts out." />
      <section className="card" style={{ padding: 20, display: "flex", flexDirection: "column", gap: 12 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <h2 style={{ margin: 0, fontSize: 17 }}>Alert webhook</h2>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 13, color: "var(--text-3)" }}>
            <span className={s.receiving ? "" : "live"} style={{ width: 8, height: 8, borderRadius: 99, background: s.receiving ? "var(--ok)" : "var(--amber)" }} />{s.receiving ? "Receiving" : "Waiting for the first alert"}
          </span>
        </div>
        <p style={{ margin: 0, fontSize: 14, color: "var(--text-3)" }}>Point Alertmanager, PagerDuty or any tool that can POST JSON here.</p>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <code className="mono" style={{ flex: 1, minWidth: 240, background: "var(--surface-2)", border: "1px solid var(--line)", borderRadius: 8, padding: "10px 12px", fontSize: 13, overflowX: "auto", whiteSpace: "nowrap" }}>{s.webhook_url}</code>
          <Btn variant="glass" onClick={() => navigator.clipboard?.writeText(s.webhook_url).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1200) })}>{copied ? "Copied" : "Copy"}</Btn>
          <Btn onClick={t.send} disabled={t.busy}>Send test alert</Btn>
        </div>
        {t.msg && <div role="status" className="mono" style={{ fontSize: 13, color: "var(--ok)" }}>✓ {t.msg}</div>}
        {t.err && <Err>{t.err}</Err>}
      </section>
      <section className="card" style={{ padding: 20 }}>
        <h2 style={{ margin: "0 0 10px", fontSize: 17 }}>API token</h2>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <code className="mono" style={{ flex: 1, minWidth: 240, fontSize: 13 }}>{tok ?? s.token_masked}</code>
          <Btn variant="glass" onClick={async () => setTok(tok ? null : (await api("/api/settings/token/reveal", { method: "POST" })).token)}>{tok ? "Hide" : "Reveal"}</Btn>
          <Btn variant="glass" onClick={async () => { if (confirm("Rotate the token? Anything using the old one stops working.")) { setTok((await api("/api/settings/token/rotate", { method: "POST" })).token); reload() } }}>Rotate</Btn>
        </div>
        <p style={{ margin: "8px 0 0", fontSize: 12, color: "var(--text-4)" }}>Send it as <span className="mono">Authorization: Bearer …</span>. Required when sign-in is on ({s.auth_mode}).</p>
      </section>
      <section className="card" style={{ padding: 20 }}>
        <h2 style={{ margin: "0 0 10px", fontSize: 17 }}>CLI</h2>
        <pre className="mono" style={{ margin: 0, fontSize: 13, lineHeight: 1.8, color: "var(--text-3)" }}>{`$ pip install ghostwalk\n$ gw map import ./your-repos\n$ gw why --alerts alerts.json\n$ gw learn INC-1042 --root config-svc`}</pre>
      </section>
      <section className="card" style={{ padding: 20 }}>
        <h2 style={{ margin: "0 0 4px", fontSize: 17 }}>Store</h2>
        <Row k="Backend" v={s.store.label} />
        <Row k="Graph" v={`${s.graph.nodes} nodes · ${s.graph.edges} edges (${s.graph.learned} learned)`} />
        <Row k="Version" v={`v${s.version}`} />
      </section>
      <section className="card" style={{ padding: 20 }}>
        <h2 style={{ margin: "0 0 8px", fontSize: 17 }}>Coming later</h2>
        <ul style={{ margin: 0, paddingLeft: 18, fontSize: 14, color: "var(--text-3)", lineHeight: 1.8 }}>
          <li>MCP server, so coding agents can ask “why” during an incident</li>
          <li>Postmortem import with a language model (proposes edges for review)</li>
          <li>Map discovery from OpenTelemetry traces</li>
        </ul>
      </section>
      <section className="card" style={{ padding: 20, display: "flex", flexWrap: "wrap", gap: 12, alignItems: "center" }}>
        <div style={{ flex: 1 }}><h2 style={{ margin: 0, fontSize: 17 }}>Reset learned edges</h2><p style={{ margin: "2px 0 0", fontSize: 14, color: "var(--text-3)" }}>Returns the graph to the official map. Incident history stays.</p></div>
        <Btn variant="glass" onClick={async () => { if (confirm("Remove every learned edge?")) { await api("/api/settings/reset-learned", { method: "POST" }); reload() } }}>Reset</Btn>
      </section>
    </Page>
  )
}
