import { proofStrip, pts, type Results } from "./results"

const base = (over: Partial<Results> = {}) => ({
  meta: {}, methods: {},
  headline: { best_baseline: "pagerank", gain_vs_best: { point: 0.123, ci95: [0.05, 0.2], baseline: "pagerank" }, gap_closed: { point: 0.4, ci95: [0.3, 0.5] } },
  ...over,
}) as unknown as Results

test("strip values come from the file", () => {
  const s = proofStrip(base())
  expect(s[0].value).toBe("+12.3 pts")
  expect(s[1].value).toBe("40%")
  const s2 = proofStrip(base({ headline: { best_baseline: "x", gain_vs_best: { point: 0.01, ci95: [0, 0.02], baseline: "x" }, gap_closed: { point: 0.9, ci95: [0.8, 1] } } }))
  expect(s2[0].value).toBe("+1.0 pts")
})

test("latency and store-swap tiles appear only when their runs exist", () => {
  expect(proofStrip(base()).length).toBe(2)
  const withOps = base({ ops: { ghostwalk: { verdict_ms_p95: 2.134, verdict_ms_p50: 0.4, mean_checks_to_root: 2, n: 5 } } })
  expect(proofStrip(withOps).map((t) => t.value)).toContain("2.1 ms")
  const swap = base({ store_swap: { reference: "inmemory", hydradb: { status: "not run" }, backends: { kv_1hop: { description: "", ac1: { point: 0.6, ci95: [0.5, 0.7] }, delta_vs_reference: { point: -0.134, ci95: [-0.17, -0.1] }, verdict_ms_p95: 1 } } } })
  const t = proofStrip(swap).at(-1)!
  expect(t.value).toBe("−13.4 pts")
  expect(t.label).toContain("in-memory")
})

test("no results, no tiles", () => {
  expect(proofStrip(null)).toEqual([])
  expect(pts(-0.05)).toBe("−5.0 pts")
})
