"""Validate the sealed R3.1 delivery bundle.

``--check-bundle`` is deterministic and can validate a copied fixture.
``--check-worktrees`` additionally checks the live MePhC, TriLatt, and SqrLatt
refs, ancestry, clean state, protected digests, and the metadata-seal diff.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path


MEPHC = Path(__file__).resolve().parents[3]
TRILATT = MEPHC.parent / "TriLatt"
SQRLATT = MEPHC.parent / "SqrLatt"
ARTIFACT = Path(__file__).resolve().parent
EVIDENCE_PREFIX = "docs/architecture/mephc_affine_architecture_r3_1/"
ENTRY_MEPHC = "24e29d9c9c6ceae979e1a81953c4f54853f98808"
ENTRY_TRILATT = "df2cdf4fd70e741e1a8901a9274a0b0e42b1e737"
ENTRY_SQRLATT = "8a1e4534a48e01a83996fb199ccd55e0983e72b2"
NAMED_GATES = {
    "all_motif_centers_affine",
    "rigid_local_features",
    "frequency_landmark_migrated",
    "production_entry_smokes",
    "documentation_current",
}
SEAL_ALLOWLIST = {
    EVIDENCE_PREFIX + "completion.json",
    EVIDENCE_PREFIX + "artifact_manifest.json",
}
REQUIRED = {
    "README.md", "baseline.json", "change_scope.json", "geometry_validation.json",
    "k_landmark_validation.json", "entrypoint_smoke.json", "test_runs.json",
    "integrity_digests.json", "validation_report.md", "completion.json",
    "artifact_manifest.json", "validate_r3_1.py", "run_r3_1_smokes.py",
    "validator_negative_fixtures.py",
}
REQUIRED_LOGS = {
    "compileall.log", "mephc_tests.log", "trilatt_tests.log", "r2_validator.log",
    "r3_validator.log", "r31_negative_fixtures.log", "entrypoint_smoke.log",
}


def fail(message: str) -> None:
    raise ValueError(message)


def load(root: Path, name: str):
    return json.loads((root / name).read_text(encoding="utf-8"))


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def git_tree(repo: Path, prefixes=None) -> dict:
    files = git(repo, "ls-files").splitlines()
    if prefixes:
        files = [item for item in files if any(item == p or item.startswith(p) for p in prefixes)]
    digest = hashlib.sha256()
    for relative in sorted(files):
        digest.update(f"{repo.name}/{relative}".encode())
        digest.update(b"\0")
        digest.update((repo / relative).read_bytes())
        digest.update(b"\0")
    return {"sha256": digest.hexdigest(), "file_count": len(files)}


def scientific_digest() -> dict:
    values = {repo.name: git_tree(repo, ("data/", "image/", "diagnostics/")) for repo in (MEPHC, TRILATT, SQRLATT)}
    digest = hashlib.sha256()
    for name in ("MePhC", "TriLatt", "SqrLatt"):
        digest.update(f"{name}:{values[name]['sha256']}".encode())
    return {"sha256": digest.hexdigest(), "repositories": values}


def actual_payload_files(root: Path) -> set[str]:
    return {
        str(path.relative_to(root)).replace("\\", "/")
        for path in root.rglob("*")
        if path.is_file() and path.name != "artifact_manifest.json"
    }


def check_manifest(root: Path) -> dict:
    manifest = load(root, "artifact_manifest.json")
    if manifest.get("status") != "PASS" or manifest.get("algorithm") != "sha256":
        fail("manifest status or algorithm is invalid")
    if manifest.get("excluded_paths") != ["artifact_manifest.json"]:
        fail("manifest must exclude only itself")
    entries = manifest.get("artifacts", [])
    paths = [item.get("path") for item in entries]
    if len(paths) != len(set(paths)):
        fail("manifest contains duplicate paths")
    actual = actual_payload_files(root)
    if set(paths) != actual:
        fail(f"manifest payload mismatch; missing={sorted(actual - set(paths))}, extra={sorted(set(paths) - actual)}")
    if "completion.json" not in paths or "run_r3_1_smokes.py" not in paths:
        fail("manifest omits completion or committed smoke driver")
    for item in entries:
        path = root / item["path"]
        if not path.is_file() or item.get("size") != path.stat().st_size or item.get("sha256") != file_digest(path):
            fail(f"manifest digest or size mismatch: {item.get('path')}")
    return manifest


def check_json_gates(root: Path) -> dict:
    completion = load(root, "completion.json")
    if completion.get("task_id") != "mephc-affine-architecture-r3.1-delivery-closure":
        fail("invalid task_id")
    if completion.get("status") != "PASS" or completion.get("r4_authorized") is not False:
        fail("invalid completion status or R4 flag")
    if completion.get("independent_review_required") is not True:
        fail("independent review flag is missing")
    if completion.get("submission_ref_policy") != "external_post_push_receipt":
        fail("invalid submission_ref_policy")
    if completion.get("metadata_seal_paths") != sorted(SEAL_ALLOWLIST):
        fail("metadata seal path allowlist is invalid")
    if set(completion.get("defect_gates", {})) != NAMED_GATES:
        fail("named defect gates are missing or abbreviated")
    if any(value != "PASS" for value in completion["defect_gates"].values()):
        fail("a named defect gate is not PASS")

    validator_summary = completion.get("validator_summary")
    required_validator_keys = {"bundle", "worktrees", "negative_fixtures", "required_checks"}
    if not isinstance(validator_summary, dict) or not required_validator_keys <= set(validator_summary):
        fail("validator_summary is missing or incomplete")
    if any(value != "PASS" for key, value in validator_summary.items() if key != "required_checks"):
        fail("validator summary contains a non-PASS result")
    if any(value != "PASS" for value in validator_summary["required_checks"].values()):
        fail("a required validator check is not PASS")

    tests = completion.get("test_summary", {})
    for key in ("MePhC_tests", "TriLatt_tests", "compileall", "R2_validator", "R3_validator", "R3_1_negative_fixtures", "production_smokes"):
        if tests.get(key, {}).get("status") != "PASS":
            fail(f"missing or failed test summary: {key}")
    if tests["MePhC_tests"].get("tests_run", 0) < 33 or tests["TriLatt_tests"].get("tests_run", 0) < 28:
        fail("test baseline is below the required count")
    if tests["production_smokes"].get("skipped"):
        fail("production smokes were skipped")
    smoke = tests["production_smokes"]
    driver = smoke.get("driver_path", "")
    if not driver.startswith(EVIDENCE_PREFIX) or "/tmp" in driver or driver.startswith("/"):
        fail("smoke driver path is not repository-relative")
    if not (root / "run_r3_1_smokes.py").is_file():
        fail("committed smoke driver is missing")
    entries = smoke.get("entries", {})
    required_entries = {
        "band_non_identity_low_resolution",
        "berry_non_identity_low_resolution",
        "efs_non_identity_low_resolution",
        "frequency_at_tracked_K1_non_identity_low_resolution",
    }
    if set(entries) != required_entries or any(item.get("status") != "PASS" for item in entries.values()):
        fail("production smoke entries are incomplete or not PASS")

    ranges = completion.get("complete_commit_ranges", {})
    for repo_name in ("MePhC", "TriLatt"):
        values = ranges.get(repo_name, {}).get("from_reviewed_entry_exclusive_through_payload", [])
        if not values or len(values) != len(set(values)):
            fail(f"commit range missing or duplicated for {repo_name}")
    refs = completion.get("reviewed_entry_refs", {})
    if refs.get("MePhC") != ENTRY_MEPHC or refs.get("TriLatt") != ENTRY_TRILATT or refs.get("SqrLatt") != ENTRY_SQRLATT:
        fail("reviewed entry refs are invalid")
    validated = completion.get("validated_payload_refs", {})
    if not all(isinstance(validated.get(name), str) and len(validated[name]) == 40 for name in ("MePhC", "TriLatt")):
        fail("validated payload refs are incomplete")
    return completion


def check_bundle(root: Path) -> None:
    missing = sorted(REQUIRED - {path.name for path in root.iterdir() if path.is_file()})
    if missing:
        fail(f"missing required artifact(s): {missing}")
    logs = {path.name for path in (root / "logs").glob("*.log")}
    if not REQUIRED_LOGS <= logs:
        fail(f"missing required logs: {sorted(REQUIRED_LOGS - logs)}")
    check_manifest(root)
    completion = check_json_gates(root)
    geometry = load(root, "geometry_validation.json")
    landmark = load(root, "k_landmark_validation.json")
    if not geometry.get("all_passed") or not landmark.get("all_passed"):
        fail("geometry or landmark validation is not PASS")
    smoke = load(root, "entrypoint_smoke.json")
    if smoke.get("status") != "PASS" or set(smoke.get("entries", {})) != {
        "band_non_identity_low_resolution", "berry_non_identity_low_resolution",
        "efs_non_identity_low_resolution", "frequency_at_tracked_K1_non_identity_low_resolution",
    }:
        fail("entrypoint_smoke.json is incomplete")
    scope = load(root, "change_scope.json")
    if not scope.get("allowlist_passed", False):
        fail("change scope allowlist failed")
    integrity = load(root, "integrity_digests.json")
    protected = integrity.get("protected", {})
    current = {
        "r1": git_tree(MEPHC, ("docs/architecture/mephc_affine_architecture_r1/",)),
        "r2": git_tree(MEPHC, ("docs/architecture/mephc_affine_architecture_r2/",)),
        "r3": git_tree(MEPHC, ("docs/architecture/mephc_affine_architecture_r3/",)),
        "scientific": scientific_digest(),
        "sqrlatt_tree": git_tree(SQRLATT),
    }
    for key in ("r1", "r2", "r3", "scientific", "sqrlatt_tree"):
        if current[key] != protected.get(key):
            fail(f"protected digest changed: {key}")
    return completion


def check_worktrees(completion: dict) -> None:
    if any(git(repo, "status", "--porcelain") for repo in (MEPHC, TRILATT, SQRLATT)):
        fail("a worktree is dirty")
    if git(MEPHC, "rev-parse", "HEAD^") != completion["validated_payload_refs"]["MePhC"]:
        fail("validated_payload_refs.MePhC is not HEAD^")
    if git(TRILATT, "rev-parse", "HEAD") != completion["validated_payload_refs"]["TriLatt"]:
        fail("TriLatt ref does not match sealed completion")
    if git(SQRLATT, "rev-parse", "HEAD") != ENTRY_SQRLATT:
        fail("SqrLatt hold ref changed")
    if git(MEPHC, "diff", "--name-only", "HEAD^", "HEAD").splitlines() != sorted(SEAL_ALLOWLIST):
        fail("metadata seal diff is outside the allowlist")
    if git(MEPHC, "rev-parse", "HEAD") != git(MEPHC, "rev-parse", "origin/main"):
        fail("MePhC HEAD is not equal to origin/main")
    if git(TRILATT, "rev-parse", "HEAD") != git(TRILATT, "rev-parse", "origin/main"):
        fail("TriLatt HEAD is not equal to origin/main")
    if git(SQRLATT, "rev-parse", "HEAD") != git(SQRLATT, "rev-parse", "origin/main"):
        fail("SqrLatt HEAD is not equal to origin/main")
    subprocess.check_call(["git", "-C", str(MEPHC), "merge-base", "--is-ancestor", ENTRY_MEPHC, "HEAD"])
    subprocess.check_call(["git", "-C", str(TRILATT), "merge-base", "--is-ancestor", ENTRY_TRILATT, "HEAD"])
    ranges = completion["complete_commit_ranges"]
    mephc_range = git(MEPHC, "rev-list", "--first-parent", "--reverse", f"{ENTRY_MEPHC}..HEAD^").splitlines()
    trilatt_range = git(TRILATT, "rev-list", "--first-parent", "--reverse", f"{ENTRY_TRILATT}..HEAD").splitlines()
    if mephc_range != ranges["MePhC"]["from_reviewed_entry_exclusive_through_payload"]:
        fail("MePhC complete commit range is inconsistent")
    if trilatt_range != ranges["TriLatt"]["from_reviewed_entry_exclusive_through_payload"]:
        fail("TriLatt complete commit range is inconsistent")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-bundle", action="store_true")
    parser.add_argument("--check-worktrees", action="store_true")
    parser.add_argument("--bundle-root", type=Path, default=ARTIFACT)
    args = parser.parse_args()
    if not args.check_bundle and not args.check_worktrees:
        parser.error("choose --check-bundle or --check-worktrees")
    try:
        completion = check_bundle(args.bundle_root)
        if args.check_worktrees:
            check_worktrees(completion)
        print("R3.1 VALIDATION PASS")
        return 0
    except (ValueError, subprocess.CalledProcessError, OSError, KeyError, json.JSONDecodeError) as exc:
        print(f"R3.1 VALIDATION FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
