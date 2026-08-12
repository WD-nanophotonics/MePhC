"""Strict R6 evidence-bundle validator; supports bundle-only and --root."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

REQUIRED = [
    "README.md", "preflight.json", "response_contract.md", "benchmark_field.json",
    "call_site_matrix.csv", "runtime_probe.json", "convergence.json",
    "sqrlatt_response.json", "trilatt_response.json", "eligibility_matrix.csv",
    "production_smokes.json", "test_coverage_matrix.csv", "validation_report.md",
    "change_scope.json", "integrity_digests.json", "known_limits_and_r7.md",
    "run_r6_response.py", "validate_r6.py", "validator_negative_fixtures.py",
    "artifact_manifest.json", "completion.json",
]
FORBIDDEN = re.compile(r"unfold|berry|chern|bcd|transport|far.?field|primitive.?X|primitive.?M|primitive.?K|primitive.?Gamma", re.I)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate(root: Path):
    errors = []
    for name in REQUIRED:
        if not (root / name).is_file():
            errors.append(f"missing:{name}")
    if errors:
        return errors
    try:
        convergence = json.loads((root / "convergence.json").read_text())
        sq = json.loads((root / "sqrlatt_response.json").read_text())
        tri = json.loads((root / "trilatt_response.json").read_text())
        completion = json.loads((root / "completion.json").read_text())
        manifest = json.loads((root / "artifact_manifest.json").read_text())
        digests = json.loads((root / "integrity_digests.json").read_text())
    except Exception as exc:
        return [f"json:{exc}"]

    if sq.get("status") != "PASS":
        errors.append("SqrLatt must PASS")
    if tri.get("status") not in {"PASS", "BLOCKED_NONCONVERGED", "BLOCKED_BAND_IDENTITY_GUARD"}:
        errors.append("invalid TriLatt status")
    if convergence.get("SqrLatt", {}).get("status") != "PASS":
        errors.append("SqrLatt convergence missing")
    if tri.get("status") == "BLOCKED_NONCONVERGED" and convergence.get("TriLatt", {}).get("status") != "BLOCKED_NONCONVERGED":
        errors.append("TriLatt convergence/status mismatch")
    if completion.get("overall_status") != tri.get("status"):
        errors.append("completion status mismatch")
    if manifest.get("schema") != "mephc.affine_architecture.r6.artifact_manifest.v1":
        errors.append("manifest schema")
    if manifest.get("payload_parent") in {None, "", "PENDING"}:
        errors.append("manifest payload_parent missing")
    listed = digests.get("artifacts", {})
    for name, expected in listed.items():
        path = root / name
        if not path.is_file():
            errors.append(f"digest_missing:{name}")
        elif digest(path) != expected:
            errors.append(f"digest_mismatch:{name}")
    for name in ("sqrlatt_response.json", "trilatt_response.json", "benchmark_field.json", "convergence.json"):
        text = (root / name).read_text(encoding="utf-8")
        if re.search(r'"(unfolding|berry_or_efs_interpretation|primitive_symmetry_reduction)"\s*:\s*true', text, re.I):
            errors.append(f"forbidden_semantics:{name}")
    for response in (sq,):
        for row in response.get("responses", []):
            raw = row["raw"]
            if abs(row["odd_A"] - (raw["wp"] - raw["wm"]) / 2) > 1e-12:
                errors.append("bad_sign_algebra")
            if abs(row["even_A"] - (raw["wp"] + raw["wm"]) / 2 + raw["w0"]) > 1e-12:
                errors.append("bad_even_algebra")
    return errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    errors = validate(args.root.resolve())
    if errors:
        print("R6 VALIDATOR FAIL")
        print("\n".join(errors))
        return 1
    print("R6 VALIDATOR PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

