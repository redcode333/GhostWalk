import { api } from "./api"

export type Demo = {
  ms: number
  search: { query: string[]; matches: { incident: string; root: string }[] }
  blast: string[]
  nodes: { id: number; name: string; kind: string; tier: number; alerting: boolean }[]
  edges: { u: number; v: number; origin: string }[]
  learned_edges: { u: number; v: number; w: number }[]
  before: { ranking: { id: number; name: string; confidence: number }[]; path: { u: number; v: number; origin: string }[] }
  after: { ranking: { id: number; name: string; confidence: number }[]; path: { u: number; v: number; origin: string }[] }
  changes: { index: number; symbol: string; text: string; detail: string; apply?: boolean }[]
  alerts: number
}
let cache: Promise<Demo | null> | null = null
/** The landing page's demo scenario, computed by the real engine. One request shared by every section; null if the API is down. */
export const loadDemo = () => (cache ??= api<Demo>("/api/demo/inside").catch(() => null))
