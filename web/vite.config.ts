import { defineConfig } from "vitest/config"
import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"
import path from "node:path"

const api = process.env.GW_API ?? "http://127.0.0.1:8000"
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(__dirname, "src") } },
  server: { port: 5173, proxy: { "/api": api, "/v1": api, "/results.json": api } },
  test: { environment: "jsdom", globals: true },
})
