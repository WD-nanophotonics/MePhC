from __future__ import annotations

import json
import tempfile
from pathlib import Path
from shutil import copytree

import validate_r16


def expect_reject(root: Path, mutate, label: str):
    mutate(root)
    try:
        validate_r16.validate_bundle(root)
    except (AssertionError, KeyError, IndexError, ValueError, OSError):
        return {"fixture": label, "rejected": True}
    raise AssertionError(f"negative fixture accepted: {label}")


def main():
    results = []
    with tempfile.TemporaryDirectory(prefix="r16-negative-") as directory:
        base = Path(directory) / "bundle"
        copytree(validate_r16.ROOT, base)

        def wrong_count(root):
            path = root / "solver_execution.json"
            data = json.loads(path.read_text())
            data["fresh_solver_call_count"] = 141
            path.write_text(json.dumps(data))

        results.append(expect_reject(base, wrong_count, "fresh_count_141"))

        base2 = Path(directory) / "bundle2"
        copytree(validate_r16.ROOT, base2)

        def forbidden_uniform(root):
            path = root / "corrective_fresh_call_plan.json"
            data = json.loads(path.read_text())
            data["calls"][0]["h"] = 0.01
            path.write_text(json.dumps(data))

        results.append(expect_reject(base2, forbidden_uniform, "forbidden_fresh_level"))

    print(json.dumps({"validator": "r16_negative_fixtures", "status": "PASS", "fixtures": results}, sort_keys=True))


if __name__ == "__main__":
    main()
