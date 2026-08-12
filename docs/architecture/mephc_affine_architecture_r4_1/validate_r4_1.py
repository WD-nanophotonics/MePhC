"""Portable R4.1 evidence validator.

The bundle mode is deliberately independent of Git, Meep/MPB, network, and
implicit repository locations.  The worktree mode is explicit and computes
Git facts from the roots supplied by the caller.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path


BASELINES = {
    "MePhC": "88f1e24fdbde3ba5ccbeeba4f69cc85d4b199397",
    "MePhC-SqrLatt": "56b4beb21eae277266ed8893c66af95b942c3cab",
    "MePhC-TriLatt": "16cbb988a12f46d5360c64b2c65fdf9fc51e053c",
}
REMOTES = {
    "MePhC": "https://github.com/WD-nanophotonics/MePhC.git",
    "MePhC-SqrLatt": "https://github.com/WD-nanophotonics/MePhC-SqrLatt.git",
    "MePhC-TriLatt": "https://github.com/WD-nanophotonics/MePhC-TriLatt.git",
}
TREE_DIGEST = "51434ca616762dda6b4e5f702c0bd1fa9933b5ebd503ff3e0248b54a99ae863b"
R4_SELECTED = {
    "validate_r4.py": ("ef5902a48d415958bde65280b7ada4bc3cc071b292efbb88dd4b371d75888a36", 10281),
    "completion.json": ("ec9802091617a803db35d614a304e03793962512fcbce57826efaa243ffec5b2", 6306),
    "artifact_manifest.json": ("a1f61f5d131cc51bcb0620861765e47cb4b02756502445c8a9ba3221a93b95fc", 4321),
    "production_smokes.json": ("1a37b3fc6e5091fb8a6590dbb649a89db78a371c7da736818b0af5be69789bc6", 6917),
    "negative_fixture_results.json": ("276d77833f9e0f7f079c988a9f71290115496e5678bbd84c22084182979885f4", 3096),
    "validator_negative_fixtures.py": ("ba19ee381774088275f82b100387556f212820dd075368b0c8528233904a2873", 1030),
    "final_validation_commands.json": ("7388af1e17efabe8bc77ba222300ddbcee087a25c0e96d847860a384fdeb9d25", 1968),
}
REQUIRED_ARTIFACTS = {
    "README.md", "audit_findings.md", "immutable_r4_inputs.json",
    "validation_contract.md", "validate_r4_1.py", "run_negative_fixtures.py",
    "negative_fixture_results.json", "run_final_validation.py",
    "final_validation_commands.json", "change_scope.json", "integrity_digests.json",
    "test_and_smoke_summary.json", "completion.json", "artifact_manifest.json",
}
REQUIRED_CHECKS = {
    "required_artifacts", "manifest_payload_complete", "manifest_digests_match",
    "immutable_r4_input", "required_semantic_gates", "production_smokes",
    "negative_fixtures", "portable_commands", "r5_unauthorized",
}
SMOKE_IDS = {
    "R4-SMOKE-BAND-IDENTITY", "R4-SMOKE-BAND-AFFINE",
    "R4-SMOKE-BERRY-IDENTITY-C4Q", "R4-SMOKE-BERRY-AFFINE-RAW",
    "R4-SMOKE-EFS-AFFINE",
}
HEX40 = re.compile(r"^[0-9a-f]{40}$")


class ValidationFailure(RuntimeError):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def fail(code: str, detail: str) -> None:
    raise ValidationFailure(code, detail)


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - diagnostic path
        fail("E_JSON_INVALID", f"{path.name}: {exc}")


def digest(path: Path) -> tuple[str, int]:
    data = path.read_bytes()
    return hashlib.sha256(data).hexdigest(), len(data)


def payload_files(root: Path) -> list[Path]:
    excluded = {"artifact_manifest.json", "completion.json"}
    return sorted(
        p for p in root.rglob("*")
        if p.is_file() and p.name not in excluded and "__pycache__" not in p.parts
    )


def relative_payload(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in payload_files(root)}


def check_forbidden_text(root: Path) -> None:
    # Construct the developer root without committing it as a reproducibility path.
    forbidden = (chr(47) + "home" + chr(47) + "icy", "C:\\", "D:\\")
    persistent_tmp = chr(47) + "tmp" + chr(47)
    for path in payload_files(root):
        if path.suffix.lower() not in {".json", ".md", ".csv", ".log", ".txt"}:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if any(token in text for token in forbidden) or persistent_tmp in text:
            fail("E_UNSAFE_REPRODUCIBILITY_PATH", path.relative_to(root).as_posix())
        if re.search(r"(^|[=\s])/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", text):
            fail("E_UNSAFE_REPRODUCIBILITY_PATH", path.relative_to(root).as_posix())


def immutable_r4_check(root: Path) -> None:
    inputs = load_json(root / "immutable_r4_inputs.json")
    if inputs.get("baseline_ref") != BASELINES["MePhC"]:
        fail("E_IMMUTABLE_R4_DIGEST_CHANGED", "baseline ref")
    if inputs.get("tree_sha256") != TREE_DIGEST:
        fail("E_IMMUTABLE_R4_DIGEST_CHANGED", "R4 tree digest")
    selected = inputs.get("selected_artifacts", {})
    for name, (sha, size) in R4_SELECTED.items():
        if selected.get(name, {}).get("sha256") != sha or selected.get(name, {}).get("size") != size:
            fail("E_IMMUTABLE_R4_DIGEST_CHANGED", name)


def manifest_check(root: Path) -> None:
    manifest = load_json(root / "artifact_manifest.json")
    if manifest.get("excludes") != ["artifact_manifest.json", "completion.json", "__pycache__"]:
        fail("E_MANIFEST_SCHEMA", "exclusions")
    actual = relative_payload(root)
    listed = set(manifest.get("artifacts", {}))
    if listed != actual:
        missing = sorted(actual - listed)
        extra = sorted(listed - actual)
        fail("E_MANIFEST_OMISSION" if missing else "E_MANIFEST_EXTRA", f"missing={missing} extra={extra}")
    for rel in sorted(actual):
        path = root / rel
        expected = manifest["artifacts"].get(rel, {})
        sha, size = digest(path)
        if expected.get("sha256") != sha or expected.get("size") != size:
            fail("E_MANIFEST_DIGEST_MISMATCH", rel)


def semantic_check(root: Path) -> None:
    completion = load_json(root / "completion.json")
    checks = set(completion.get("validator_summary", {}).get("required_checks", []))
    if checks != REQUIRED_CHECKS:
        fail("E_REQUIRED_CHECK_SET", "required checks")
    if completion.get("status") != "PASS":
        fail("E_COMPLETION_STATUS", "completion is not PASS")
    gates = completion.get("gates", {})
    if not gates or any(value != "PASS" for value in gates.values()):
        fail("E_COMPLETED_WITH_REQUIRED_FAILURE", "gate status")
    if completion.get("c4_verifier_evidence") is not True:
        fail("E_C4_EVIDENCE", "missing C4 verifier evidence")
    policy = completion.get("c4_policy", {})
    if policy.get("identity_mode") != "c4q" or policy.get("nonidentity_auto_mode") != "raw_bz":
        fail("E_NONIDENTITY_FALSE_C4_CLAIM", "C4 policy")
    workflow = completion.get("workflow_policy", {})
    if workflow.get("nonidentity_band_path") == "gxm":
        fail("E_NONIDENTITY_FALSE_GXM_CLAIM", "GXM path")
    if workflow.get("nonidentity_sampling") == "fixed_square":
        fail("E_NONIDENTITY_FIXED_SQUARE_DOMAIN", "fixed square domain")
    if completion.get("r5_authorized") is not False or completion.get("r5_started") is not False:
        fail("E_R5_AUTHORIZED", "R5 state")
    if completion.get("trilatt_hold_ref") != BASELINES["MePhC-TriLatt"]:
        fail("E_TRILATT_HOLD_REF", "hold ref")
    topology = completion.get("seal", {})
    if topology.get("diff_paths") != [
        "docs/architecture/mephc_affine_architecture_r4_1/artifact_manifest.json",
        "docs/architecture/mephc_affine_architecture_r4_1/completion.json",
    ]:
        fail("E_SEAL_FORBIDDEN_PATH", "seal diff paths")
    if topology.get("payload_ref") != completion.get("validated_payload_ref"):
        fail("E_PAYLOAD_NOT_SEAL_PARENT", "payload binding")


def smoke_check(root: Path) -> None:
    summary = load_json(root / "test_and_smoke_summary.json")
    smokes = {item.get("id"): item for item in summary.get("smokes", [])}
    if set(smokes) != SMOKE_IDS:
        fail("E_REQUIRED_SMOKE", "smoke IDs")
    for smoke_id, item in smokes.items():
        assertions = item.get("assertions", {})
        if not assertions:
            fail("E_SMOKE_ASSERTION", smoke_id)
        if any(value is not True for value in assertions.values()):
            fail("E_SMOKE_ASSERTION_FALSE", smoke_id)
        rel = item.get("log")
        if not rel or not (root / rel).is_file() or (root / rel).stat().st_size == 0:
            fail("E_SMOKE_LOG", smoke_id)
        sha, size = digest(root / rel)
        if item.get("log_sha256") != sha or item.get("log_size") != size:
            fail("E_SMOKE_LOG_BINDING", smoke_id)
        command = item.get("command", "")
        if any(token in command for token in ("--mephc-root", "--sqrlatt-root", "--trilatt-root")):
            fail("E_UNSAFE_REPRODUCIBILITY_PATH", smoke_id)


def check_bundle(root: Path) -> None:
    missing = sorted(name for name in REQUIRED_ARTIFACTS if not (root / name).is_file())
    if missing:
        fail("E_REQUIRED_ARTIFACT", ",".join(missing))
    immutable_r4_check(root)
    check_forbidden_text(root)
    manifest_check(root)
    semantic_check(root)
    smoke_check(root)
    fixture_results = load_json(root / "negative_fixture_results.json")
    if fixture_results.get("count", 0) < 19 or fixture_results.get("all_passed") is not True:
        fail("E_NEGATIVE_FIXTURES", "fixture summary")
    print("R4.1 BUNDLE PASS")


def run_git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-c", "core.filemode=false", "-C", str(root), *args],
        text=True, capture_output=True, check=False,
    )


def git_value(root: Path, *args: str) -> str:
    result = run_git(root, *args)
    if result.returncode:
        fail("E_GIT_COMMAND", " ".join(args))
    return result.stdout.strip()


def check_worktrees(args: argparse.Namespace, root: Path) -> None:
    paths = {
        "MePhC": Path(args.mephc_root),
        "MePhC-SqrLatt": Path(args.sqrlatt_root),
        "MePhC-TriLatt": Path(args.trilatt_root),
    }
    expected = {
        "MePhC": args.expected_mephc_ref,
        "MePhC-SqrLatt": BASELINES["MePhC-SqrLatt"],
        "MePhC-TriLatt": BASELINES["MePhC-TriLatt"],
    }
    for name, path in paths.items():
        if git_value(path, "remote", "get-url", "origin") != REMOTES[name]:
            fail("E_REMOTE_IDENTITY", name)
        if git_value(path, "rev-parse", "HEAD") != expected[name]:
            fail("E_LOCAL_HEAD", name)
        if git_value(path, "rev-parse", "origin/main") != expected[name]:
            fail("E_ORIGIN_MAIN", name)
        if run_git(path, "merge-base", "--is-ancestor", expected[name], "origin/main").returncode:
            fail("E_REMOTE_CONTAINMENT", name)
        if git_value(path, "status", "--porcelain=v2", "--untracked-files=all"):
            fail("E_WORKTREE_DIRTY", name)
    mephc = paths["MePhC"]
    payload = args.expected_payload_ref
    if git_value(mephc, "rev-parse", f"{expected['MePhC']}^") != payload:
        fail("E_PAYLOAD_NOT_SEAL_PARENT", "seal parent")
    changed = git_value(mephc, "diff", "--name-only", BASELINES["MePhC"], expected["MePhC"]).splitlines()
    prefix = "docs/architecture/mephc_affine_architecture_r4_1/"
    if any(not item.startswith(prefix) for item in changed):
        fail("E_PROTECTED_PATH_MUTATION", "changed path")
    seal_diff = git_value(mephc, "diff", "--name-only", payload, expected["MePhC"]).splitlines()
    if seal_diff != [
        "docs/architecture/mephc_affine_architecture_r4_1/artifact_manifest.json",
        "docs/architecture/mephc_affine_architecture_r4_1/completion.json",
    ]:
        fail("E_SEAL_FORBIDDEN_PATH", "actual seal diff")
    print("R4.1 WORKTREE PASS")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--check-bundle", action="store_true")
    modes.add_argument("--check-worktrees", action="store_true")
    parser.add_argument("--bundle-root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--mephc-root")
    parser.add_argument("--sqrlatt-root")
    parser.add_argument("--trilatt-root")
    parser.add_argument("--expected-mephc-ref")
    parser.add_argument("--expected-payload-ref")
    args = parser.parse_args(argv)
    try:
        if args.check_bundle:
            check_bundle(args.bundle_root.resolve())
        else:
            if not all((args.mephc_root, args.sqrlatt_root, args.trilatt_root,
                        args.expected_mephc_ref, args.expected_payload_ref)):
                fail("E_EXPLICIT_ROOTS_REQUIRED", "worktree roots and refs are required")
            check_worktrees(args, args.bundle_root.resolve())
        return 0
    except ValidationFailure as exc:
        print(f"R4.1 FAIL {exc.code}: {exc.detail}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
