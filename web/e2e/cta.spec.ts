import { expect, test } from "@playwright/test"
import fs from "node:fs"
import path from "node:path"

const SHOTS = process.env.SHOTS ?? path.resolve(process.cwd(), "../docs/screenshots")

for (const v of [{ w: 1440, h: 900 }, { w: 390, h: 844 }]) {
  test(`final CTA ${v.w}: 24 to 32 px between the licence line and the buttons`, async ({ page }) => {
    await page.setViewportSize({ width: v.w, height: v.h })
    await page.goto(process.env.BASE_URL ? process.env.BASE_URL : "/")
    await page.waitForSelector("h1")
    const line = page.getByText("Free and open source. MIT licensed.", { exact: true })
    await line.scrollIntoViewIfNeeded()
    const gap = await page.evaluate(() => {
      const p = [...document.querySelectorAll("p")].find((e) => e.textContent === "Free and open source. MIT licensed.") as HTMLElement
      const row = p.nextElementSibling as HTMLElement
      return row.getBoundingClientRect().top - p.getBoundingClientRect().bottom
    })
    console.log(`  ${v.w}px: gap ${gap.toFixed(1)} px`)
    expect(gap).toBeGreaterThanOrEqual(24)
    expect(gap).toBeLessThanOrEqual(32)
    fs.mkdirSync(SHOTS, { recursive: true })
    await page.locator("h2", { hasText: "Your next outage" }).locator("..").screenshot({ path: path.join(SHOTS, `cta-${v.w}.png`) })
  })
}
