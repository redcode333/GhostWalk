import { expect, test } from "@playwright/test"
import fs from "node:fs"
import path from "node:path"

const SHOTS = process.env.SHOTS ?? path.resolve(process.cwd(), "../docs/screenshots")
const VIEWPORTS = [{ w: 1440, h: 900 }, { w: 1366, h: 768 }, { w: 390, h: 844 }]

for (const v of VIEWPORTS) {
  test(`hero ${v.w}x${v.h}: the globe rises above the fold, nothing scrolls sideways, no stray scrollbar`, async ({ page }) => {
    await page.setViewportSize({ width: v.w, height: v.h })
    await page.goto("/")
    await page.waitForSelector("h1")
    await page.waitForTimeout(2500)                                           // let the WebGL globe draw
    fs.mkdirSync(SHOTS, { recursive: true })
    await page.screenshot({ path: path.join(SHOTS, `${process.env.SHOT_PREFIX ?? "hero"}-${v.w}x${v.h}.png`) })
    // no horizontal page scroll
    const m = await page.evaluate(() => ({ sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth }))
    expect(m.sw, "document.documentElement.scrollWidth equals clientWidth").toBe(m.cw)
    // the header has no scrolling element inside it
    const scrolling = await page.evaluate(() => [...document.querySelectorAll("header *")].filter((e) => {
      const s = getComputedStyle(e as HTMLElement)
      return /(auto|scroll)/.test(s.overflowX + s.overflowY) && ((e as HTMLElement).scrollHeight > (e as HTMLElement).clientHeight + 1 || (e as HTMLElement).scrollWidth > (e as HTMLElement).clientWidth + 1)
    }).map((e) => e.tagName + "." + (e as HTMLElement).className))
    expect(scrolling, "no element in the header scrolls").toEqual([])
    // the globe: how much of its container is inside the first screen
    const g = await page.evaluate(() => {
      const el = document.querySelector("#outages canvas, #outages [data-globe]") as HTMLElement | null
      const box = (document.querySelector("#outages") as HTMLElement).getBoundingClientRect()
      const c = el?.getBoundingClientRect()
      return { containerTop: box.top, canvasTop: c?.top ?? null, canvasH: c?.height ?? null, vh: window.innerHeight }
    })
    console.log(`  ${v.w}x${v.h}: globe container top ${Math.round(g.containerTop)} px, canvas top ${g.canvasTop == null ? "n/a" : Math.round(g.canvasTop)} px, viewport ${g.vh} px`)
    if (v.w >= 1000) expect(g.vh - g.containerTop, "at least about 200 px of the globe area is on the first screen").toBeGreaterThanOrEqual(200)
  })
}

test("no horizontal scroll at any common width", async ({ page }) => {
  for (const w of [320, 360, 390, 414, 768, 1024, 1280, 1440, 1920]) {
    await page.setViewportSize({ width: w, height: 800 })
    await page.goto("/")
    await page.waitForSelector("h1")
    const m = await page.evaluate(() => ({ sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth }))
    expect(m.sw, `width ${w}`).toBe(m.cw)
  }
})
