import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react"
import { afterEach, expect, test, vi } from "vitest"

const demo = {
  ms: 0.2, alerts: 5, blast: ["checkout-api"], search: { query: [], matches: [] },
  nodes: [{ id: 0, name: "web-edge", kind: "edge", tier: 0, alerting: true }, { id: 1, name: "fraud-check", kind: "service", tier: 1, alerting: true }, { id: 2, name: "config-svc", kind: "infra", tier: 3, alerting: true }],
  edges: [{ u: 0, v: 1, origin: "official" }], learned_edges: [{ u: 1, v: 2, w: 0.7 }],
  before: { ranking: [{ id: 1, name: "fraud-check", confidence: 0.8 }, { id: 2, name: "config-svc", confidence: 0.1 }], path: [] },
  after: { ranking: [{ id: 2, name: "config-svc", confidence: 0.94 }, { id: 1, name: "fraud-check", confidence: 0.05 }], path: [] },
  changes: [{ index: 1, symbol: "+", text: "fraud-check ⇢ config-svc", detail: "tentative 0.35", apply: true }],
}

afterEach(cleanup)

test("applying the lesson in Learn re-sorts the Investigate ranking (shared state)", async () => {
  vi.resetModules()
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(demo), { status: 200 })))
  const { InsideGhostWalk } = await import("./InsideGhostWalk")
  const { container } = render(<InsideGhostWalk />)
  await screen.findByText("Investigate")
  const names = () => [...container.querySelectorAll("[role=listitem]")].map((e) => e.textContent ?? "")
  expect(names()[0]).toContain("fraud-check")
  fireEvent.click(screen.getByText("Apply"))
  await waitFor(() => expect(screen.getByText("Applied ✓")).toBeTruthy())
  expect(names()[0]).toContain("config-svc")
})

test("tabs bring a panel to the front; hovering a candidate does not crash", async () => {
  vi.resetModules()
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(demo), { status: 200 })))
  const { InsideGhostWalk } = await import("./InsideGhostWalk")
  const { container } = render(<InsideGhostWalk />)
  await screen.findByText("Map")
  fireEvent.click(screen.getByRole("tab", { name: "Map" }))
  const front = container.querySelector('.stack-panel[data-slot="0"]')!
  expect(front.textContent).toContain("Dependency map")
  fireEvent.click(screen.getByRole("tab", { name: "Investigate" }))
  fireEvent.mouseEnter(container.querySelector("[role=listitem]")!)
})
