/** Where the API lives: empty when the page and the API share an origin (the container, the dev proxy), https://<api-domain> on Vercel (VITE_API_URL). */
export const API_BASE: string = ((import.meta as any).env?.VITE_API_URL ?? "").replace(/\/$/, "")
export const apiUrl = (p: string) => (p.startsWith("/") ? API_BASE + p : p)

/** The public demo: set by visiting /demo, cleared by signing in or up. While it is set, requests carry X-GW-Demo and reach the shared sandbox workspace. */
export const demoMode = () => { try { return sessionStorage.getItem("gw_demo") === "1" } catch { return false } }
export const setDemoMode = (on: boolean) => { try { on ? sessionStorage.setItem("gw_demo", "1") : sessionStorage.removeItem("gw_demo") } catch { /* private window */ } }

export async function api<T = any>(path: string, init?: RequestInit & { json?: unknown }): Promise<T> {
  const headers: Record<string, string> = { ...(init?.headers as Record<string, string>) }
  let body = init?.body
  if (init?.json !== undefined) { headers["content-type"] = "application/json"; body = JSON.stringify(init.json) }
  const tok = (window as any).__gwToken?.()
  const t = tok && !demoMode() ? await tok : null
  if (t) headers.authorization = `Bearer ${t}`
  else if (demoMode()) headers["x-gw-demo"] = "1"
  const r = await fetch(apiUrl(path), { ...init, headers, body })
  if (!r.ok) {
    let msg = r.statusText
    try { const j = await r.json(); msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail) } catch { /* keep statusText */ }
    throw new Error(msg)
  }
  return r.json()
}

export const ago = (ts: number) => {
  const s = Math.max(0, Date.now() / 1000 - ts)
  if (s < 3600) return `${Math.max(1, Math.round(s / 60))}m ago`
  if (s < 86400) return `${Math.round(s / 3600)}h ago`
  return new Date(ts * 1000).toLocaleDateString("en", { month: "short", day: "2-digit" })
}
