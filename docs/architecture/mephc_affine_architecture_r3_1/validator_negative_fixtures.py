"""Target every corrective validator rule with isolated, deterministic fixtures."""

from __future__ import annotations

import hashlib
import json
import os
import re
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


def refresh_manifest(root: Path, changed: str) -> None:
    manifest_path = root / "artifact_manifest.json"
    manifest = load(manifest_path)
    path = root / changed
    for item in manifest["artifacts"]:
        if item["path"] == changed:
            item["size"] = path.stat().st_size
            item["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            break
    else:
        raise AssertionError(f"manifest item not found: {changed}")
    dump(manifest_path, manifest)


def run_bundle(root: Path):
    return subprocess.run(
        [sys.executable, str(root / "validate_r3_1.py"), "--check-bundle", "--bundle-root", str(root)],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )


def codes(proc) -> list[str]:
    return re.findall(r"E_[A-Z_]+", proc.stderr)


def mutate_completion(root: Path, fn) -> None:
    path = root / "completion.json"
    value = load(path)
    fn(value)
    dump(path, value)
    refresh_manifest(root, "completion.json")


def mutate_smoke(root: Path, smoke_id: str, fn) -> None:
    path = root / "entrypoint_smoke.json"
    value = load(path)
    fn(value["entries"][smoke_id])
    dump(path, value)
    refresh_manifest(root, "entrypoint_smoke.json")


def mutate_scope(root: Path) -> None:
    path = root / "change_scope.json"
    value = load(path)
    value["payload_paths"] = value["payload_paths"][1:]
    dump(path, value)
    refresh_manifest(root, "change_scope.json")


def main() -> int:
    cases = {
        "remove_compatibility_gate": ("E_COMPATIBILITY_GATE_MISSING", lambda r: mutate_completion(r, lambda c: c["compatibility_gates"].pop("record_namespace_preserved"))),
        "compatibility_gate_non_pass": ("E_COMPATIBILITY_GATE_STATUS", lambda r: mutate_completion(r, lambda c: c["compatibility_gates"].__setitem__("record_namespace_preserved", "FAIL"))),
        "remove_integrity_entry": ("E_INTEGRITY_ENTRY_MISSING", lambda r: mutate_completion(r, lambda c: c["integrity_summary"].pop("manifest_payload_complete"))),
        "remove_required_check": ("E_VALIDATOR_REQUIRED_CHECK_MISSING", lambda r: mutate_completion(r, lambda c: c["validator_summary"]["required_checks"].pop("bundle_schema"))),
        "arbitrary_pass_required_checks": ("E_VALIDATOR_REQUIRED_CHECK_MISSING", lambda r: mutate_completion(r, lambda c: c["validator_summary"].__setitem__("required_checks", {"A": {"status": "PASS", "command": "x", "exit_code": 0, "evidence_path": "README.md"}}))),
        "remove_smoke_assertion": ("E_SMOKE_ASSERTION_MISSING", lambda r: mutate_smoke(r, "band_non_identity_low_resolution", lambda e: e["assertion_results"].pop(next(iter(e["assertion_results"]))))),
        "remove_smoke_log": ("E_SMOKE_LOG_MISSING", lambda r: mutate_smoke(r, "band_non_identity_low_resolution", lambda e: e.__setitem__("log_path", "logs/missing.log"))),
        "tmp_smoke_command": ("E_SMOKE_COMMAND_UNSAFE", lambda r: mutate_smoke(r, "band_non_identity_low_resolution", lambda e: e.__setitem__("command", "/tmp/runner.py"))),
        "windows_or_unc_smoke_command": ("E_SMOKE_COMMAND_UNSAFE", lambda r: mutate_smoke(r, "band_non_identity_low_resolution", lambda e: e.__setitem__("command", r"\\server\share\runner.py"))),
        "manifest_payload_omission": ("E_MANIFEST_PAYLOAD_OMISSION", mutate_scope),
        "manifested_byte_change": ("E_MANIFEST_DIGEST", lambda r: (r / "README.md").write_text((r / "README.md").read_text(encoding="utf-8") + "\nfixture mutation\n", encoding="utf-8")),
    }
    results = {}
    for fixture_id, (expected, mutate) in cases.items():
        with tempfile.TemporaryDirectory(prefix="r31-bundle-") as temporary:
            fixture = Path(temporary) / "bundle"
            shutil.copytree(ROOT, fixture, ignore=shutil.ignore_patterns("__pycache__"))
            mutate(fixture)
            proc = run_bundle(fixture)
            actual = codes(proc)
            masking = {"E_MANIFEST_DIGEST", "E_MANIFEST_SIZE"} - {expected}
            passed = proc.returncode != 0 and expected in actual and not masking.intersection(actual)
            results[fixture_id] = {"intended_rule": fixture_id, "expected_code": expected, "actual_codes": actual, "exit_code": proc.returncode, "stderr": proc.stderr, "status": "PASS" if passed else "FAIL"}
            if not passed:
                raise AssertionError(json.dumps(results[fixture_id], sort_keys=True))

    pure_cases = {}
    pure = subprocess.run([sys.executable, "-c", f"import importlib.util; s=importlib.util.spec_from_file_location('v', r'{VALIDATOR}'); m=importlib.util.module_from_spec(s); s.loader.exec_module(m);\nfor a,b in [('E_SEAL_PARENT', lambda: m.validate_seal_parent('0'*40,'1'*40)), ('E_SEAL_DIFF_PATH', lambda: m.validate_seal_diff(['docs/forbidden.py'])), ('E_REPOSITORY_REF', lambda: m.validate_repository_ref('0'*40,'1'*40))]:\n try: b()\n except m.DiagnosticError as e: print(a, e.code)"], capture_output=True, text=True)
    observed = pure.stdout.split()
    pure_fixture_ids = {
        "payload_ref_not_equal_seal_parent": "E_SEAL_PARENT",
        "seal_diff_forbidden_path": "E_SEAL_DIFF_PATH",
        "repository_ref_mismatch": "E_REPOSITORY_REF",
    }
    for fixture_id, expected in pure_fixture_ids.items():
        actual = expected if expected in observed else ""
        pure_cases[fixture_id] = {"intended_rule": fixture_id, "expected_code": expected, "actual_codes": [actual] if actual else [], "exit_code": 1 if actual else 0, "status": "PASS" if actual else "FAIL"}
        if not actual:
            raise AssertionError(f"pure fixture failed: {expected}: {pure.stdout} {pure.stderr}")
    report = {"status": "PASS", "cases": {**results, **pure_cases}}
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
