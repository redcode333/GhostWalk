// Types and derivations for results.json. Every number the site shows about accuracy comes through here;
// nothing is hard-coded, and a missing field yields no tile instead of an invented value.
export type CI = { point: number; ci95: [number, number] }
export type Results = {
  meta: { split: string; companies: number; incidents: number; timestamp_utc: string; git: { short: string; dirty: boolean }; seeds: Record<string, unknown> }
  methods: Record<string, Record<string, CI>>
  headline: {
    best_baseline: string
    gain_vs_best: CI & { baseline: string }
    gap_closed: CI
  }
  repeat_vs_novel?: { definition: string; methods: Record<string, { repeat: CI; novel: CI }> }
  learning_curve?: { bin: number; series: Record<string, { from: number; to: number; ac1: number; ci95: [number, number] }[]> }
  learning_metrics?: { series: { after: number; recall: number | null; precision: number | null }[]; false_edges: Record<string, number | string> }
  poisoning?: { levels: Record<string, { wrong_pm: number; ghostwalk: CI; learning_off: CI; gain: CI }> }
  ops?: Record<string, { verdict_ms_p50: number; verdict_ms_p95: number; mean_checks_to_root: number; n: number } | string | null>
  store_swap?: {
    reference: string
    hydradb: { status: string }
    backends: Record<string, { description: string; ac1: CI; delta_vs_reference: CI | null; verdict_ms_p95: number }>
  }
  change_evidence?: {
    settings: { gamma: number; tau_min: number }; helps_only_when: string; note: string
    main: { without: CI; with: CI; gain: CI & { p_le_0: number } }
    sensitivity: { p_root: number; r_noise: number; without: CI; with: CI; gain: CI }[]
  }
  baseline_fairness?: { pagerank: { settings: Record<string, unknown>; grid_budget: number | null; dev_ac1_tuned: number | null; dev_ac1_untuned_default: number | null } }
}

export const pts = (x: number) => `${x >= 0 ? "+" : "−"}${Math.abs(x * 100).toFixed(1)} pts`
export const pct = (x: number) => `${Math.round(x * 100)}%`
export const ms = (x: number) => (x < 10 ? x.toFixed(1) : Math.round(x).toString())

export type Strip = { label: string; value: string; note?: string }[]

/** The proof-strip tiles. The store-swap tile exists only when a real store-swap run is in the file. */
export function proofStrip(r: Results | null): Strip {
  if (!r?.headline) return []
  const out: Strip = [
    { label: `top-1 accuracy over the best baseline (${r.headline.gain_vs_best.baseline})`, value: pts(r.headline.gain_vs_best.point),
      note: `95% CI ${pts(r.headline.gain_vs_best.ci95[0])} to ${pts(r.headline.gain_vs_best.ci95[1])}, paired` },
    { label: "of the gap to a perfect map closed by learning", value: pct(r.headline.gap_closed.point),
      note: `95% CI ${pct(r.headline.gap_closed.ci95[0])} to ${pct(r.headline.gap_closed.ci95[1])}` },
  ]
  const gw = r.ops?.ghostwalk
  if (gw && typeof gw === "object") out.push({ label: "p95 time to a verdict", value: `${ms(gw.verdict_ms_p95)} ms`, note: String(r.ops?.backend ?? "") })
  const kv = r.store_swap?.backends?.kv_1hop?.delta_vs_reference
  if (r.store_swap && kv) {
    const ref = r.store_swap.reference === "hydradb" ? "HydraDB" : "the in-memory graph"
    out.push({ label: `with ${ref} swapped for a key-value store`, value: pts(kv.point), note: `95% CI ${pts(kv.ci95[0])} to ${pts(kv.ci95[1])}` })
  }
  return out
}

export const METHOD_LABEL: Record<string, string> = {
  ghostwalk: "GhostWalk", pagerank: "Personalized PageRank", retrieval: "Postmortem retrieval", deepest: "Deepest alert", random: "Random",
  oracle: "Perfect map", learning_off: "Learning off", placebo: "Placebo postmortems",
}

export async function loadResults(): Promise<Results | null> {
  try {
    const r = await fetch("/api/proof")
    return r.ok ? ((await r.json()) as Results) : null
  } catch {
    return null
  }
}
