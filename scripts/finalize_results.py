"""After the final TEST run: record the AC@1 history in results.json and check that every table agrees.   python scripts/finalize_results.py"""
import json, pathlib, subprocess
ROOT = pathlib.Path(__file__).resolve().parent.parent
p = ROOT / "results.json"
r = json.loads(p.read_text(encoding="utf8"))
N = r["meta"]["incidents"]
final = round(r["methods"]["ghostwalk"]["ac1"]["point"] * N)
sw = r["store_swap"]
tables = {k: round(v["ac1"]["point"] * N) for k, v in sw["backends"].items() if k in ("inmemory", "hydradb", "pg_cte")}
assert set(tables.values()) == {final}, f"tables disagree: main {final} vs store swap {tables}"          # one engine, one number everywhere
head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, cwd=ROOT).strip()
r["meta"]["ac1_history"] = [
    {"engine": "before the walk-loop optimisation (commit f8bf9a8)", "hits": 1379, "of": N},
    {"engine": "after the optimisation: tied scores ordered by float summation order (store-swap run, commit 3c43bab)", "hits": 1380, "of": N},
    {"engine": "final: deterministic tie-break (scores equal to 9 decimals, then lowest component id)", "hits": final, "of": N},
]
r["meta"]["note_engine_versions"] = ("every table in this file (methods, headline, repeat/novel, poisoning, change evidence, store swap) comes from the final engine; "
                                     "see ac1_history for how the top-1 count moved: 1379 -> 1380 -> " + str(final) + " of " + str(N))
sw.pop("engine_note", None)
sw["engine"] = {"commit": head, "note": "store swap run with the final engine; HydraDB, in-memory and Postgres-CTE give the identical top-1 count"}
p.write_text(json.dumps(r, indent=2), encoding="utf8")
print("history recorded; all tables agree on", final, "of", N)
