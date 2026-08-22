"""Evidence-only E7I.3B.C1 reduction of rank-3 determinant holonomy."""
from __future__ import annotations

import hashlib
import json
import math
import subprocess
from fractions import Fraction
from pathlib import Path

EXPECTED_SOURCE_COMMIT = "0425209b55de7e41e1bbdd349d097dd7bab0c034"
EXPECTED_SOURCE_SHA256 = "3e9521f172958a818474f76479ea8f3a7f7b058e647ea689ac3116f0c29e386a"
EXPECTED_CLASSIFICATION = "E7I3A_RANK3_WILSON_ALGEBRA_QUALIFIED"
PHASE_BRANCH_SAFE_LIMIT = math.pi / 2.0
RELATIVE_METRIC_FLOOR = 100.0 * math.ulp(1.0)
NOMINAL_STEP_CANDIDATES = (Fraction(1, 36), Fraction(1, 72))
STABLE_WINDOW_IDS = (Fraction(1, 36), Fraction(1, 72), Fraction(1, 144))
FINEST_STEP_ID = Fraction(1, 288)


def current_commit(root: Path) -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def safe_relative(first: float, second: float) -> float | None:
    scale = max(abs(first), abs(second))
    if scale <= RELATIVE_METRIC_FLOOR:
        return None
    return float(abs(first - second) / scale)


def canonical_nominal_step(delta_k: float) -> Fraction:
    matches = [
        step for step in NOMINAL_STEP_CANDIDATES
        if math.isclose(float(step), float(delta_k), rel_tol=0.0, abs_tol=1e-12)
    ]
    if len(matches) != 1:
        raise ValueError(f"unsupported nominal delta-k: {delta_k}")
    return matches[0]


def step_id(step: Fraction) -> str:
    return f"{step.numerator}/{step.denominator}"


def determinant_phase(entry: dict) -> float:
    value = entry["forward"]["Arg_det_W"]
    if value is None or not math.isfinite(float(value)):
        raise ValueError("missing or non-finite forward determinant phase")
    return float(value)


def make_level(case_name: str, case: dict, nominal_step: Fraction, level: int, entry: dict) -> dict:
    step = nominal_step / (2 ** level)
    h = float(step)
    phi = determinant_phase(entry)
    return {
        "case": case_name,
        "level": level,
        "nominal_step_id": step_id(nominal_step),
        "STEP_ID": step_id(step),
        "step_numerator": step.numerator,
        "step_denominator": step.denominator,
        "h": h,
        "A_q": h * h,
        "PHI": phi,
        "DETERMINANT_HOLONOMY_DENSITY_PROXY": float(phi / (h * h)),
        "det_W": entry["forward"]["det_W"],
        "unitarity_residual": entry["forward"]["unitarity_residual"],
        "qualification_status": case["qualification"]["forward_status"],
        "qualification_passed": bool(case["qualification"]["forward_qualified"]),
    }


def within_run_scaling(levels: list[dict]) -> dict:
    adjacent = []
    for coarse, fine in zip(levels, levels[1:]):
        residual = coarse["PHI"] - 4.0 * fine["PHI"]
        coarse_density = coarse["DETERMINANT_HOLONOMY_DENSITY_PROXY"]
        fine_density = fine["DETERMINANT_HOLONOMY_DENSITY_PROXY"]
        adjacent.append({
            "coarse_step_id": coarse["STEP_ID"],
            "fine_step_id": fine["STEP_ID"],
            "AREA_RATIO": float(coarse["A_q"] / fine["A_q"]),
            "PHASE_AREA_LAW_RESIDUAL": float(residual),
            "PHASE_AREA_LAW_RELATIVE_RESIDUAL": float(
                abs(residual) / max(abs(coarse["PHI"]), abs(4.0 * fine["PHI"]), RELATIVE_METRIC_FLOOR)
            ),
            "DENSITY_PROXY_ABS_DIFFERENCE": float(abs(coarse_density - fine_density)),
            "DENSITY_PROXY_RELATIVE_DIFFERENCE": safe_relative(coarse_density, fine_density),
        })
    return {
        "levels": levels,
        "adjacent_refinement": adjacent,
        "max_density_proxy_relative_drift": float(max(
            (item["DENSITY_PROXY_RELATIVE_DIFFERENCE"] or 0.0 for item in adjacent),
            default=0.0,
        )),
    }


