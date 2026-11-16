import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, expect, test, vi } from "vitest"
import { MemoryRouter } from "react-router-dom"
import { setDemoMode } from "@/lib/api"
import { alertWebhookExample, default as Onboarding } from "./Onboarding"

afterEach(() => { cleanup(); setDemoMode(false); vi.unstubAllGlobals() })

test("authenticated webhook examples include the workspace token header", () => {
  const required = alertWebhookExample("Grafana", "https://gw.example/v1/alerts/acme", true).cmd
  const open = alertWebhookExample("Any webhook", "http://localhost:8000/v1/alerts/acme", false).cmd
  expect(required).toContain("Authorization: Bearer <workspace-token>")
  expect(open).not.toContain("Authorization:")
})

test("public demo explains the read-only setup boundary and does not send blocked onboarding writes", async () => {
  setDemoMode(true)
  const responses: Record<string, unknown> = {
    "/api/onboarding": { steps: { github: false, map: false, alert: false, postmortem: false }, proposals: null, installation: null, summary: { services: 80, scored: 0, learned_edges: 0 } },
    "/api/config": { auth_mode: "clerk", github: { configured: true, webhook_configured: true, slug: "ghostwalk" } },
    "/api/settings": { webhook_url: "https://gw.example/v1/alerts/acme", token_required: true },
  }
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = new URL(String(input), window.location.origin).pathname
    return new Response(JSON.stringify(responses[path]), { status: 200, headers: { "content-type": "application/json" } })
  })
  vi.stubGlobal("fetch", fetchMock)
  render(<MemoryRouter initialEntries={["/app/onboarding"]}><Onboarding /></MemoryRouter>)
  expect(await screen.findByText(/This is the public sample workspace/)).toBeTruthy()
  expect((screen.getByRole("button", { name: "Install the GitHub App" }) as HTMLButtonElement).disabled).toBe(true)
  expect((screen.getByRole("button", { name: "Scan sample repository files" }) as HTMLButtonElement).disabled).toBe(true)
  expect((screen.getByRole("button", { name: "Load a sample company" }) as HTMLButtonElement).disabled).toBe(true)
  expect((screen.getByRole("button", { name: "Send test alert" }) as HTMLButtonElement).disabled).toBe(true)
  await waitFor(() => expect(fetchMock.mock.calls.every((call) => call[1]?.method !== "POST")).toBe(true))
})
