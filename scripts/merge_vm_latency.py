"""Merge deploy/measure_vm.py's output into results.json as ops.vm (labelled VM), keeping the laptop numbers untouched.
    python scripts/merge_vm_latency.py vm_latency.json"""
import json, pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parent.parent
vm = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf8"))
if vm["machine"]["label"] != "VM":
    raise SystemExit(f"refusing to record this as the VM: it was measured on '{vm['machine']['label']}' (run it with GW_MEASURED_ON=vm on the VM)")
p = ROOT / "results.json"
doc = json.loads(p.read_text(encoding="utf8"))
doc.setdefault("ops", {})["vm"] = vm
p.write_text(json.dumps(doc, indent=2), encoding="utf8")
print("ops.vm written:", vm["online_loop"]["verdict_ms"], "ms verdict,", vm["warm"]["verdict_cached_hit_ms"])
