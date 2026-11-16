import { defineConfig } from "vitest/config"
import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"
import path from "node:path"

const api = process.env.GW_API ?? "http://127.0.0.1:8000"
const REPO = process.env.GW_REPO ?? "redcode333/GhostWalk"

/** GitHub star count, fetched once at build time. Any failure (offline, private repo, rate limit) gives null and the UI hides it. */
async function stars(): Promise<number | null> {
  try {
    const r = await fetch(`https://api.github.com/repos/${REPO}`, { signal: AbortSignal.timeout(4000), headers: { accept: "application/vnd.github+json" } })
    if (!r.ok) return null
    const n = (await r.json()).stargazers_count
    return typeof n === "number" ? n : null
  } catch {
    return null
  }
}

export default defineConfig(async () => ({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(__dirname, "src") } },
  define: { __GH_STARS__: JSON.stringify(await stars()) },
  server: { port: 5173, proxy: { "/api": api, "/v1": api, "/results.json": api } },
  test: { environment: "jsdom", globals: true, exclude: ["node_modules/**", "e2e/**"] },
}))
