"""Hermetic R5 bundle validator and explicit-root worktree gate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parent
REQUIRED = [
    "README.md", "preflight.json", "deformation_field_contract.md",
    "periodicity_capability_contract.md", "call_site_matrix.csv",
    "global_affine_equivalence.json", "local_geometry_validation.json",
    "supercell_validation.json", "workflow_guard_matrix.md",
    "record_identity_contract.md", "production_smokes.json",
    "test_coverage_matrix.csv", "validation_report.md", "change_scope.json",
    "integrity_digests.json", "known_limits_and_r6.md", "validate_r5.py",
    "validator_negative_fixtures.py", "artifact_manifest.json", "completion.json",
]


def fail(code, detail):
    raise SystemExit(f"{code}: {detail}")


def check_bundle(root: Path):
    missing = [name for name in REQUIRED if not (root / name).is_file()]
    if missing:
        fail("E_R5_REQUIRED_ARTIFACT", ", ".join(missing))
    for name in ("preflight.json", "global_affine_equivalence.json", "local_geometry_validation.json", "supercell_validation.json", "change_scope.json", "integrity_digests.json", "completion.json"):
        try:
            json.loads((root / name).read_text(encoding="utf-8"))
        except Exception as exc:
            fail("E_R5_JSON", f"{name}: {exc}")
    contract = json.loads((root / "completion.json").read_text(encoding="utf-8"))
    if set(contract.get("required_modes", [])) != {"GLOBAL_AFFINE_PERIODIC", "SUPERCELL_PERIODIC", "APERIODIC_LOCAL"}:
        fail("E_R5_CAPABILITY_MODES", "required mode set is incomplete")
    if contract.get("r6") is not False:
        fail("E_R5_NO_R6", "R6 must remain unauthorized")
    print("R5 BUNDLE PASS")


def git(root: Path, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def check_worktrees(args):
    roots = {"MePhC": Path(args.mephc_root), "MePhC-SqrLatt": Path(args.sqrlatt_root), "MePhC-TriLatt": Path(args.trilatt_root)}
    expected = {"MePhC": args.expected_mephc_ref, "MePhC-SqrLatt": args.expected_sqrlatt_ref, "MePhC-TriLatt": args.expected_trilatt_ref}
    for name, root in roots.items():
        if git(root, "rev-parse", "HEAD") != expected[name]:
            fail("E_R5_HEAD", name)
        if git(root, "rev-parse", "origin/main") != expected[name]:
            fail("E_R5_REMOTE", name)
        if git(root, "status", "--porcelain"):
            fail("E_R5_DIRTY", name)
    print("R5 WORKTREE PASS")


def main():
    parser = argparse.ArgumentParser()
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--check-bundle", action="store_true")
    modes.add_argument("--check-worktrees", action="store_true")
    parser.add_argument("--bundle-root", type=Path, default=ROOT)
    parser.add_argument("--mephc-root")
    parser.add_argument("--sqrlatt-root")
    parser.add_argument("--trilatt-root")
    parser.add_argument("--expected-mephc-ref")
    parser.add_argument("--expected-sqrlatt-ref")
    parser.add_argument("--expected-trilatt-ref")
    args = parser.parse_args()
    if args.check_bundle:
        check_bundle(args.bundle_root.resolve())
    else:
        if not all(getattr(args, key) for key in ("mephc_root", "sqrlatt_root", "trilatt_root", "expected_mephc_ref", "expected_sqrlatt_ref", "expected_trilatt_ref")):
            fail("E_R5_EXPLICIT_ROOTS", "all repository roots and refs are required")
        check_worktrees(args)


if __name__ == "__main__":
    main()
