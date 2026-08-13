"""Mutate isolated R7.4 copies and assert contract-bound rejection."""
from __future__ import annotations
import json
from pathlib import Path
import shutil
import tempfile
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_r7_4 import ValidationError, validate_bundle

ROOT = Path(__file__).resolve().parent

def main():
    cases = {
        "contract_digest": ("authoritative_contract.json", lambda data: data[:-1] + b" "),
        "missing_fixed_control": ("representation_geometry_controls.json", lambda data: json.dumps(dict(json.loads(data), controls={}), indent=2).encode()),
        "trilatt_call": ("solver_execution.json", lambda data: json.dumps(dict(json.loads(data), fresh_trilatt_solver_calls=1), indent=2).encode()),
        "inherited_status": ("inherited_r7_3_status.json", lambda data: json.dumps(dict(json.loads(data), resolved_count=5), indent=2).encode()),
    }
    result = {}
    for name, (relative, mutate) in cases.items():
        with tempfile.TemporaryDirectory(prefix="r74-negative-") as directory:
            copy_root = Path(directory) / "docs" / "architecture" / ROOT.name
            copy_root.parent.mkdir(parents=True)
            shutil.copytree(ROOT, copy_root)
            path = copy_root / relative
            path.write_bytes(mutate(path.read_bytes()))
            try:
                validate_bundle(copy_root)
            except ValidationError:
                result[name] = "REJECTED"
            else:
                result[name] = "ACCEPTED_UNEXPECTEDLY"
    (ROOT / "logs" / "negative_fixtures.log").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if set(result.values()) != {"REJECTED"}:
        raise SystemExit("R7_4_NEGATIVE_FIXTURE_FAILURE")
    print("PASS_R7_4_NEGATIVE_FIXTURES")

if __name__ == "__main__":
    main()
