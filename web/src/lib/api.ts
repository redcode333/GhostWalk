export async function api<T = any>(path: string, init?: RequestInit & { json?: unknown }): Promise<T> {
  const headers: Record<string, string> = { ...(init?.headers as Record<string, string>) }
  let body = init?.body
  if (init?.json !== undefined) { headers["content-type"] = "application/json"; body = JSON.stringify(init.json) }
  const tok = (window as any).__gwToken?.()
  const t = tok ? await tok : null
  if (t) headers.authorization = `Bearer ${t}`
  const r = await fetch(path, { ...init, headers, body })
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