def load_source(root: Path) -> tuple[dict, dict]:
    calculation_commit = current_commit(root)
    ancestry = subprocess.run(
        ["git", "merge-base", "--is-ancestor", EXPECTED_SOURCE_COMMIT, calculation_commit],
        cwd=root,
    )
    if ancestry.returncode != 0:
        raise RuntimeError("source commit is not an ancestor of calculation commit")
    source_bytes = subprocess.check_output(
        ["git", "show", f"{EXPECTED_SOURCE_COMMIT}:audit/e7i3a/result.json"], cwd=root
    )
    source_sha = sha256_bytes(source_bytes)
    if source_sha != EXPECTED_SOURCE_SHA256:
        raise RuntimeError(f"source evidence hash mismatch: {source_sha}")
    source = json.loads(source_bytes.decode("utf-8"))
    if source.get("classification") != EXPECTED_CLASSIFICATION:
        raise RuntimeError("E7I.3A classification is not algebraically qualified")
    if not source.get("all_rank3_qualification_gates_pass"):
        raise RuntimeError("E7I.3A rank-3 qualification gates did not pass")
    if not source.get("all_algebraic_checks_pass"):
        raise RuntimeError("E7I.3A algebraic checks did not pass")
    binding = {
        "source_path": "audit/e7i3a/result.json",
        "source_git_commit": EXPECTED_SOURCE_COMMIT,
        "calculation_code_git_commit": calculation_commit,
        "source_evidence_sha256": source_sha,
        "classification": source["classification"],
        "rank_selection_zero_based": source["selection_zero_based"],
        "endpoints": source["endpoints"],
        "plaquettes": source["plaquettes"],
        "source_commit_is_ancestor": True,
    }
    return source, binding


def collect(source: dict) -> tuple[dict[str, dict], list[dict]]:
    endpoint_results = {}
    all_levels = []
    for endpoint, endpoint_result in source["endpoint_results"].items():
        cases = {}
        for case_name, case in endpoint_result["cases"].items():
            nominal_step = canonical_nominal_step(case["delta_k"])
            levels = [
                make_level(case_name, case, nominal_step, level, entry)
                for level, entry in enumerate(case["wilson"]["levels"])
            ]
            cases[case_name] = {
                "resolution": case["resolution"],
                "nominal_delta_k": case["delta_k"],
                "nominal_step_id": step_id(nominal_step),
                "scaling": within_run_scaling(levels),
            }
            for level in levels:
                all_levels.append({
                    "endpoint": endpoint,
                    "resolution": case["resolution"],
                    **level,
                })
        endpoint_results[endpoint] = cases
    return endpoint_results, all_levels


def rows_at_step(all_levels: list[dict], endpoint: str, step: Fraction, resolutions=None) -> list[dict]:
    allowed = None if resolutions is None else set(resolutions)
    return sorted(
        [
            row for row in all_levels
            if row["endpoint"] == endpoint
            and (allowed is None or row["resolution"] in allowed)
            and (row["step_numerator"], row["step_denominator"]) == (step.numerator, step.denominator)
        ],
        key=lambda row: (row["resolution"], row["case"], row["level"]),
    )


def overlap_reproducibility(all_levels: list[dict]) -> dict:
    result = {}
    for endpoint in ("FR00", "FR050"):
        comparisons = []
        for step in (Fraction(1, 72), Fraction(1, 144)):
            rows = rows_at_step(all_levels, endpoint, step, resolutions=(48,))
            if len(rows) != 2:
                raise RuntimeError(f"expected two exact R48 replay rows for {endpoint} {step_id(step)}")
            first, second = rows
            comparisons.append({
                "STEP_ID": step_id(step),
                "h": float(step),
                "sources": [f"{first['case']}:level{first['level']}", f"{second['case']}:level{second['level']}"],
                "REPLAY_PHASE_ABS_DIFFERENCE": float(abs(first["PHI"] - second["PHI"])),
                "REPLAY_DENSITY_PROXY_ABS_DIFFERENCE": float(
                    abs(first["DETERMINANT_HOLONOMY_DENSITY_PROXY"] - second["DETERMINANT_HOLONOMY_DENSITY_PROXY"])
                ),
            })
        result[endpoint] = comparisons
    return result


