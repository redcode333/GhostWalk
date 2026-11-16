"""LLM baseline on a fixed 100-incident subset of the TEST split.

    python eval/llm_baseline.py [--minutes 90]          # keys come from .env (GEMINI_API_KEY, GROQ_API_KEY); they are never printed, logged or cached

LLM baseline: Gemini with Groq fallback on rate limits (the model is recorded per incident). GhostWalk itself uses no LLM.

Subset: 100 TEST incidents, stratified by company (three per company, one early / middle / late, and a fourth for ten seeded companies), chosen with a fixed seed and saved to
eval/llm_subset.json BEFORE any call. Arms, on the same incidents:
  llm_plain   the alerts in firing order + the company's OFFICIAL map as text
  llm_memory  the same + the five most similar PAST postmortems of that company (TF-IDF over the alert text; never a future incident)
Gemini first; on a rate or daily-limit error that incident is retried on Groq. temperature 0; strict JSON {"ranking": [five service names], "reason": "..."}; one retry on bad JSON, then it is a miss.
Every response is cached in eval/llm_cache/ (no keys in it). Compared with ghostwalk, learning_off and TF-IDF retrieval on the same incidents, with paired cluster bootstrap CIs.
Writes results.json "llm_baseline" (and the LLM token figures in ops). Hard stop after --minutes; whatever is complete is published with its n."""
from __future__ import annotations
import argparse, hashlib, json, os, pathlib, random, sys, time, types
import numpy as np
import httpx

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from eval.runner import load, run_company
from eval.full_eval import bootstrap
from eval.memory_retrieval import tfidf_top
from gwsim.world import official_view

SUBSET = ROOT / "eval" / "llm_subset.json"
CACHE = ROOT / "eval" / "llm_cache"
SEED = 20261117
GEMINI_MODEL = "gemini-3.5-flash"
GROQ_MODEL = "openai/gpt-oss-120b"
LABEL = "LLM baseline: Gemini with Groq fallback on rate limits (model recorded per incident). GhostWalk itself uses no LLM."
SYSTEM = "You are an experienced site reliability engineer doing root cause analysis. Answer with strict JSON only."


def env():
    e = dict(os.environ)
    p = ROOT / ".env"
    if p.exists():
        for l in p.read_text(encoding="utf8").splitlines():
            if "=" in l and not l.strip().startswith("#"):
                k, v = l.split("=", 1)
                e.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return e


