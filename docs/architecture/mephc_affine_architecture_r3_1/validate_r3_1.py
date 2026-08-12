"""Validate the R3.1 validator/receipt corrective evidence bundle.

``--check-bundle`` is hermetic and never invokes Git. ``--check-worktrees``
adds Git checks against explicitly supplied repository roots.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

TASK_ID = "mephc-affine-architecture-r3.1-validator-receipt-corrective"
PREFIX = "docs/architecture/mephc_affine_architecture_r3_1/"
DRIVER = PREFIX + "run_r3_1_smokes.py"
SEAL = sorted([PREFIX + "artifact_manifest.json", PREFIX + "completion.json"])
REVIEWED_MEPHC = "24e29d9c9c6ceae979e1a81953c4f54853f98808"
REVIEWED_TRILATT = "df2cdf4fd70e741e1a8901a9274a0b0e42b1e737"
ENTRY_MEPHC = "699d1802ff02d92de25e6ef8ff9b90386dc82cf0"
ENTRY_TRILATT = "16cbb988a12f46d5360c64b2c65fdf9fc51e053c"
ENTRY_SQRLATT = "8a1e4534a48e01a83996fb199ccd55e0983e72b2"
NAMED = {"all_motif_centers_affine", "rigid_local_features", "frequency_landmark_migrated", "production_entry_smokes", "documentation_current"}
COMPAT = {"identity_behavior_preserved", "record_namespace_preserved", "production_source_unchanged", "trilatt_runtime_unchanged", "sqrlatt_hold_point_preserved", "r1_r2_r3_evidence_preserved"}
INTEGRITY = {"manifest_payload_complete", "manifest_digests_match", "changed_paths_within_allowlist", "protected_digests_match", "seal_diff_within_allowlist"}
CHECKS = {"bundle_schema", "manifest_integrity", "completion_semantics", "compatibility_gates", "integrity_summary", "smoke_evidence_binding", "negative_fixture_targeting", "seal_and_worktree_validation"}
SMOKES = {"band_non_identity_low_resolution", "berry_non_identity_low_resolution", "efs_non_identity_low_resolution", "frequency_at_tracked_K1_non_identity_low_resolution"}
LOGS = {"compileall.log", "mephc_tests.log", "trilatt_tests.log", "r2_validator.log", "r3_validator.log", "r31_negative_fixtures.log", "entrypoint_smoke.log"}
FILES = {"README.md", "baseline.json", "change_scope.json", "geometry_validation.json", "k_landmark_validation.json", "entrypoint_smoke.json", "test_runs.json", "integrity_digests.json", "validation_report.md", "completion.json", "artifact_manifest.json", "validate_r3_1.py", "run_r3_1_smokes.py", "validator_negative_fixtures.py"}
HEX40 = re.compile(r"^[0-9a-f]{40}$")


class DiagnosticError(ValueError):
    def __init__(self, code: str, message: str):
        self.code, self.message = code, message
        super().__init__(message)


def fail(code: str, message: str):
    raise DiagnosticError(code, message)


def load(root: Path, name: str):
    try:
        return json.loads((root / name).read_text(encoding="utf-8"))
    except FileNotFoundError:
        fail("E_REQUIRED_FILE", f"missing {name}")
    except json.JSONDecodeError as exc:
        fail("E_JSON_SCHEMA", f"invalid JSON {name}: {exc}")


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def rel(value: str, field: str) -> str:
    if not isinstance(value, str) or "\\" in value:
        fail("E_PATH_UNSAFE", f"{field} is not POSIX-relative")
    p = PurePosixPath(value)
    if not value or p.is_absolute() or ".." in p.parts or value.startswith("./"):
        fail("E_PATH_UNSAFE", f"unsafe {field}: {value!r}")
    return value


def path_for(root: Path, value: str, field: str) -> Path:
    rel(value, field)
    path = (root / value).resolve()
    if root.resolve() not in path.parents:
        fail("E_PATH_UNSAFE", f"path escapes root: {value!r}")
    return path


def payload_files(root: Path) -> set[str]:
    result = set()
    for path in root.rglob("*"):
        if path.is_symlink():
            fail("E_PATH_UNSAFE", f"symlink in bundle: {path}")
        if path.is_file() and path.name != "artifact_manifest.json":
            result.add(str(path.relative_to(root)).replace("\\", "/"))
    return result


def check_manifest(root: Path):
    m = load(root, "artifact_manifest.json")
    if m.get("status") != "PASS" or m.get("algorithm") != "sha256":
        fail("E_MANIFEST_SCHEMA", "invalid manifest status or algorithm")
    if m.get("excluded_paths") != ["artifact_manifest.json"]:
        fail("E_MANIFEST_SCHEMA", "manifest must exclude only itself")
    entries = m.get("artifacts")
    if not isinstance(entries, list):
        fail("E_MANIFEST_SCHEMA", "manifest artifacts must be a list")
    paths = []
    for item in entries:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            fail("E_MANIFEST_SCHEMA", "malformed manifest entry")
        value = rel(item["path"], "manifest.path")
        if value == "artifact_manifest.json":
            fail("E_MANIFEST_SCHEMA", "manifest may not list itself")
        paths.append(value)
        path = path_for(root, value, "manifest.path")
        if not path.is_file():
            fail("E_MANIFEST_PAYLOAD_OMISSION", f"missing payload: {value}")
        if item.get("sha256") != digest(path):
            fail("E_MANIFEST_DIGEST", value)
        if item.get("size") != path.stat().st_size:
            fail("E_MANIFEST_SIZE", value)
    if len(paths) != len(set(paths)):
        fail("E_MANIFEST_SCHEMA", "duplicate manifest path")
    actual = payload_files(root)
    if set(paths) != actual:
        fail("E_MANIFEST_PAYLOAD_OMISSION", f"payload mismatch missing={sorted(actual-set(paths))} extra={sorted(set(paths)-actual)}")
    if "completion.json" not in paths or "run_r3_1_smokes.py" not in paths:
        fail("E_MANIFEST_PAYLOAD_OMISSION", "completion or driver omitted")
    return m


def check_completion(root: Path):
    c = load(root, "completion.json")
    if c.get("task_id") != TASK_ID:
        fail("E_COMPLETION_TASK", "wrong corrective task id")
    preseal = c.get("phase") == "preseal"
    if (c.get("status") != "PASS" and not (preseal and c.get("status") == "PREPARED")) or c.get("r4_authorized") is not False:
        fail("E_COMPLETION_STATUS", "invalid status or R4 flag")
    if c.get("independent_review_required") is not True:
        fail("E_COMPLETION_STATUS", "independent review flag missing")
    if c.get("metadata_seal_paths") != SEAL:
        fail("E_SEAL_PATH_ALLOWLIST", "invalid metadata seal allowlist")
    gates = c.get("defect_gates")
    if not isinstance(gates, dict) or set(gates) != NAMED:
        fail("E_NAMED_GATE_MISSING", "exact named defect gates required")
    if any(value != "PASS" and not (preseal and value == "PENDING") for value in gates.values()):
        fail("E_NAMED_GATE_STATUS", "named defect gate is not PASS")
    compatibility = c.get("compatibility_gates")
    if not isinstance(compatibility, dict):
        fail("E_COMPATIBILITY_GATE_MISSING", "compatibility gates missing")
    if COMPAT - set(compatibility):
        fail("E_COMPATIBILITY_GATE_MISSING", f"missing gates: {sorted(COMPAT-set(compatibility))}")
    if any(compatibility[name] != "PASS" and not (preseal and compatibility[name] == "PENDING") for name in COMPAT):
        fail("E_COMPATIBILITY_GATE_STATUS", "compatibility gate is not PASS")
    integrity = c.get("integrity_summary")
    if not isinstance(integrity, dict):
        fail("E_INTEGRITY_ENTRY_MISSING", "integrity summary missing")
    for name in INTEGRITY:
        item = integrity.get(name)
        if not isinstance(item, dict) or (item.get("status") != "PASS" and not (preseal and item.get("status") == "PENDING")) or not isinstance(item.get("evidence_ref"), str):
            fail("E_INTEGRITY_ENTRY_MISSING", f"invalid integrity entry: {name}")
        path_for(root, item["evidence_ref"], f"integrity.{name}.evidence_ref")
    summary = c.get("validator_summary")
    checks = summary.get("required_checks") if isinstance(summary, dict) else None
    if not isinstance(checks, dict):
        fail("E_VALIDATOR_REQUIRED_CHECK_MISSING", "required checks missing")
    for name in CHECKS:
        item = checks.get(name)
        if not isinstance(item, dict):
            fail("E_VALIDATOR_REQUIRED_CHECK_MISSING", f"missing required check: {name}")
        if (item.get("status") != "PASS" and not (preseal and item.get("status") == "PENDING")) or item.get("exit_code") not in (0, None):
            fail("E_VALIDATOR_REQUIRED_CHECK_STATUS", f"failed required check: {name}")
        if not isinstance(item.get("command"), str) or not isinstance(item.get("evidence_path"), str):
            fail("E_VALIDATOR_REQUIRED_CHECK_SCHEMA", f"incomplete required check: {name}")
        path_for(root, item["evidence_path"], f"checks.{name}.evidence_path")
    tests = c.get("test_summary")
    required_tests = ("MePhC_tests", "TriLatt_tests", "compileall", "R2_validator", "R3_validator", "R3_1_negative_fixtures", "production_smokes")
    if not isinstance(tests, dict) or any(not isinstance(tests.get(name), dict) or (tests[name].get("status") != "PASS" and not (preseal and tests[name].get("status") == "PENDING")) for name in required_tests):
        fail("E_TEST_SUMMARY", "test summary is incomplete")
    if tests["MePhC_tests"].get("tests_run", 0) < 33 or tests["TriLatt_tests"].get("tests_run", 0) < 28:
        fail("E_TEST_SUMMARY", "test count below contract")
    if tests["production_smokes"].get("skipped") is not False:
        fail("E_SMOKE_STATUS", "smokes may not be skipped")
    refs = c.get("reviewed_entry_refs", {})
    if refs.get("MePhC") != REVIEWED_MEPHC or refs.get("TriLatt") != REVIEWED_TRILATT or refs.get("SqrLatt") != ENTRY_SQRLATT:
        fail("E_REPOSITORY_REF", "reviewed refs invalid")
    for key in ("validated_payload_refs", "corrective_entry_refs"):
        values = c.get(key)
        if not isinstance(values, dict) or any(not isinstance(values.get(name), str) or not HEX40.fullmatch(values[name]) for name in ("MePhC", "TriLatt")):
            fail("E_REPOSITORY_REF", f"invalid {key}")
    ranges = c.get("complete_commit_ranges", {})
    for name in ("MePhC", "TriLatt"):
        values = ranges.get(name, {}).get("from_reviewed_entry_exclusive_through_payload", [])
        if not values or len(values) != len(set(values)) or any(not isinstance(v, str) or not HEX40.fullmatch(v) for v in values):
            fail("E_COMMIT_RANGE", f"invalid historical range: {name}")
    corrective = c.get("corrective_commit_ranges", {})
    if not isinstance(corrective.get("MePhC", {}).get("from_entry_exclusive_through_payload", []), list):
        fail("E_COMMIT_RANGE", "corrective MePhC range is malformed")
    if corrective.get("TriLatt", {}).get("from_entry_exclusive_through_payload"):
        fail("E_REPOSITORY_REF", "TriLatt corrective range must be empty")
    return c


def check_command(command: str):
    if not isinstance(command, str) or not command.strip() or "/tmp" in command or re.search(r"(^|\s)[A-Za-z]:[\\/]", command) or "\\\\" in command or re.search(r"(^|\s)/(?!/)", command):
        fail("E_SMOKE_COMMAND_UNSAFE", f"unsafe smoke command: {command!r}")
    if any(part == ".." for part in command.replace("\\", "/").split("/")):
        fail("E_SMOKE_COMMAND_UNSAFE", f"parent escape in smoke command: {command!r}")


def check_smokes(root: Path):
    s = load(root, "entrypoint_smoke.json")
    if s.get("status") != "PASS" or set(s.get("entries", {})) != SMOKES:
        fail("E_SMOKE_SCHEMA", "smoke IDs incomplete")
    for name, item in s["entries"].items():
        required = {"status", "exit_code", "started_at", "ended_at", "duration_seconds", "driver_path", "command", "parameters", "solver", "production_entry_traversed", "required_assertions", "assertion_results", "numerical_or_shape_summary", "log_path"}
        if required - set(item):
            fail("E_SMOKE_SCHEMA", f"{name} missing fields: {sorted(required-set(item))}")
        if item["status"] != "PASS" or item["exit_code"] != 0 or item["duration_seconds"] < 0:
            fail("E_SMOKE_STATUS", name)
        if item["driver_path"] != DRIVER:
            fail("E_SMOKE_DRIVER", name)
        rel(item["driver_path"], f"{name}.driver_path")
        check_command(item["command"])
        params = item["parameters"]
        if not isinstance(params, dict) or params.get("resolution", 0) <= 0 or params.get("stretch_factor") == 1 or "stretch_angle_degrees" not in params:
            fail("E_SMOKE_PARAMETERS", name)
        if item["solver"] != "MPB" or item["production_entry_traversed"] is not True:
            fail("E_SMOKE_PRODUCTION_ENTRY", name)
        assertions, results = item["required_assertions"], item["assertion_results"]
        if not isinstance(assertions, list) or not assertions or not isinstance(results, dict) or any(results.get(a) != "PASS" for a in assertions):
            fail("E_SMOKE_ASSERTION_MISSING", name)
        summary = item["numerical_or_shape_summary"]
        if not isinstance(summary, dict) or summary.get("finite") is not True or not isinstance(summary.get("shape"), list) or not summary["shape"]:
            fail("E_SMOKE_NUMERICS", name)
        log = rel(item["log_path"], f"{name}.log_path")
        if not (root / log).is_file():
            fail("E_SMOKE_LOG_MISSING", name)
    return s


def check_bundle(root: Path):
    root = root.resolve()
    if not root.is_dir():
        fail("E_BUNDLE_ROOT", str(root))
    if FILES - {p.name for p in root.iterdir() if p.is_file()}:
        fail("E_REQUIRED_FILE", f"missing files: {sorted(FILES-{p.name for p in root.iterdir() if p.is_file()})}")
    if not LOGS <= {p.name for p in (root / "logs").glob("*.log")}:
        fail("E_SMOKE_LOG_MISSING", "required log missing")
    check_manifest(root)
    completion = check_completion(root)
    if load(root, "geometry_validation.json").get("all_passed") is not True or load(root, "k_landmark_validation.json").get("all_passed") is not True:
        fail("E_PROTECTED_EVIDENCE", "geometry/landmark evidence failed")
    scope = load(root, "change_scope.json")
    if scope.get("allowlist_passed") is not True:
        fail("E_ALLOWLIST", "change scope failed")
    declared = scope.get("payload_paths")
    expected_declared = {PREFIX + value for value in payload_files(root)} | {PREFIX + "artifact_manifest.json"}
    if not isinstance(declared, list) or set(declared) != expected_declared:
        fail("E_MANIFEST_PAYLOAD_OMISSION", "change scope payload declaration does not cover the bundle")
    check_smokes(root)
    return completion


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def tree(repo: Path, prefixes=None):
    files = git(repo, "ls-files").splitlines()
    if prefixes:
        files = [x for x in files if any(x == p or x.startswith(p) for p in prefixes)]
    h = hashlib.sha256()
    for x in sorted(files):
        h.update(f"{repo.name}/{x}".encode()); h.update(b"\0"); h.update((repo/x).read_bytes()); h.update(b"\0")
    return {"sha256": h.hexdigest(), "file_count": len(files)}


def scientific(repos):
    values = {n: tree(p, ("data/", "image/", "diagnostics/")) for n, p in repos.items()}
    h = hashlib.sha256()
    for n in ("MePhC", "TriLatt", "SqrLatt"): h.update(f"{n}:{values[n]['sha256']}".encode())
    return {"sha256": h.hexdigest(), "repositories": values}


def check_worktrees(bundle, mephc, trilatt, sqrlatt, require_remote):
    c = check_bundle(bundle)
    if c.get("phase") == "preseal":
        fail("E_COMPLETION_STATUS", "preseal bundle cannot validate live worktrees")
    repos = {"MePhC": mephc, "TriLatt": trilatt, "SqrLatt": sqrlatt}
    if any(git(p, "status", "--porcelain") for p in repos.values()): fail("E_CLEAN_STATE", "dirty worktree")
    if git(mephc, "rev-parse", "HEAD^") != c["validated_payload_refs"]["MePhC"]: fail("E_SEAL_PARENT", "payload is not HEAD^")
    if git(trilatt, "rev-parse", "HEAD") != c["validated_payload_refs"]["TriLatt"]: fail("E_REPOSITORY_REF", "TriLatt ref mismatch")
    if git(sqrlatt, "rev-parse", "HEAD") != ENTRY_SQRLATT: fail("E_REPOSITORY_REF", "SqrLatt hold mismatch")
    if git(mephc, "diff", "--name-only", "HEAD^", "HEAD").splitlines() != SEAL: fail("E_SEAL_DIFF_PATH", "seal diff is outside allowlist")
    if require_remote:
        for name, repo in repos.items():
            if git(repo, "rev-parse", "HEAD") != git(repo, "rev-parse", "origin/main"): fail("E_REMOTE_CONTAINMENT", name)
    for repo, entry in ((mephc, REVIEWED_MEPHC), (trilatt, REVIEWED_TRILATT)): subprocess.check_call(["git", "-C", str(repo), "merge-base", "--is-ancestor", entry, "HEAD"])
    ranges = c["complete_commit_ranges"]
    if git(mephc, "rev-list", "--first-parent", "--reverse", f"{REVIEWED_MEPHC}..HEAD^").splitlines() != ranges["MePhC"]["from_reviewed_entry_exclusive_through_payload"]: fail("E_COMMIT_RANGE", "MePhC historical range")
    if git(trilatt, "rev-list", "--first-parent", "--reverse", f"{REVIEWED_TRILATT}..HEAD").splitlines() != ranges["TriLatt"]["from_reviewed_entry_exclusive_through_payload"]: fail("E_COMMIT_RANGE", "TriLatt historical range")
    corrective = c["corrective_commit_ranges"]
    mephc_corrective = git(mephc, "rev-list", "--first-parent", "--reverse", f"{ENTRY_MEPHC}..HEAD^").splitlines()
    if not mephc_corrective or mephc_corrective != corrective["MePhC"]["from_entry_exclusive_through_payload"]: fail("E_COMMIT_RANGE", "MePhC corrective range")
    if git(trilatt, "rev-list", "--first-parent", "--reverse", f"{ENTRY_TRILATT}..HEAD").splitlines() != corrective["TriLatt"]["from_entry_exclusive_through_payload"]: fail("E_REPOSITORY_REF", "TriLatt corrective range")
    if any(not x.startswith(PREFIX) for x in git(mephc, "diff", "--name-only", ENTRY_MEPHC, "HEAD").splitlines()): fail("E_ALLOWLIST", "corrective path outside evidence")
    for path in (DRIVER, PREFIX+"validator_negative_fixtures.py", PREFIX+"validate_r3_1.py", PREFIX+"logs/entrypoint_smoke.log"): git(mephc, "ls-files", "--error-unmatch", path)
    protected = load(bundle, "integrity_digests.json").get("protected", {})
    current = {"r1": tree(mephc, ("docs/architecture/mephc_affine_architecture_r1/",)), "r2": tree(mephc, ("docs/architecture/mephc_affine_architecture_r2/",)), "r3": tree(mephc, ("docs/architecture/mephc_affine_architecture_r3/",)), "scientific": scientific(repos), "sqrlatt_tree": tree(sqrlatt)}
    for key, value in current.items():
        if value != protected.get(key): fail("E_PROTECTED_DIGEST", key)
    return c


def validate_seal_parent(actual_parent: str, expected_parent: str):
    if actual_parent != expected_parent:
        fail("E_SEAL_PARENT", "payload ref is not the seal parent")


def validate_seal_diff(paths: list[str]):
    if paths != SEAL:
        fail("E_SEAL_DIFF_PATH", "seal diff contains a forbidden path")


def validate_repository_ref(actual: str, expected: str):
    if actual != expected:
        fail("E_REPOSITORY_REF", "repository ref does not match the hold point")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-bundle", action="store_true")
    parser.add_argument("--check-worktrees", action="store_true")
    parser.add_argument("--bundle-root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--mephc-root", type=Path)
    parser.add_argument("--trilatt-root", type=Path)
    parser.add_argument("--sqrlatt-root", type=Path)
    parser.add_argument("--require-remote-equality", action="store_true")
    args = parser.parse_args()
    if args.check_bundle == args.check_worktrees: parser.error("choose exactly one validation mode")
    try:
        if args.check_bundle: check_bundle(args.bundle_root)
        else:
            if not all((args.mephc_root, args.trilatt_root, args.sqrlatt_root)): parser.error("worktree roots are required")
            check_worktrees(args.bundle_root, args.mephc_root, args.trilatt_root, args.sqrlatt_root, args.require_remote_equality)
        print("R3.1 VALIDATION PASS"); return 0
    except DiagnosticError as exc:
        print(f"R3.1 VALIDATION FAIL [{exc.code}]: {exc.message}", file=sys.stderr); return 1
    except (subprocess.CalledProcessError, OSError, KeyError) as exc:
        print(f"R3.1 VALIDATION FAIL [E_RUNTIME]: {exc}", file=sys.stderr); return 1


if __name__ == "__main__":
    raise SystemExit(main())