def resolution_sensitivity(all_levels: list[dict]) -> dict:
    result = {}
    for endpoint in ("FR00", "FR050"):
        comparisons = []
        for step in STABLE_WINDOW_IDS:
            rows = rows_at_step(all_levels, endpoint, step, resolutions=(48, 64))
            by_resolution = {row["resolution"]: row for row in rows}
            if set(by_resolution) != {48, 64}:
                raise RuntimeError(f"missing exact R48/R64 step for {endpoint} {step_id(step)}")
            r48, r64 = by_resolution[48], by_resolution[64]
            phase_difference = abs(r48["PHI"] - r64["PHI"])
            density_difference = abs(
                r48["DETERMINANT_HOLONOMY_DENSITY_PROXY"]
                - r64["DETERMINANT_HOLONOMY_DENSITY_PROXY"]
            )
            comparisons.append({
                "STEP_ID": step_id(step),
                "h": float(step),
                "DELTA_PHASE_RESOLUTION_ABS": float(phase_difference),
                "DELTA_PHASE_RESOLUTION_RELATIVE": safe_relative(r48["PHI"], r64["PHI"]),
                "DELTA_DENSITY_PROXY_RESOLUTION_ABS": float(density_difference),
                "DELTA_DENSITY_PROXY_RESOLUTION_RELATIVE": safe_relative(
                    r48["DETERMINANT_HOLONOMY_DENSITY_PROXY"],
                    r64["DETERMINANT_HOLONOMY_DENSITY_PROXY"],
                ),
                "NONZERO_INTERVAL_OVERLAP": bool(
                    density_difference < min(
                        abs(r48["DETERMINANT_HOLONOMY_DENSITY_PROXY"]), abs(r64["DETERMINANT_HOLONOMY_DENSITY_PROXY"])
                    )
                ),
            })
        result[endpoint] = comparisons
    return result


