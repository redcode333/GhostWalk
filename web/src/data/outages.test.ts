import { OUTAGES, savedM, CLOUDFLARE } from "./outages"

test("the slider follows the spec: (275/190) x (190 - N) $M", () => {
  expect(savedM(15)).toBeCloseTo((275 / 190) * 175, 6)
  expect(savedM(190)).toBe(0)
  expect(CLOUDFLARE.midM).toBe((CLOUDFLARE.lowM + CLOUDFLARE.highM) / 2)
})

test("every outage has a source and an honest verification note; costs name their estimator", () => {
  expect(OUTAGES.length).toBe(7)
  for (const o of OUTAGES) {
    expect(o.source).toMatch(/^https:\/\//)
    expect(o.check.length).toBeGreaterThan(10)
    if (o.cost) { expect(o.cost).toMatch(/\((Forrester|Parametrix)\)/); expect(o.costSource).toMatch(/^https:\/\//) }
  }
})
