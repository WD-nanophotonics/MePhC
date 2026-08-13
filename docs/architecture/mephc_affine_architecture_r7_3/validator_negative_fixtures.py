"""Negative fixtures mutate isolated copies of the R7.3 bundle only."""
from __future__ import annotations
import json
from pathlib import Path
import shutil
import tempfile
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_r7_3 import ValidationError, validate_bundle

ROOT = Path(__file__).resolve().parent

def main():
    cases = {
        "contract_digest_mismatch": ("authoritative_contract.json", lambda data: data[:-1] + b" "),
        "wrong_target_denominator": ("contract_preflight.json", lambda data: json.dumps(dict(json.loads(data), target_denominator=18), indent=2, sort_keys=True).encode()),
        "fresh_resolution_8": ("fresh_solver_execution.json", lambda data: json.dumps((lambda payload: (payload.update({"resolutions": [8] + payload["resolutions"]}), payload["downstream_calls"][0].update({"resolution": 8}), payload)[2])(json.loads(data)), indent=2, sort_keys=True).encode()),
        "trilatt_solver_call": ("trilatt_hold.json", lambda data: json.dumps(dict(json.loads(data), fresh_mpb_solver_calls=1), indent=2, sort_keys=True).encode()),
    }
    results = {}
    for name, (relative, mutate) in cases.items():
        with tempfile.TemporaryDirectory(prefix="r73-negative-") as directory:
            copy = Path(directory) / ROOT.name
            shutil.copytree(ROOT, copy)
            path = copy / relative
            path.write_bytes(mutate(path.read_bytes()))
            try:
                validate_bundle(copy)
            except ValidationError:
                results[name] = "REJECTED"
            else:
                results[name] = "ACCEPTED_UNEXPECTEDLY"
    (ROOT / "logs" / "negative_fixtures.log").write_text(json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if set(results.values()) != {"REJECTED"}:
        raise SystemExit("R7_3_NEGATIVE_FIXTURE_FAILURE")
    print("PASS_R7_3_NEGATIVE_FIXTURES")

if __name__ == "__main__":
    main()
