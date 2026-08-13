"""Strict validator for the R7.1 geometry and real-MPB closure bundle."""
from __future__ import annotations

import json
from pathlib import Path

from mephc.geometry_equivalence import GeometryEquivalence, match_geometry
from mephc.r7_response import DifferentialMaxwellResponse


ROOT = Path(__file__).resolve().parent
REQUIRED = {
    "README.md", "response_contract.md", "change_scope.json", "geometry_equivalence.json",
    "real_mpb_response.json", "runtime_probe.json", "completion_probe.json",
    "run_r7_1_closure.py", "validate_r7_1.py", "test_coverage_matrix.csv", "validation_report.md",
}


def fail(message: str):
    raise SystemExit(f"R7_1_VALIDATION_ERROR: {message}")


def main() -> int:
    missing = sorted(name for name in REQUIRED if not (ROOT / name).is_file())
    if missing:
        fail(f"missing artifacts: {missing}")
    geometry = json.loads((ROOT / "geometry_equivalence.json").read_text())
    if {key: value["status"] for key, value in geometry.items()} != {"SqrLatt": "PASS", "TriLatt": "PASS"}:
        fail("geometry gate did not pass for both downstreams")
    for downstream, report in geometry.items():
        if not report["zero_vs_legacy"]["equivalent"]:
            fail(f"{downstream}: zero geometry is not absolutely equivalent to legacy")
        if not all(state["shape"]["equivalent"] for state in report["states"].values()):
            fail(f"{downstream}: ladder shape equivalence failed")
        if not report["distinct_nonzero_position_errors"]:
            fail(f"{downstream}: nonzero geometries were not pairwise distinct")
    probe = json.loads((ROOT / "runtime_probe.json").read_text())
    if probe.get("solver") != "meep.mpb.ModeSolver" or not probe.get("mode_solver"):
        fail("real MPB runtime probe is missing")
    if probe.get("resolution") != 12 or probe.get("amplitudes") != [0.0, 0.005, -0.005, 0.0025, -0.0025]:
        fail("runtime ladder mismatch")
    responses = json.loads((ROOT / "real_mpb_response.json").read_text())
    for downstream, result in responses.items():
        if len(result.get("raw_provenance", [])) != 15 or len(result.get("responses", [])) != 18:
            fail(f"{downstream}: real raw/response cardinality mismatch")
        if not all(item["settings"]["semantic_domain"] == "supercell_bz" for item in result["raw_provenance"]):
            fail(f"{downstream}: raw provenance is not supercell semantic data")
    if responses["SqrLatt"]["status"] != "PASS_REAL_MPB" or responses["SqrLatt"]["counts"]["pass_differential"] < 2:
        fail("SqrLatt did not close a real differential MPB response")
    completion = json.loads((ROOT / "completion_probe.json").read_text())
    if completion.get("tri_response_claim") or not completion.get("tri_real_data_recorded"):
        fail("TriLatt was either not audited or was incorrectly claimed")
    if completion.get("protected_r6_inputs_modified"):
        fail("protected R6 inputs were modified")
    print("PASS_R7_1_EVIDENCE_BUNDLE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