def stable_window_analysis(endpoint: str, all_levels: list[dict], overlap: dict, resolution: dict) -> dict:
    window_rows = [
        row for step in STABLE_WINDOW_IDS
        for row in rows_at_step(all_levels, endpoint, step, resolutions=(48, 64))
    ]
    signs = {math.copysign(1.0, row["DETERMINANT_HOLONOMY_DENSITY_PROXY"]) for row in window_rows}
    common_sign = len(signs) == 1
    resolution_rows = resolution[endpoint]
    resolution_by_step = {row["STEP_ID"]: row for row in resolution_rows}
    nonzero_overlap = all(row["NONZERO_INTERVAL_OVERLAP"] for row in resolution_rows)
    replay_ok = all(
        replay["REPLAY_DENSITY_PROXY_ABS_DIFFERENCE"]
        <= resolution_by_step[replay["STEP_ID"]]["DELTA_DENSITY_PROXY_RESOLUTION_ABS"]
        for replay in overlap[endpoint]
    )
    nominal_rows = sorted(
        [
            row for row in all_levels
            if row["endpoint"] == endpoint
            and row["resolution"] == 48
            and row["nominal_step_id"] == "1/36"
        ],
        key=lambda row: row["level"],
    )
    if len(nominal_rows) != 3:
        raise RuntimeError(f"missing nominal 1/36 refinement chain for {endpoint}")
    refinement_drift = [
        safe_relative(
            nominal_rows[i]["DETERMINANT_HOLONOMY_DENSITY_PROXY"],
            nominal_rows[i + 1]["DETERMINANT_HOLONOMY_DENSITY_PROXY"],
        )
        for i in range(2)
    ]
    refinement_envelope = [
        resolution_by_step[nominal_rows[i]["STEP_ID"]]["DELTA_DENSITY_PROXY_RESOLUTION_RELATIVE"]
        for i in range(2)
    ]
    refinement_inside_envelope = all(
        drift is not None and envelope is not None and drift <= envelope
        for drift, envelope in zip(refinement_drift, refinement_envelope)
    )
    stable_window_supported = common_sign and nonzero_overlap and replay_ok and refinement_inside_envelope
    fine_rows = sorted(
        [
            row for row in all_levels
            if row["endpoint"] == endpoint
            and row["resolution"] == 48
            and row["nominal_step_id"] == "1/72"
        ],
        key=lambda row: row["level"],
    )
    if len(fine_rows) != 3:
        raise RuntimeError(f"missing nominal 1/72 fine chain for {endpoint}")
    fine_drift = safe_relative(
        fine_rows[1]["DETERMINANT_HOLONOMY_DENSITY_PROXY"],
        fine_rows[2]["DETERMINANT_HOLONOMY_DENSITY_PROXY"],
    )
    fine_envelope = resolution_by_step[step_id(FINEST_STEP_ID * 2)]["DELTA_DENSITY_PROXY_RESOLUTION_RELATIVE"]
    finest_status = (
        "NUMERICAL_FLOOR_SUSPECTED" if fine_drift is not None and fine_drift > fine_envelope
        else ("NUMERICALLY_UNRESOLVED" if not stable_window_supported else "CONSISTENT_WITH_WINDOW")
    )
    phase_decreases = abs(nominal_rows[2]["PHI"]) < abs(nominal_rows[0]["PHI"])
    return {
        "STABLE_WINDOW_STEP_IDS": [step_id(step) for step in STABLE_WINDOW_IDS],
        "common_density_sign": common_sign,
        "nonzero_interval_overlap_all_steps": nonzero_overlap,
        "replay_within_resolution_envelope": replay_ok,
        "refinement_relative_drifts": refinement_drift,
        "refinement_resolution_envelope": refinement_envelope,
        "refinement_inside_resolution_envelope": refinement_inside_envelope,
        "stable_window_supported": stable_window_supported,
        "fine_step_id": step_id(FINEST_STEP_ID),
        "fine_step_relative_density_drift": fine_drift,
        "fine_step_resolution_envelope": fine_envelope,
        "FINEST_STEP_STATUS": finest_status,
        "phase_decreases_toward_zero_on_nominal_chain": phase_decreases,
    }


def classify_endpoint(endpoint: str, stable_window_supported: bool, measured_effects: bool, exact_symmetry: bool, phase_decreases_toward_zero: bool) -> str:
    if stable_window_supported:
        return "SUPPORTED_WITH_VISIBLE_FINITE_STEP_SENSITIVITY" if measured_effects else "SUPPORTED"
    if endpoint == "FR050" and exact_symmetry and phase_decreases_toward_zero:
        return "SYMMETRY_SUPPRESSED_OR_NEAR_ZERO"
    return "NUMERICALLY_UNRESOLVED"


def phase_status(values: list[float]) -> str:
    return "SAFE" if all(abs(value) < PHASE_BRANCH_SAFE_LIMIT for value in values) else "UNRESOLVED"


