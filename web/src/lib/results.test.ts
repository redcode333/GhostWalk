import { gainStats, proofStrip, pts, verdictLatency, type Results } from "./results"

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

test("the latency quoted is HydraDB p95 when a HydraDB run exists, and it says which", () => {
  const ops = { ghostwalk: { verdict_ms_p95: 2.0, verdict_ms_p50: 0.4, mean_checks_to_root: 2, n: 5 } }
  const mem = base({ ops })
  expect(verdictLatency(mem)).toEqual({ text: "2.0 ms", label: "in-memory p95" })
  const hy = base({ ops, store_swap: { reference: "hydradb", hydradb: { status: "ok" }, backends: { hydradb: { description: "", ac1: { point: 0.7, ci95: [0.6, 0.8] }, delta_vs_reference: null, verdict_ms_p95: 31.4 } } } })
  expect(verdictLatency(hy)).toEqual({ text: "31 ms", label: "HydraDB p95" })
  expect(verdictLatency(null)).toBeNull()
})

describe("gainStats", () => {
  const mk = (llmCi: [number, number]) => ({
    meta: { split: "test", companies: 30, incidents: 1800, timestamp_utc: "", git: { short: "x", dirty: false }, seeds: {} },
    methods: { ghostwalk: { ac1: { point: 0.76, ci95: [0.74, 0.78] } }, learning_off: { ac1: { point: 0.68, ci95: [0.64, 0.71] } }, placebo: { ac1: { point: 0.69, ci95: [0.65, 0.72] } } },
    headline: { best_baseline: "pagerank", gain_vs_best: { point: 0.065, ci95: [0.036, 0.098], baseline: "pagerank" }, gap_closed: { point: 0.5, ci95: [0.4, 0.6] } },
    paired: { ac1: { "ghostwalk - learning_off": { point: 0.089, ci95: [0.057, 0.124] } } },
    store_swap: { reference: "hydradb", hydradb: { status: "ok" }, backends: { kv_1hop: { description: "", ac1: { point: 0.63, ci95: [0.6, 0.66] }, delta_vs_reference: { point: -0.135, ci95: [-0.17, -0.1] }, verdict_ms_p95: 3 },
      pgvector: { description: "", ac1: { point: 0.39, ci95: [0.35, 0.43] }, delta_vs_reference: { point: -0.376, ci95: [-0.4, -0.35] }, verdict_ms_p95: 3 }, hydradb: { description: "", ac1: { point: 0.76, ci95: [0.74, 0.78] }, delta_vs_reference: null, verdict_ms_p95: 3 } } },
    llm_baseline: { n_incidents: 58, arms: { llm_plain: { ac1: { point: 0.57, ci95: [0.4, 0.7] } }, llm_memory: { ac1: { point: 0.67, ci95: [0.5, 0.8] } } },
      paired_ac1: { ghostwalk_minus_llm_plain: { point: 0.155, ci95: [0.034, 0.273] }, ghostwalk_minus_llm_memory: { point: 0.052, ci95: llmCi } } },
  }) as unknown as Results

  it("shows the LLM gain only when the paired interval of the better LLM arm excludes zero", () => {
    expect(gainStats(mk([0.01, 0.1])).map((s) => s.key)).toEqual(["llm", "kv_1hop", "pgvector", "learning"])
    const s = gainStats(mk([-0.05, 0.15]))
    expect(s[0].key).toBe("baseline")                           // the better arm (memory) includes 0, so the baseline gain takes its place
    expect(s[0].value).toBe("+6.5 pts")
  })
  it("states gains in percentage points, positive, from the store swap and learning", () => {
    const s = Object.fromEntries(gainStats(mk([-0.05, 0.15])).map((x) => [x.key, x]))
    expect(s.kv_1hop.value).toBe("+13.5 pts"); expect(s.pgvector.value).toBe("+37.6 pts"); expect(s.learning.value).toBe("+8.9 pts")
    expect(s.learning.sub).toBe("placebo: +1.0 pts")
    expect(gainStats(mk([-0.05, 0.15])).every((x) => !x.value.includes("%"))).toBe(true)
  })
  it("returns nothing without results", () => expect(gainStats(null)).toEqual([]))
})
