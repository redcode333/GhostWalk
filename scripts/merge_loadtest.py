"""Merge a load test run into results.json as ops.loadtest.<label> (label from the run, e.g. vm). Refuses unlabelled runs.
    python scripts/merge_loadtest.py loadtest_vm.json"""
import json, pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parent.parent
run = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf8"))
label = run["machine"]["label"]
if label == "unlabelled":
    raise SystemExit("set GW_MEASURED_ON (vm / laptop) when running the load test")
p = ROOT / "results.json"
doc = json.loads(p.read_text(encoding="utf8"))
doc.setdefault("ops", {}).setdefault("loadtest", {})[label] = run
p.write_text(json.dumps(doc, indent=2), encoding="utf8")
print("ops.loadtest." + label, [(l["concurrency"], l["req_per_s"]) for l in run["levels"]])
