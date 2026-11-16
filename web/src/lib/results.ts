import { apiUrl } from "./api"
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
  latency?: {
    incidents_per_size: number
    sizes: Record<string, { services: number; edges: number; in_memory_ms: { p50: number; p95: number; p99: number }; reference_walk_ms?: { p95: number }; hydradb_ms: unknown }>
    hydradb: { status: string }
    gate: { p95_1000_ms: number | null; p95_5000_ms: number | null; stopped_at_1000: boolean; rust_port: string }
    meta: { git: string | null; cpus: number }
  }
  scale?: {
    path_query?: { sizes: Record<string, { services: number; edges: number; path_query: Record<string, { hydradb: { p50: number; p95: number; wrong: number }; postgres: { p50: number; p95: number; wrong: number; timeouts: number } }>;
      verdict: { cold_read: { p50: number }; in_db: { p50: number } } }> }
    postgres_verdict?: { sizes: Record<string, { p50: number }> }
  }
  llm_baseline?: { n_incidents: number; arms: Record<string, { ac1: CI }>; paired_ac1: Record<string, CI> }
  paired?: { ac1?: Record<string, CI> }
  baseline_fairness?: { pagerank: { settings: Record<string, unknown>; grid_budget: number | null; dev_ac1_tuned: number | null; dev_ac1_untuned_default: number | null } }
}

export const pts = (x: number) => `${x >= 0 ? "+" : "−"}${Math.abs(x * 100).toFixed(1)} pts`
export const pct = (x: number) => `${Math.round(x * 100)}%`
export const ms = (x: number) => (x < 10 ? x.toFixed(1) : Math.round(x).toString())

/** The verdict latency to quote anywhere a number is shown: HydraDB p95 when a HydraDB run exists, else the in-memory p95, and it says which. */
export function verdictLatency(r: Results | null): { text: string; label: string } | null {
  const h = r?.store_swap?.backends?.hydradb?.verdict_ms_p95
  if (typeof h === "number") return { text: `${ms(h)} ms`, label: "HydraDB p95" }
  const g = r?.ops?.ghostwalk
  if (g && typeof g === "object") return { text: `${ms(g.verdict_ms_p95)} ms`, label: "in-memory p95" }
  return null
}

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
  const lat = verdictLatency(r)
  if (lat) out.push({ label: "p95 time to a verdict", value: lat.text, note: lat.label })
  const kv = r.store_swap?.backends?.kv_1hop?.delta_vs_reference
  if (r.store_swap && kv) {
    const ref = r.store_swap.reference === "hydradb" ? "HydraDB" : "the in-memory graph"
    out.push({ label: `with ${ref} swapped for a key-value store`, value: pts(kv.point), note: `95% CI ${pts(kv.ci95[0])} to ${pts(kv.ci95[1])}` })
  }
  return out
}

export type Gain = { key: string; value: string; label: string; sub: string; href: string }
export const GAIN_TIP = "pts = percentage points of top-1 accuracy (AC@1)"
const gp = (x: number) => `${x >= 0 ? "+" : "-"}${Math.abs(x * 100).toFixed(1)} pts`

/** The gain stats shown in the hero and on the dashboard, in percentage points, all derived from results.json. Nothing is typed here.
 *  The LLM stat appears only if the paired 95% interval of GhostWalk minus the better LLM arm excludes 0; otherwise the gain over the best baseline takes its place. */
export function gainStats(r: Results | null): Gain[] {
  if (!r?.methods) return []
  const out: Gain[] = []
  const llm = r.llm_baseline
  let llmShown = false
  if (llm?.arms) {
    const arms = Object.keys(llm.arms).filter((k) => k.startsWith("llm_") && llm.paired_ac1?.[`ghostwalk_minus_${k}`])
    const best = arms.sort((a, b) => llm.arms[b].ac1.point - llm.arms[a].ac1.point)[0]
    const d = best ? llm.paired_ac1[`ghostwalk_minus_${best}`] : null
    if (d && d.ci95[0] > 0) {
      out.push({ key: "llm", value: gp(d.point), label: "vs an LLM", sub: `same ${llm.n_incidents} incidents, Gemini/Groq`, href: "#cmp-llm" })
      llmShown = true
    }
  }
  if (!llmShown && r.headline?.gain_vs_best) {
    const g = r.headline.gain_vs_best
    out.push({ key: "baseline", value: gp(g.point), label: "vs best baseline (tuned PageRank)", sub: `95% CI ${gp(g.ci95[0])} to ${gp(g.ci95[1])}`, href: "#cmp-pagerank" })
  }
  const swap = r.store_swap?.backends
  for (const [k, label, id] of [["kv_1hop", "vs a key-value store", "cmp-kv"], ["pgvector", "vs a vector store", "cmp-vector"]] as const) {
    const d = swap?.[k]?.delta_vs_reference
    if (d) out.push({ key: k, value: gp(-d.point), label, sub: "same engine, store swapped", href: `#${id}` })
  }
  const learn = r.paired?.ac1?.["ghostwalk - learning_off"]
  if (learn) {
    const pl = r.methods.placebo?.ac1?.point, off = r.methods.learning_off?.ac1?.point
    out.push({ key: "learning", value: gp(learn.point), label: "from learning", sub: pl != null && off != null ? `placebo: ${gp(pl - off)}` : "", href: "#learning" })
  }
  const vm = (r.ops as any)?.vm?.minio?.online_loop?.verdict_ms?.p50
  const lat = typeof vm === "number" ? { v: vm, sub: "AWS VM, HydraDB on MinIO" } : (() => { const h = r.store_swap?.backends?.hydradb as any; return h?.verdict_ms_p50 != null ? { v: h.verdict_ms_p50 as number, sub: "HydraDB, laptop" } : null })()
  if (lat) out.push({ key: "latency", value: `${ms(lat.v)} ms`, label: "verdict p50", sub: lat.sub, href: "#latency" })
  return out
}

export const METHOD_LABEL: Record<string, string> = {
  ghostwalk: "GhostWalk", pagerank: "Personalized PageRank", retrieval: "Postmortem retrieval", deepest: "Deepest alert", random: "Random",
  oracle: "Perfect map", learning_off: "Learning off", placebo: "Placebo postmortems",
}

export async function loadResults(): Promise<Results | null> {
  try {
    const r = await fetch(apiUrl("/api/proof"))
    return r.ok ? ((await r.json()) as Results) : null
  } catch {
    return null
  }
}