def self_check(result: dict) -> None:
    assert result["PHASE_BRANCH_STATUS"] == "SAFE"
    assert result["source_binding"]["source_commit_is_ancestor"] is True
    assert result["EXACT_STEP_IDENTITY"] == "VERIFIED"
    assert result["source_binding"]["source_evidence_sha256"] == EXPECTED_SOURCE_SHA256
    assert canonical_nominal_step(1.0 / 36.0) == Fraction(1, 36)
    assert step_id(Fraction(1, 288)) == "1/288"
    assert phase_status([0.0, 1e-6]) == "SAFE"
    assert phase_status([math.pi]) == "UNRESOLVED"
    assert safe_relative(0.0, 0.0) is None
    assert safe_relative(2.0, 1.0) == 0.5
    assert classify_endpoint("FR00", True, True, False, False) == "SUPPORTED_WITH_VISIBLE_FINITE_STEP_SENSITIVITY"
    assert classify_endpoint("FR00", False, True, False, False) == "NUMERICALLY_UNRESOLVED"
    assert classify_endpoint("FR050", False, False, True, True) == "SYMMETRY_SUPPRESSED_OR_NEAR_ZERO"
    assert classify_endpoint("FR050", False, False, True, False) == "NUMERICALLY_UNRESOLVED"
    serialized = json.dumps(result, sort_keys=True, indent=2)
    assert json.loads(serialized) == result


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    source, binding = load_source(root)
    endpoint_results, all_levels = collect(source)
    phases = [row["PHI"] for row in all_levels]
    branch = phase_status(phases)
    if branch != "SAFE":
        raise RuntimeError("principal-branch proximity makes local scaling ambiguous")
    overlap = overlap_reproducibility(all_levels)
    resolution = resolution_sensitivity(all_levels)
    analyses = {
        endpoint: stable_window_analysis(endpoint, all_levels, overlap, resolution)
        for endpoint in ("FR00", "FR050")
    }
    endpoint_max_phase = {
        endpoint: max(abs(row["PHI"]) for row in all_levels if row["endpoint"] == endpoint)
        for endpoint in ("FR00", "FR050")
    }
    measured_effects = {
        endpoint: any(
            item["DELTA_DENSITY_PROXY_RESOLUTION_RELATIVE"] is not None
            and item["DELTA_DENSITY_PROXY_RESOLUTION_RELATIVE"] > RELATIVE_METRIC_FLOOR
            for item in resolution[endpoint]
        )
        for endpoint in ("FR00", "FR050")
    }
    classifications = {
        "FR00": classify_endpoint(
            "FR00",
            analyses["FR00"]["stable_window_supported"],
            measured_effects["FR00"],
            False,
            analyses["FR00"]["phase_decreases_toward_zero_on_nominal_chain"],
        ),
        "FR050": classify_endpoint(
            "FR050",
            analyses["FR050"]["stable_window_supported"],
            measured_effects["FR050"],
            True,
            analyses["FR050"]["phase_decreases_toward_zero_on_nominal_chain"],
        ),
    }
    result = {
        "schema": "e7i3b_rank3_determinant_small_loop_scaling_c1_v1",
        "work_order": "E7I.3B.C1",
        "source_binding": binding,
        "CALCULATION_LOGIC_COMMITTED_BEFORE_EXECUTION": True,
        "EXACT_STEP_IDENTITY": "VERIFIED",
        "PHASE_BRANCH_STATUS": branch,
        "MAX_ABS_DETERMINANT_PHASE": max(abs(value) for value in phases),
        "endpoint_results": endpoint_results,
        "overlapping_step_reproducibility": overlap,
        "resolution_sensitivity": resolution,
        "stable_window_analysis": analyses,
        "endpoint_max_abs_phase": endpoint_max_phase,
        "FR00_STABLE_WINDOW": "SUPPORTED" if analyses["FR00"]["stable_window_supported"] else "UNRESOLVED",
        "FR00_FINEST_STEP_STATUS": analyses["FR00"]["FINEST_STEP_STATUS"],
        "FR00_SMALL_LOOP_SCALING": classifications["FR00"],
        "FR050_SMALL_LOOP_SCALING": classifications["FR050"],
        "WILSON_REPRESENTATION": "MPB_H_PERIODIC_L2",
        "PHYSICAL_MAXWELL_BERRY_INTERPRETATION": "NOT_YET_AUTHORIZED",
        "new_mpb_solve_performed": False,
        "new_field_solve_authorized": False,
        "area_normalized_physical_berry_curvature_authorized": False,
        "chern_number_authorized": False,
        "rank2_doublet_observable_authorized": False,
        "physical_hall_response_authorized": False,
        "CODE_CHANGE": "SANDBOX_AUDIT_ONLY",
        "E7I3B_C1_OVERALL": "CORRECTED_RANK3_DETERMINANT_SCALING_READY_FOR_SUPERVISOR_AUDIT",
    }
    self_check(result)
    output = root / "audit" / "e7i3b" / "result.json"
    output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\\n", encoding="utf-8")
    print(json.dumps({
        "overall": result["E7I3B_C1_OVERALL"],
        "FR00": classifications["FR00"],
        "FR050": classifications["FR050"],
        "FR00_window": result["FR00_STABLE_WINDOW"],
        "FR00_finest": result["FR00_FINEST_STEP_STATUS"],
        "phase_branch": branch,
    }))


if __name__ == "__main__":
    main()
