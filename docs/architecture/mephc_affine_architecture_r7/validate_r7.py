"""Strict validator for the R7 equivalence-aware qualification bundle."""
from __future__ import annotations

import json
from pathlib import Path

from mephc import DifferentialMaxwellResponse, SpectralEquivalence
from mephc.r7_response import match_equivalent_spectrum, qualify_differential_maxwell_response


ROOT = Path(__file__).resolve().parent
REQUIRED = {
    "README.md", "response_contract.md", "change_scope.json", "qualification_matrix.json",
    "validation_report.md", "run_r7_qualification.py", "validate_r7.py", "test_coverage_matrix.csv",
}


def fail(message: str):
    raise SystemExit(f"R7_VALIDATION_ERROR: {message}")


def main() -> int:
    missing = sorted(name for name in REQUIRED if not (ROOT / name).is_file())
    if missing:
        fail(f"missing artifacts: {missing}")
    payload = json.loads((ROOT / "qualification_matrix.json").read_text())
    if payload.get("schema") != "mephc.affine_architecture.r7.qualification.v1":
        fail("qualification schema mismatch")
    counts = payload.get("real_counts", {})
    if counts != {"total": 18, "pass_differential": 5, "equivalent_null": 1, "blocked": 12}:
        fail(f"unexpected real qualification counts: {counts}")
    fixture = payload.get("permutation_fixture", {})
    if not fixture.get("equivalent") or fixture.get("assignment") == [0, 1, 2]:
        fail("permutation fixture did not prove non-identity equivalence")
    null_fixture = payload.get("null_fixture", {})
    if null_fixture.get("status") != "EQUIVALENT_NULL" or null_fixture.get("qualified"):
        fail("null fixture qualified as a physical response")
    if not isinstance(match_equivalent_spectrum([1.0], [1.0]), SpectralEquivalence):
        fail("equivalence API type mismatch")
    if not isinstance(qualify_differential_maxwell_response("q", 0, {0.0: [1.0], 0.005: [1.0], -0.005: [1.0], 0.0025: [1.0], -0.0025: [1.0]}, 0.0), DifferentialMaxwellResponse):
        fail("qualification API type mismatch")
    print("PASS_R7_EVIDENCE_BUNDLE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