# ---------------------------------------------------------------------------------------------- subset
def make_subset(cos):
    if SUBSET.exists():
        return json.loads(SUBSET.read_text(encoding="utf8"))
    rng = random.Random(SEED)
    picks = []
    extra = set(rng.sample([c["name"] for c in cos], 10))
    for c in cos:
        n = len(c["incidents"])
        terciles = [range(1, n // 3), range(n // 3, 2 * n // 3), range(2 * n // 3, n)]          # never incident 0: the memory arm needs a past
        order = [0, 1, 2]
        chosen = [rng.choice(list(terciles[t])) for t in order]
        if c["name"] in extra:
            t = rng.choice(order)
            pool = [i for i in terciles[t] if i not in chosen]
            chosen.append(rng.choice(pool))
        picks += [{"company": c["name"], "index": i, "seq": c["incidents"][i]["seq"]} for i in sorted(chosen)]
    doc = {"seed": SEED, "split": "test", "n": len(picks), "rule": "three per company (one each from the early, middle and late third of its incidents, never the first), plus a fourth for ten seeded companies",
           "incidents": picks}
    SUBSET.write_text(json.dumps(doc, indent=1), encoding="utf8")
    return doc


# ---------------------------------------------------------------------------------------------- prompts
def map_text(co):
    view = official_view(types.SimpleNamespace(components=co["components"], official_edges=co["official_edges"]))
    name = {c["id"]: c["name"] for c in view["components"]}
    deps = {}
    for e in view["edges"]:
        deps.setdefault(e["u"], []).append(name[e["v"]])
    lines = [f"- {c['name']} ({c['kind']}, tier {c['tier']})" + (f" depends on: {', '.join(sorted(deps[c['id']]))}" if c["id"] in deps else "") for c in sorted(view["components"], key=lambda c: c["id"])]
    return "\n".join(lines)


def alerts_text(inc):
    al = sorted(inc["alerts"], key=lambda a: a["t"])
    t0 = al[0]["t"]
    return "\n".join(f"- +{a['t'] - t0:.0f}s {a['name']} ({a.get('signal', 'alert')})" for a in al)


def build_prompt(co, inc, memory):
    parts = ["Service map (the official dependency map; it may be incomplete):", map_text(co)]
    if memory:
        past = [{"seq": p["seq"], "text": p["postmortem_text"]} for p in co["incidents"] if p["seq"] < inc["seq"]]
        q = "alerts: " + " ".join(a["name"] for a in inc["alerts"])
        top = tfidf_top(q, past, 5) if past else []
        by = {p["seq"]: p["text"] for p in past}
        parts += ["", "The five most similar past postmortems of this company:"] + [f"- {by[s]}" for s in top]
    parts += ["", "Alerts, in firing order:", alerts_text(inc), "",
              'Which service is the root cause of these alerts? Reply with JSON only: {"ranking": ["<service>", "<service>", "<service>", "<service>", "<service>"], "reason": "<one or two sentences>"}. '
              "Rank the five most likely root-cause services, most likely first, using only names from the service map."]
    return "\n".join(parts)


# ---------------------------------------------------------------------------------------------- providers
class RateLimited(Exception):
    def __init__(self, msg, retry_after=None, daily=False):
        super().__init__(msg)
        self.retry_after, self.daily = retry_after, daily


def call_gemini(key, prompt):
    body = {"systemInstruction": {"parts": [{"text": SYSTEM}]}, "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json", "maxOutputTokens": 1024, "thinkingConfig": {"thinkingBudget": 0}}}
    t = time.perf_counter()
    r = httpx.post(f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent", headers={"x-goog-api-key": key}, json=body, timeout=90)
    ms = (time.perf_counter() - t) * 1000
    if r.status_code == 429:
        daily = "per day" in r.text.lower() or "perday" in r.text.lower()
        raise RateLimited("gemini 429" + (" (daily quota)" if daily else ""), daily=daily)
    r.raise_for_status()
    j = r.json()
    cand = (j.get("candidates") or [{}])[0]
    text = "".join(p.get("text", "") for p in (cand.get("content") or {}).get("parts", []))
    u = j.get("usageMetadata", {})
    return {"provider": "gemini", "model": j.get("modelVersion", GEMINI_MODEL), "text": text, "prompt_tokens": u.get("promptTokenCount", 0),
            "completion_tokens": u.get("candidatesTokenCount", 0) + u.get("thoughtsTokenCount", 0), "latency_ms": ms}


def call_groq(key, prompt):
    body = {"model": GROQ_MODEL, "temperature": 0, "max_tokens": 700, "reasoning_effort": "low", "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}]}
    t = time.perf_counter()
    r = httpx.post("https://api.groq.com/openai/v1/chat/completions", headers={"authorization": "Bearer " + key}, json=body, timeout=90)
    ms = (time.perf_counter() - t) * 1000
    if r.status_code == 429:
        try:
            ra = float(r.headers.get("retry-after", "")) if r.headers.get("retry-after") else None
        except ValueError:
            ra = None
        raise RateLimited("groq 429", retry_after=ra)
    r.raise_for_status()
    j = r.json()
    u = j.get("usage", {})
    return {"provider": "groq", "model": j.get("model", GROQ_MODEL), "text": j["choices"][0]["message"].get("content") or "", "prompt_tokens": u.get("prompt_tokens", 0),
            "completion_tokens": u.get("completion_tokens", 0), "latency_ms": ms}


def parse(text):
    try:
        j = json.loads(text)
        r = j["ranking"]
        if isinstance(r, list) and r and all(isinstance(x, str) for x in r):
            return [x.strip() for x in r][:5], str(j.get("reason", ""))[:400]
    except Exception:
        pass
    return None, ""


class Runner:
    def __init__(self, e, deadline):
        self.gem, self.groq = e.get("GEMINI_API_KEY"), e.get("GROQ_API_KEY")
        self.deadline = deadline
        self.last_gem = 0.0
        self.gemini_dead = False                      # the daily quota is gone: Gemini is not tried again in this run
        self.gemini_down_until = 0.0
        self.groq_window = []                         # (time, tokens) over the last minute: Groq's free tier allows 8,000 tokens a minute

    def _groq_pace(self, est):
        while True:
            now = time.time()
            self.groq_window = [(t, k) for t, k in self.groq_window if now - t < 62]
            if sum(k for _, k in self.groq_window) + est <= 7800 or not self.groq_window:
                return
            time.sleep(max(1.0, self.groq_window[0][0] + 62 - now))

    def ask(self, prompt):
        """Gemini first; a rate or daily limit moves that incident to Groq (waiting out Groq's per-minute limit). One retry on bad JSON on the provider that answered, then it is a miss.
        Returns None when the time budget ran out before any provider answered: such an incident is simply not part of the result (it is neither cached nor scored)."""
        attempts = []
        est = int(len(prompt) / 3.4) + 250
        bad_json = 0
        while time.time() < self.deadline:
            use_gem = self.gem and not self.gemini_dead and time.time() >= self.gemini_down_until and bad_json < 2
            prov = "gemini" if use_gem else "groq"
            if prov == "groq" and not self.groq:
                return None
            try:
                if prov == "gemini":
                    wait = 13.0 - (time.time() - self.last_gem)                # a few requests a minute
                    if wait > 0:
                        time.sleep(wait)
                    self.last_gem = time.time()
                    rec = call_gemini(self.gem, prompt)
                else:
                    self._groq_pace(est)
                    rec = call_groq(self.groq, prompt)
                    self.groq_window.append((time.time(), rec["prompt_tokens"] + rec["completion_tokens"] + 60))
            except RateLimited as e:
                attempts.append({"provider": prov, "error": str(e)})
                if prov == "gemini":
                    if e.daily:
                        self.gemini_dead = True
                    else:
                        self.gemini_down_until = time.time() + 60
                else:
                    time.sleep(min(max(e.retry_after or 20.0, 5.0), 120.0))
                continue
            except httpx.HTTPError as e:
                attempts.append({"provider": prov, "error": type(e).__name__ + (f" {e.response.status_code}" if getattr(e, "response", None) is not None else "")})
                if len(attempts) > 40:
                    return None
                time.sleep(5)
                continue
            ranking, reason = parse(rec["text"])
            rec.update({"ranking": ranking, "reason": reason, "attempts": attempts[-6:], "bad_json_retries": bad_json})
            if ranking is not None:
                return rec
            bad_json += 1
            if bad_json >= 2:
                return {**rec, "invalid": True}                                 # two bad answers: a miss
        return None


# ---------------------------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=90.0)
    ap.add_argument("--limit", type=int, default=0, help="only the first N subset incidents (a dry run)")
    ap.add_argument("--no-results", action="store_true")
    ap.add_argument("--report-only", action="store_true", help="make no API calls: report on what the cache already holds (complete incidents only)")
    a = ap.parse_args()
    t_start = time.time()
    cos = load("test")
    by_name = {c["name"]: c for c in cos}
    sub = make_subset(cos)                                      # written before any call
    picks = sub["incidents"][:a.limit] if a.limit else sub["incidents"]
    CACHE.mkdir(exist_ok=True)
    run = Runner(env(), t_start + a.minutes * 60)
    done = {"llm_plain": {}, "llm_memory": {}}
    print(f"subset: {len(picks)} incidents ({SUBSET.name}); {LABEL}", flush=True)
    for n, p in enumerate(picks, 1):
        if time.time() - t_start > a.minutes * 60:
            print(f"hard stop after {a.minutes:.0f} minutes at incident {n - 1} of {len(picks)}", flush=True)
            break
        co = by_name[p["company"]]
        inc = co["incidents"][p["index"]]
        truth = next(c["name"] for c in co["components"] if c["id"] == inc["root"])
        for arm, memory in (("llm_plain", False), ("llm_memory", True)):
            prompt = build_prompt(co, inc, memory)
            h = hashlib.sha256(prompt.encode()).hexdigest()[:16]
            f = CACHE / f"{arm}__{p['company']}__{p['seq']}.json"
            rec = None
            if f.exists():
                c = json.loads(f.read_text(encoding="utf8"))
                if c.get("prompt_sha") == h:
                    rec = c
            if rec is None or rec.get("provider") is None:                      # (an earlier run that got no answer at all is retried, never scored)
                if a.report_only:
                    continue
                rec = run.ask(prompt)
                if rec is None:
                    continue
                rec.update({"arm": arm, "company": p["company"], "seq": p["seq"], "truth": truth, "prompt_sha": h})
                f.write_text(json.dumps(rec, indent=1), encoding="utf8")
            done[arm][(p["company"], p["seq"])] = rec
        if n % 10 == 0:
            print(f"  {n}/{len(picks)} incidents  (elapsed {(time.time() - t_start) / 60:.1f} min)", flush=True)
    report(cos, sub, picks, done, a)


def rank_of(rec, truth):
    if rec.get("ranking") is None:
        return None
    low = [x.lower() for x in rec["ranking"]]
    return low.index(truth.lower()) + 1 if truth.lower() in low else None


def report(cos, sub, picks, done, a):
    by_name = {c["name"]: c for c in cos}
    complete = [p for p in picks if all((p["company"], p["seq"]) in done[arm] for arm in done)]
    methods = {"ghostwalk": "ghostwalk", "learning_off": "learning_off", "tfidf": "retrieval"}
    base = {}
    for key, m in methods.items():
        for c in cos:
            for r in run_company(c, m):
                base[(key, c["name"], r["seq"])] = r["rank"]
    ranks = {k: {} for k in list(methods) + list(done)}
    for p in complete:
        c, s = p["company"], p["seq"]
        truth = next(x["name"] for x in by_name[c]["components"] if x["id"] == by_name[c]["incidents"][p["index"]]["root"])
        for k in methods:
            ranks[k][(c, s)] = base[(k, c, s)]
        for arm in done:
            ranks[arm][(c, s)] = rank_of(done[arm][(c, s)], truth)
    names = sorted({p["company"] for p in complete})

    def tab(k, top):
        rows = []
        for c in names:
            rs = [r for (cc, _), r in ranks[k].items() if cc == c]
            rows.append([sum(1 for r in rs if r is not None and r <= top), len(rs)])
        return np.array(rows, dtype=float)
    out = {"label": LABEL, "n_incidents": len(complete), "n_requested": len(picks), "companies": len(names), "subset_file": "eval/llm_subset.json", "subset": {k: sub[k] for k in ("seed", "split", "rule")},
           "models": {"gemini": GEMINI_MODEL, "groq": GROQ_MODEL}, "arms": {}, "paired_ac1": {}, "paired_ac3": {}, "families_covered": sorted({c.split("-")[0] for c in names}), "families_total": sorted({c["name"].split("-")[0] for c in cos}), "cache_dir": "eval/llm_cache/", "stopped_early": len(complete) < len(picks) or len(picks) < len(sub["incidents"])}
    tabs1 = {k: tab(k, 1) for k in ranks}
    tabs3 = {k: tab(k, 3) for k in ranks}
    pairs = [("ghostwalk", k) for k in ranks if k != "ghostwalk"]
    ci1, d1 = bootstrap(tabs1, 2000, 20261116, pairs)
    ci3, d3 = bootstrap(tabs3, 2000, 20261116, pairs)
    for k in ranks:
        arm = {"ac1": ci1[k], "ac3": ci3[k]}
        if k in done:
            recs = [done[k][(p["company"], p["seq"])] for p in complete]
            lat = np.array([r["latency_ms"] for r in recs if r.get("latency_ms")]) if any(r.get("latency_ms") for r in recs) else np.array([0.0])
            toks = np.array([r.get("prompt_tokens", 0) + r.get("completion_tokens", 0) for r in recs])
            arm.update({"tokens_per_incident": {"mean": float(toks.mean()), "prompt_mean": float(np.mean([r.get("prompt_tokens", 0) for r in recs])), "completion_mean": float(np.mean([r.get("completion_tokens", 0) for r in recs]))},
                        "latency_ms": {"p50": float(np.percentile(lat, 50)), "p95": float(np.percentile(lat, 95))},
                        "invalid_output_rate": float(np.mean([bool(r.get("invalid")) for r in recs])),
                        "provider_share": {pv: float(np.mean([r.get("provider") == pv for r in recs])) for pv in ("gemini", "groq")},
                        "models_used": sorted({r["model"] for r in recs if r.get("model")})})
        out["arms"][k] = arm
    out["paired_ac1"] = {k.replace("ghostwalk - ", "ghostwalk_minus_"): v for k, v in d1.items()}
    out["paired_ac3"] = {k.replace("ghostwalk - ", "ghostwalk_minus_"): v for k, v in d3.items()}
    out["measured_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    print(json.dumps({k: {"ac1": round(v["ac1"]["point"], 3), "ac3": round(v["ac3"]["point"], 3)} for k, v in out["arms"].items()}), f"n={out['n_incidents']}", flush=True)
    if a.no_results:
        return
    p = ROOT / "results.json"
    doc = json.loads(p.read_text(encoding="utf8"))
    doc["llm_baseline"] = out
    tk = [out["arms"][k]["tokens_per_incident"]["mean"] for k in done if "tokens_per_incident" in out["arms"][k]]
    if tk:
        doc.setdefault("ops", {}).setdefault("tokens_per_verdict", {})["llm_baseline"] = {"llm_plain": out["arms"]["llm_plain"]["tokens_per_incident"]["mean"], "llm_memory": out["arms"]["llm_memory"]["tokens_per_incident"]["mean"],
                                                                                       "n": out["n_incidents"], "note": "mean prompt+completion tokens per incident on the LLM subset"}
    p.write_text(json.dumps(doc, indent=2), encoding="utf8")
    print("wrote results.json llm_baseline", flush=True)


if __name__ == "__main__":
    main()
