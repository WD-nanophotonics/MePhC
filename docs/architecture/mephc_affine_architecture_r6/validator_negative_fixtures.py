"""Negative fixtures for validate_r6.py; never mutates the live bundle."""
from __future__ import annotations
import json
from pathlib import Path
import shutil
import tempfile

from validate_r6 import validate


def run(root: Path):
    checks = {}
    with tempfile.TemporaryDirectory(prefix="r6-negative-") as temp:
        work = Path(temp) / "bundle"
        shutil.copytree(root, work)
        (work / "README.md").unlink()
        checks["missing_artifact"] = bool(validate(work))
        shutil.copytree(root, Path(temp) / "digest")
        bad = Path(temp) / "digest" / "sqrlatt_response.json"
        bad.write_text(bad.read_text() + "x", encoding="utf-8")
        checks["bad_digest"] = bool(validate(Path(temp) / "digest"))
        shutil.copytree(root, Path(temp) / "status")
        completion = Path(temp) / "status" / "completion.json"
        value = json.loads(completion.read_text())
        value["overall_status"] = "PASS"
        completion.write_text(json.dumps(value), encoding="utf-8")
        checks["status_mismatch"] = bool(validate(Path(temp) / "status"))
    return checks


if __name__ == "__main__":
    result = run(Path(__file__).resolve().parent)
    print(result)
    raise SystemExit(0 if all(result.values()) else 1)

