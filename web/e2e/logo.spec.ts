import { expect, test } from "@playwright/test"
import fs from "node:fs"
import path from "node:path"

const FRAMES = process.env.LOGO_FRAMES

test("the logo plays its sequence once, replays on hover without restarting mid-play, and is static under reduced motion", async ({ page }) => {
  await page.setViewportSize({ width: FRAMES ? 780 : 600, height: 240 })
  await page.goto("/dev/logo.html")
  const mark = page.locator("svg").first()
  await expect(mark).toHaveAttribute("aria-hidden", "true")
  await expect(page.getByRole("link", { name: "GhostWalk home" })).toBeVisible()
  const anims = await page.evaluate(() => document.getAnimations().filter((a) => (a as CSSAnimation).animationName?.startsWith("lg-")).map((a) => (a as CSSAnimation).animationName))
  for (const n of ["lg-rise", "lg-blink", "lg-draw", "lg-pop", "lg-in", "lg-fade", "lg-ring", "lg-sweep"]) expect(anims).toContain(n)
  expect(anims.filter((n) => n === "lg-in").length).toBe(3)                               // three trail steps
  const total = await page.evaluate(() => Math.max(...document.getAnimations().filter((a) => { const n = (a as CSSAnimation).animationName; return n.startsWith("lg-") && n !== "lg-idle" }).map((a) => a.effect!.getComputedTiming().endTime as number)))
  expect(total).toBeGreaterThan(1500); expect(total).toBeLessThan(1700)                       // about 1.6 s end to end
  await page.waitForFunction(() => !document.getAnimations().some((a) => { const n = (a as CSSAnimation).animationName; return n.startsWith("lg-") && n !== "lg-idle" && a.playState === "running" }), null, { timeout: 5000 })
  const startedAt = async () => page.evaluate(() => document.querySelector(".lg-g") && performance.now())
  const playing = () => page.evaluate(() => document.getAnimations().some((a) => { const n = (a as CSSAnimation).animationName; return n.startsWith("lg-") && n !== "lg-idle" && a.playState === "running" }))
  expect(await playing()).toBe(false)                                                      // finished
  await page.getByRole("link").hover()
  await page.waitForTimeout(200)
  expect(await playing()).toBe(true)                                                       // replays on hover
  const t1 = await page.evaluate(() => (document.getAnimations().find((a) => (a as CSSAnimation).animationName === "lg-draw")!.currentTime as number))
  await page.mouse.move(5, 5); await page.getByRole("link").hover()                       // hover again mid-play
  const t2 = await page.evaluate(() => (document.getAnimations().find((a) => (a as CSSAnimation).animationName === "lg-draw")!.currentTime as number))
  expect(t2).toBeGreaterThanOrEqual(t1)                                                    // not restarted
  void startedAt

  if (FRAMES) {                                                                            // deterministic frames for the GIF: seek every animation to t, then screenshot
    fs.mkdirSync(FRAMES, { recursive: true })
    await page.reload(); await page.waitForTimeout(300)
    for (let i = 0, t = 0; t <= 1800; i++, t += 50) {
      await page.evaluate((t) => document.getAnimations().forEach((a) => { a.pause(); a.currentTime = t }), t)
      await page.screenshot({ path: path.join(FRAMES, `f${String(i).padStart(3, "0")}.png`) })
    }
  }
})

test("reduced motion shows the final static state", async ({ browser }) => {
  const ctx = await browser.newContext({ reducedMotion: "reduce", viewport: { width: 600, height: 240 } })
  const page = await ctx.newPage()
  await page.goto("/dev/logo.html")
  await page.waitForTimeout(300)
  const running = await page.evaluate(() => document.getAnimations().filter((a) => (a as CSSAnimation).animationName?.startsWith("lg-")).length)
  expect(running).toBe(0)
  await ctx.close()
})

test("the navbar logo plays on load; the sidebar logo plays only on the first load per session", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto("/")
  await page.waitForSelector("h1")
  await expect(page.locator("header a[aria-label='GhostWalk home'] .lg-on").first()).toBeAttached()
  await page.goto("/demo")
  await page.waitForURL(/\/app\/incidents/)
  const side = page.locator("aside a[aria-label='GhostWalk home'] span").first()
  await expect(side).toHaveClass(/lg-on/)                                     // first load of the session: plays
  await page.reload()
  await page.waitForSelector("aside a[aria-label='GhostWalk home']")
  await expect(page.locator("aside a[aria-label='GhostWalk home'] span").first()).not.toHaveClass(/lg-on/)   // same session: the static final frame
})
