"""Strict validator for the R7.2 sign and differential-resolution closure."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REQUIRED = {
    "README.md", "response_contract.md", "change_scope.json",
    "real_mpb_response.json", "sign_equivalence_spectra.json",
    "sign_equivalence_geometry.json", "differential_resolution_ladder.json",
    "runtime_probe.json", "completion_probe.json", "run_r7_2_closure.py",
    "validate_r7_2.py", "test_coverage_matrix.csv", "validation_report.md",
}
RESOLUTIONS = ("8", "12", "16")
POINTS = ("q0", "q1", "q2")


def fail(message: str):
    raise SystemExit(f"R7_2_VALIDATION_ERROR: {message}")


def read(name: str):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def main() -> int:
    missing = sorted(name for name in REQUIRED if not (ROOT / name).is_file())
    if missing:
        fail(f"missing artifacts: {missing}")

    runtime = read("runtime_probe.json")
    if runtime.get("solver") != "meep.mpb.ModeSolver" or not runtime.get("mode_solver"):
        fail("real MPB runtime probe is missing")
    if runtime.get("resolutions") != [8, 12, 16]:
        fail("resolution ladder is not [8, 12, 16]")
    if runtime.get("amplitudes") != [0.0, 0.005, -0.005, 0.0025, -0.0025]:
        fail("signed amplitude ladder is incomplete")

    geometry = read("sign_equivalence_geometry.json")
    for downstream, report in geometry.items():
        if not report.get("equivalent") or report.get("reason") != "EQUIVALENT_PERIODIC_TRANSLATION":
            fail(f"{downstream}: periodic sign geometry did not pass")
        if len(report.get("translation", [])) != 2:
            fail(f"{downstream}: missing declared Cartesian translation")

    spectra = read("sign_equivalence_spectra.json")
    for downstream, by_resolution in spectra.items():
        if set(by_resolution) != set(RESOLUTIONS):
            fail(f"{downstream}: incomplete spectral resolution ladder")
        for resolution, by_point in by_resolution.items():
            if set(by_point) != set(POINTS):
                fail(f"{downstream}/{resolution}: spectral point cardinality mismatch")
            for point_id, report in by_point.items():
                if not report.get("equivalent") or report.get("reason") != "EQUIVALENT_SPECTRUM":
                    fail(f"{downstream}/{resolution}/{point_id}: +A/-A spectrum mismatch")
                if not report.get("spectrum", {}).get("identity_match"):
                    fail(f"{downstream}/{resolution}/{point_id}: semantic identity mismatch")

    responses = read("real_mpb_response.json")
    for downstream, by_resolution in responses.items():
        if set(by_resolution) != set(RESOLUTIONS):
            fail(f"{downstream}: incomplete real-MPB response ladder")
        for resolution, result in by_resolution.items():
            raw = result.get("raw_spectra", {})
            if set(raw) != {"0.0", "0.005", "-0.005", "0.0025", "-0.0025"}:
                fail(f"{downstream}/{resolution}: raw signed amplitude cardinality mismatch")
            if any(set(points) != set(POINTS) for points in raw.values()):
                fail(f"{downstream}/{resolution}: raw q-point cardinality mismatch")
            if len(result.get("responses", {})) != 18:
                fail(f"{downstream}/{resolution}: differential response cardinality mismatch")
            for spectrum in raw.values():
                for item in spectrum.values():
                    if item.get("solver") != "meep.mpb.ModeSolver":
                        fail(f"{downstream}/{resolution}: non-MPB raw provenance")
                    if item.get("settings", {}).get("semantic_domain") != "supercell_bz":
                        fail(f"{downstream}/{resolution}: primitive/supercell semantic leak")

    ladders = read("differential_resolution_ladder.json")
    if ladders["SqrLatt"].get("status") != "PASS" or ladders["SqrLatt"].get("accepted_resolution") != 12:
        fail("SqrLatt differential ladder did not close at resolution 12")
    if ladders["TriLatt"].get("status") != "BLOCKED_DIFFERENTIAL_NONCONVERGED":
        fail("TriLatt non-convergence was not preserved as an explicit block")
    completion = read("completion_probe.json")
    if completion.get("status") != "PASS_R7_2_SIGN_EQUIVALENCE_DIFFERENTIAL_LADDER":
        fail("completion status mismatch")
    if completion.get("SqrLatt_claim") is not True or completion.get("TriLatt_claim") is not False:
        fail("downstream qualification claim mismatch")
    if completion.get("protected_r6_inputs_modified") or not completion.get("tri_real_data_recorded"):
        fail("protected inputs or TriLatt audit invariant failed")
    print("PASS_R7_2_EVIDENCE_BUNDLE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
