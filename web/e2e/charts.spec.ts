import { expect, test } from "@playwright/test"
import fs from "node:fs"
import path from "node:path"

const SHOTS = process.env.SHOTS ?? path.resolve(process.cwd(), "../docs/screenshots")

test("proof page charts (the app is always dark)", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto("/proof")
  await page.waitForSelector('[aria-label="What learning adds"] svg')
  await page.waitForTimeout(400)
  fs.mkdirSync(SHOTS, { recursive: true })
  await page.locator('[aria-label="What learning adds"]').screenshot({ path: path.join(SHOTS, "chart-paired-gain-proof-page.png") })
  await page.locator('[aria-label="Accuracy as it learns"]').screenshot({ path: path.join(SHOTS, "chart-cumulative-proof-page.png") })
  const w = await page.evaluate(() => ({ sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth }))
  expect(w.sw).toBe(w.cw)
  // a phone: the charts scale, nothing scrolls sideways
  await page.setViewportSize({ width: 390, height: 844 })
  await page.waitForTimeout(300)
  const m = await page.evaluate(() => ({ sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth }))
  expect(m.sw).toBe(m.cw)
})

for (const theme of ["light", "dark"] as const) {
  test(`landing tile 'Proves it gets better', ${theme}`, async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 })
    await page.goto("/")
    await page.waitForSelector("h1")
    if (theme === "dark") await page.getByRole("button", { name: /Switch to dark mode/ }).click()
    const tile = page.locator("h3", { hasText: "Proves it gets better" }).locator("..")
    await tile.scrollIntoViewIfNeeded()
    await page.waitForSelector('svg[aria-label^="What learning adds"]')
    await page.waitForTimeout(1200)
    fs.mkdirSync(SHOTS, { recursive: true })
    await tile.screenshot({ path: path.join(SHOTS, `landing-tile-proves-it-${theme}.png`) })
    await expect(tile).toContainText("Each postmortem adds accuracy on companies it never saw. Random postmortems add nothing.")
  })
}
