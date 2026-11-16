import { cleanup, render, screen } from "@testing-library/react"
import { afterEach, expect, test, vi } from "vitest"
import { MemoryRouter, Route, Routes } from "react-router-dom"
import { AuthProvider, SignUpPage } from "./Auth"

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

test("AUTH_MODE=none offers the shared demo without fake credentials or OAuth", async () => {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const path = new URL(String(input), window.location.origin).pathname
    return path === "/api/config"
      ? new Response(JSON.stringify({ auth_mode: "none", clerk_publishable_key: null }), { status: 200 })
      : new Response("not found", { status: 404 })
  })
  vi.stubGlobal("fetch", fetchMock)
  render(<MemoryRouter initialEntries={["/signup"]}><AuthProvider><Routes><Route path="/signup" element={<SignUpPage />} /></Routes></AuthProvider></MemoryRouter>)
  expect(await screen.findByText("Shared workspace.")).toBeTruthy()
  expect(screen.getByText(/This server has sign-in disabled/)).toBeTruthy()
  expect(screen.getByRole("link", { name: "Explore the sample workspace" })).toBeTruthy()
  expect(screen.queryByPlaceholderText("you@company.com")).toBeNull()
  expect(screen.queryByRole("link", { name: "GitHub" })).toBeNull()
  expect(screen.queryByRole("link", { name: "Google" })).toBeNull()
})
