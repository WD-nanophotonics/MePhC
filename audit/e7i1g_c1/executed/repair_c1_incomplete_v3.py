from pathlib import Path
import json
import subprocess
import sys
import time

root = Path("/mnt/c/Users/icywo/PycharmProjects/MePhC-Windows")
manifest_path = root / ".e7i1g_c1_results_fixed" / "manifest.json"
data = json.loads(manifest_path.read_text(encoding="utf-8"))
missing = [sample for sample in data["samples"] if sample.get("result") is None]
if len(missing) != 1:
    raise SystemExit(f"expected exactly one incomplete sample, found {len(missing)}")
sample = missing[0]
qx, qy = repr(sample["qx"]), repr(sample["qy"])
cmd = [sys.executable, str(root / "e7i1b_point_worker.py"), "--resolution", "64", "--h", ".001", f"--qx={qx}", f"--qy={qy}", "--valley", "K", "--radius-a", ".15", "--radius-b", ".25"]
run = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
result = None
for line in reversed(run.stdout.splitlines()):
    if line.lstrip().startswith("{"):
        try:
            candidate = json.loads(line)
        except json.JSONDecodeError:
            continue
        if candidate.get("event") == "result":
            result = candidate
            break
if result is None:
    raise RuntimeError("the repair worker produced no result event\n" + run.stderr[-2000:])
sample["result"] = result
sample["execution"] = "REPAIRED_SINGLE_POINT"
data["status"] = "COMPLETE" if all(item.get("result") is not None for item in data["samples"]) else "FAILED_INCOMPLETE"
data["qualified_count"] = sum(item.get("result", {}).get("production_decision") == "QUALIFIED_VALUE" for item in data["samples"] if item.get("result"))
data["masked_count"] = sum(item.get("result", {}).get("production_decision") != "QUALIFIED_VALUE" for item in data["samples"] if item.get("result"))
data["repaired_at"] = time.time()
manifest_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
print(json.dumps({"status": data["status"], "qualified_count": data["qualified_count"], "masked_count": data["masked_count"], "repaired": [sample["qx"], sample["qy"]]}))
