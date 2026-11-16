"""Run the real-outage replays (ghostwalk/replays.py) and record the LLM's answer on the same input.

    python eval/replays.py            # needs GEMINI_API_KEY / GROQ_API_KEY in .env only for the LLM step (cached in docs/replays/results.json; never printed or committed)

Replay built from the public postmortem; illustrative, not an accuracy measurement. The LLM gets the same prompt as the llm_plain arm of the LLM baseline: the official map as text (without the hidden dependency)
and the alerts in postmortem order. Provider rule as in eval/llm_baseline.py: Gemini first, Groq on a rate or daily limit, the model recorded. Writes docs/replays/results.json and results.json "replays"."""
from __future__ import annotations
import json, pathlib, sys, time, types
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from ghostwalk import replays
from eval import llm_baseline as L


def prompt_for(sc):
    names = {s["name"]: i for i, s in enumerate(sc["services"])}
    co = {"components": [{"id": i, "name": s["name"], "kind": s["kind"], "tier": s["tier"]} for i, s in enumerate(sc["services"])],
          "official_edges": [{"u": names[a], "v": names[b]} for a, b in sc["official_edges"]]}
    return L.build_prompt(co, {"alerts": sc["alerts"], "seq": 0}, memory=False)


def main():
    out_path = replays.DIR / "results.json"
    prev = json.loads(out_path.read_text(encoding="utf8")) if out_path.exists() else {}
    llm = prev.get("llm", {})
    run = L.Runner(L.env(), time.time() + 20 * 60)
    for sid in replays.ids():
        if sid in llm and llm[sid].get("provider"):
            continue
        sc = replays.load(sid)
        rec = run.ask(prompt_for(sc))
        if rec is None:
            print(f"  {sid}: no LLM answer (rate limits), left for a later run", flush=True)
            continue
        low = [x.lower() for x in (rec.get("ranking") or [])]
        llm[sid] = {"provider": rec["provider"], "model": rec["model"], "ranking": rec.get("ranking"), "top1": (rec.get("ranking") or [None])[0],
                    "top1_is_root": bool(low) and low[0] == sc["root"].lower(), "root_rank": (low.index(sc["root"].lower()) + 1) if sc["root"].lower() in low else None,
                    "reason": rec.get("reason", ""), "invalid": bool(rec.get("invalid")), "tokens": rec.get("prompt_tokens", 0) + rec.get("completion_tokens", 0), "latency_ms": rec.get("latency_ms")}
        print(f"  {sid}: {rec['provider']} {rec['model']} -> {llm[sid]['top1']} (root rank {llm[sid]['root_rank']})", flush=True)
    (replays.DIR / "results.json").write_text(json.dumps({"llm": llm}, indent=1), encoding="utf8")
    allr = replays.run_all(with_llm=True)
    doc = json.loads((ROOT / "results.json").read_text(encoding="utf8"))
    doc["replays"] = {"label": "Replay built from the public postmortem; illustrative, not an accuracy measurement.", "abstain_below_confidence": replays.ABSTAIN_BELOW, "scenarios": allr,
                      "llm_label": L.LABEL, "measured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    (ROOT / "results.json").write_text(json.dumps(doc, indent=2), encoding="utf8")
    for r in allr:
        print(r["short"], "| stages:", [(s["top1"], s["root_rank"]) for s in r["stages"]], "| deepest:", r["deepest_alert"]["top1"], "| llm:", (r.get("llm") or {}).get("top1"))


if __name__ == "__main__":
    main()
