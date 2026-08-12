#!/usr/bin/env python3
"""Structural and scientific checks for the R6.1 evidence bundle."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np

REQUIRED = [
    "README.md", "preflight.json", "root_cause.md",
    "corrected_benchmark_field.json", "geometry_activity.json",
    "baseline_reproduction.json", "convergence.json", "sqrlatt_response.json",
    "trilatt_status.json", "eligibility_matrix.csv", "response_contract.md",
    "change_scope.json", "test_coverage_matrix.csv", "validation_report.md",
    "integrity_digests.json", "known_limits_and_r7.md", "validate_r6_1.py",
    "validator_negative_fixtures.py", "artifact_manifest.json", "completion.json",
    "logs/driver_stdout.log",
]

def fail(errors, message):
    errors.append(message)

def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main(root):
    errors = []
    root = Path(root).resolve()
    for name in REQUIRED:
        if not (root / name).is_file():
            fail(errors, f"missing artifact: {name}")
    if errors:
        print("\n".join(errors))
        return 1
    try:
        data = {name: json.loads((root / name).read_text()) for name in (
            "preflight.json", "corrected_benchmark_field.json",
            "geometry_activity.json", "baseline_reproduction.json",
            "convergence.json", "sqrlatt_response.json",
            "trilatt_status.json", "change_scope.json",
            "artifact_manifest.json", "completion.json",
        )}
    except Exception as exc:
        print(f"invalid JSON: {exc}")
        return 1

    field = data["corrected_benchmark_field.json"]
    if field["formula"] != "u_A(xi1,xi2)=A*cos(2*pi*xi1)*cos(2*pi*xi2)*e_x":
        fail(errors, "corrected formula mismatch")
    if field["amplitudes"] != [0.0, 0.005, -0.005, 0.0025, -0.0025]:
        fail(errors, "amplitude ladder mismatch")
    if field["q_points"]["q1"] != [0.12, 0.07] or field["q_points"]["q2"] != [-0.09, 0.14]:
        fail(errors, "q-point mismatch")

    for downstream, report in data["geometry_activity.json"].items():
        if report["status"] != "PASS" or report["failures"]:
            fail(errors, f"{downstream} geometry gate did not pass")
        if len(set(report["geometry_digests"][key] for key in ("0.0", "0.005", "-0.005"))) != 3:
            fail(errors, f"{downstream} geometry digests are not distinct")

    sqr_base = data["baseline_reproduction.json"]["SqrLatt"]
    if not sqr_base["reproduced"]:
        fail(errors, "SqrLatt baseline is not reproduced")
    sqr = data["sqrlatt_response.json"]
    if sqr["status"] != "PASS" or not sqr["nonidentical_across_amplitudes"]:
        fail(errors, "SqrLatt response gate failed")
    expected_raw = {"0.0", "0.005", "-0.005", "0.0025", "-0.0025"}
    if set(sqr["raw_spectra"]) != expected_raw:
        fail(errors, "SqrLatt raw amplitude set mismatch")
    for row in sqr["responses"]:
        point = row["point_id"]
        band = int(row["band_ordinal"])
        baseline = np.asarray(sqr["raw_spectra"]["0.0"])[({"q0":0,"q1":1,"q2":2}[point])]
        observed = max(abs(np.asarray(sqr["raw_spectra"][key])[({"q0":0,"q1":1,"q2":2}[point]), band] - baseline[band])
                       for key in expected_raw - {"0.0"})
        if abs(observed - row["eligibility"]["delta_max"]) > 1e-10:
            fail(errors, f"pooled or incorrect delta_max at {point}/{band}")

    tri_status = data["trilatt_status.json"]["status"]
    if tri_status != "BLOCKED_NONCONVERGED":
        fail(errors, f"unexpected TriLatt status: {tri_status}")
    if not data["baseline_reproduction.json"]["TriLatt"]["reproduced"]:
        fail(errors, "TriLatt zero ladder was not reproduced")
    if data["convergence.json"]["TriLatt"]["status"] != "BLOCKED_NONCONVERGED":
        fail(errors, "TriLatt convergence status mismatch")
    if data["trilatt_status.json"]["full_response_sweep_performed"]:
        fail(errors, "TriLatt full response sweep must not run while blocked")

    scope = data["change_scope.json"]
    if scope["downstream_changes"]:
        fail(errors, "unexpected downstream production changes")
    if scope["protected_paths"] != ["MePhC/docs/architecture/mephc_affine_architecture_r6"]:
        fail(errors, "protected path declaration changed")

    old_root = root.parent / "mephc_affine_architecture_r6"
    old_digest = old_root / "integrity_digests.json"
    if not old_digest.is_file():
        fail(errors, "protected R6 digest manifest missing")
    else:
        old = json.loads(old_digest.read_text())
        for name, expected in old["artifacts"].items():
            path = old_root / name
            if not path.is_file() or sha256(path) != expected:
                fail(errors, f"protected R6 digest mismatch: {name}")

    completion = data["completion.json"]
    if completion["email_sent"] is not False:
        fail(errors, "email write is forbidden")
    if completion["status"] != "PASS_SQRLATT_RESPONSE_TRILATT_BLOCKED_NONCONVERGED":
        fail(errors, "completion terminal status mismatch")

    if errors:
        print("\n".join(errors))
        return 1
    print("PASS_R6_1_EVIDENCE_BUNDLE")
    return 0

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    raise SystemExit(main(parser.parse_args().root))
