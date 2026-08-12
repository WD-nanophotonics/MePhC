"""Prove that previously observed R3.1 evidence defects fail validation."""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
VALIDATOR = ROOT / "validate_r3_1.py"


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    cases = {
        "remove_validator_summary": lambda root: _remove_validator_summary(root),
        "replace_named_gates_with_A_B_C_D": lambda root: _replace_gates(root),
        "stale_validated_payload_ref": lambda root: _stale_payload(root),
        "omit_commit_from_range": lambda root: _omit_range(root),
        "reference_tmp_smoke_driver": lambda root: _tmp_driver(root),
        "remove_completion_from_manifest": lambda root: _remove_manifest_entry(root),
        "change_manifested_payload_byte": lambda root: _change_payload(root),
        "add_out_of_allowlist_seal_path": lambda root: _out_of_allowlist(root),
    }
    results = {}
    for name, mutate in cases.items():
        with tempfile.TemporaryDirectory(prefix="r31-validator-") as temporary:
            fixture = Path(temporary) / ROOT.name
            shutil.copytree(ROOT, fixture, ignore=shutil.ignore_patterns("__pycache__"))
            mutate(fixture)
            proc = subprocess.run(
                [sys.executable, str(fixture / "validate_r3_1.py"), "--check-worktrees", "--bundle-root", str(fixture)],
                capture_output=True,
                text=True,
                check=False,
            )
            results[name] = {"rejected": proc.returncode != 0, "exit_code": proc.returncode}
            if proc.returncode == 0:
                raise AssertionError(f"negative fixture unexpectedly passed: {name}")
    summary = {"status": "PASS", "cases": results}
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def _replace_gates(root: Path):
    completion = load(root / "completion.json")
    completion["defect_gates"] = {"A": "PASS", "B": "PASS", "C": "PASS", "D": "PASS"}
    dump(root / "completion.json", completion)


def _remove_validator_summary(root: Path):
    completion = load(root / "completion.json")
    completion.pop("validator_summary", None)
    dump(root / "completion.json", completion)


def _stale_payload(root: Path):
    completion = load(root / "completion.json")
    completion["validated_payload_refs"]["MePhC"] = "0" * 40
    dump(root / "completion.json", completion)


def _omit_range(root: Path):
    completion = load(root / "completion.json")
    completion["complete_commit_ranges"]["MePhC"]["from_reviewed_entry_exclusive_through_payload"] = []
    dump(root / "completion.json", completion)


def _tmp_driver(root: Path):
    completion = load(root / "completion.json")
    completion["test_summary"]["production_smokes"]["driver_path"] = "/tmp/r31_smoke.py"
    dump(root / "completion.json", completion)


def _remove_manifest_entry(root: Path):
    manifest = load(root / "artifact_manifest.json")
    manifest["artifacts"] = [item for item in manifest["artifacts"] if item["path"] != "completion.json"]
    dump(root / "artifact_manifest.json", manifest)


def _change_payload(root: Path):
    path = root / "README.md"
    path.write_text(path.read_text(encoding="utf-8") + "\nfixture mutation\n", encoding="utf-8")


def _out_of_allowlist(root: Path):
    completion = load(root / "completion.json")
    completion["metadata_seal_paths"] = ["docs/forbidden.py"]
    dump(root / "completion.json", completion)


if __name__ == "__main__":
    raise SystemExit(main())
