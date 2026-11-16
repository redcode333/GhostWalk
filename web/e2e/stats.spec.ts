import { expect, test } from "@playwright/test"
import fs from "node:fs"
import path from "node:path"

const SHOTS = process.env.SHOTS ?? path.resolve(process.cwd(), "../docs/screenshots")
const PREFIX = process.env.SHOT_PREFIX ?? "local"

test("hero leads with the gains, in percentage points, each linking to the Proof page", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto("/")
  await page.waitForSelector("h1")
  const list = page.getByRole("list", { name: /Gains/ }).first()
  await expect(list).toBeVisible()
  const text = (await list.innerText()).replace(/\s+/g, " ")
  console.log("  hero stats:", text)
  expect(text).toMatch(/\+\d+\.\d pts/)
  expect(text).not.toMatch(/\d%\s+(better|more|higher|improvement|relative)/i)   // never a relative percentage; gains are in pts
  expect(text).toContain("vs a key-value store")
  expect(text).toContain("vs a vector store")
  expect(text).toContain("from learning")
  const links = await list.locator("a").evaluateAll((as) => as.map((a) => [(a as HTMLAnchorElement).getAttribute("href"), (a as HTMLAnchorElement).title]))
  expect(links.every(([h, t]) => String(h).startsWith("/proof#") && String(t).includes("percentage points"))).toBe(true)
  fs.mkdirSync(SHOTS, { recursive: true })
  await page.screenshot({ path: path.join(SHOTS, `${PREFIX}-hero-gains-1440x900.png`) })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto("/")
  await page.waitForSelector("h1")
  expect(await page.evaluate(() => document.documentElement.scrollWidth === document.documentElement.clientWidth)).toBe(true)
  await page.screenshot({ path: path.join(SHOTS, `${PREFIX}-hero-gains-390x844.png`) })
})

test("a stat opens its row on the Proof page", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto("/")
  await page.getByRole("list", { name: /Gains/ }).first().getByRole("link", { name: /key-value/ }).click()
  await page.waitForURL(/\/app\/proof#cmp-kv/)
  await expect(page.locator("#cmp-kv")).toBeVisible()
  await page.waitForTimeout(500)
  const top = await page.evaluate(() => document.getElementById("cmp-kv")!.getBoundingClientRect().top)
  expect(top).toBeLessThan(400)                                          // scrolled to the row
})

test("dashboard leads with the same gains", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto("/demo")
  await page.waitForURL(/\/app\/incidents/)
  const list = page.getByRole("list", { name: /Gains/ }).first()
  await expect(list).toBeVisible()
  expect(await list.innerText()).toMatch(/\+\d+\.\d pts/)
  expect(await page.locator("body").innerText()).not.toContain("Top-1 correct")
  await page.screenshot({ path: path.join(SHOTS, `${PREFIX}-dashboard-gains-1440x900.png`) })
})
