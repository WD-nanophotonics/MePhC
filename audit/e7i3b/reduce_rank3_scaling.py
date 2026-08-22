"""Evidence-only E7I.3B reduction of qualified rank-3 determinant holonomy."""
from __future__ import annotations

import hashlib
import json
import math
import subprocess
from pathlib import Path

EXPECTED_SOURCE_COMMIT = "0425209b55de7e41e1bbdd349d097dd7bab0c034"
EXPECTED_SOURCE_SHA256 = "3e9521f172958a818474f76479ea8f3a7f7b058e647ea689ac3116f0c29e386a"
EXPECTED_CLASSIFICATION = "E7I3A_RANK3_WILSON_ALGEBRA_QUALIFIED"
PHASE_BRANCH_SAFE_LIMIT = math.pi / 2.0
RELATIVE_METRIC_FLOOR = 100.0 * math.ulp(1.0)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def current_commit(root: Path) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()


def safe_relative(numerator: float, denominator: float) -> float | None:
    scale = max(abs(numerator), abs(denominator))
    if scale <= RELATIVE_METRIC_FLOOR:
        return None
    return float(abs(numerator - denominator) / scale)


def determinant_phase(entry: dict) -> float:
    value = entry["forward"]["Arg_det_W"]
    if value is None or not math.isfinite(float(value)):
        raise ValueError("missing or non-finite forward determinant phase")
    return float(value)


def make_level(case_name: str, case: dict, level: int, entry: dict) -> dict:
    nominal_h = float(case["delta_k"])
    h = nominal_h / (2.0**level)
    area = h * h
    phi = determinant_phase(entry)
    return {
        "case": case_name,
        "level": level,
        "h": h,
        "A_q": area,
        "PHI": phi,
        "DETERMINANT_HOLONOMY_DENSITY_PROXY": float(phi / area),
        "det_W": entry["forward"]["det_W"],
        "unitarity_residual": entry["forward"]["unitarity_residual"],
        "qualification_status": case["qualification"]["forward_status"],
        "qualification_passed": bool(case["qualification"]["forward_qualified"]),
    }


def within_run_scaling(levels: list[dict]) -> dict:
    adjacent = []
    for coarse, fine in zip(levels, levels[1:]):
        phase_area_law_residual = coarse["PHI"] - 4.0 * fine["PHI"]
        coarse_density = coarse["DETERMINANT_HOLONOMY_DENSITY_PROXY"]
        fine_density = fine["DETERMINANT_HOLONOMY_DENSITY_PROXY"]
        adjacent.append({
            "coarse_level": coarse["level"],
            "fine_level": fine["level"],
            "AREA_RATIO": float(coarse["A_q"] / fine["A_q"]),
            "PHASE_AREA_LAW_RESIDUAL": float(phase_area_law_residual),
            "PHASE_AREA_LAW_RELATIVE_RESIDUAL": float(abs(phase_area_law_residual) / max(abs(coarse["PHI"]), abs(4.0 * fine["PHI"]), RELATIVE_METRIC_FLOOR)),
            "DENSITY_PROXY_ABS_DIFFERENCE": float(abs(coarse_density - fine_density)),
            "DENSITY_PROXY_RELATIVE_DIFFERENCE": safe_relative(coarse_density, fine_density),
        })
    max_density_relative_drift = max(
        (item["DENSITY_PROXY_RELATIVE_DIFFERENCE"] or 0.0 for item in adjacent),
        default=0.0,
    )
    return {
        "levels": levels,
        "adjacent_refinement": adjacent,
        "max_density_proxy_relative_drift": float(max_density_relative_drift),
    }


def load_source(root: Path) -> tuple[dict, dict]:
    path = root / "audit" / "e7i3a" / "result.json"
    evidence_sha = sha256(path)
    commit = current_commit(root)
    source = json.loads(path.read_text(encoding="utf-8"))
    if commit != EXPECTED_SOURCE_COMMIT:
        raise RuntimeError(f"source commit mismatch: {commit}")
    if evidence_sha != EXPECTED_SOURCE_SHA256:
        raise RuntimeError(f"source evidence hash mismatch: {evidence_sha}")
    if source.get("classification") != EXPECTED_CLASSIFICATION:
        raise RuntimeError("E7I.3A classification is not algebraically qualified")
    if not source.get("all_rank3_qualification_gates_pass"):
        raise RuntimeError("E7I.3A rank-3 qualification gates did not pass")
    if not source.get("all_algebraic_checks_pass"):
        raise RuntimeError("E7I.3A algebraic checks did not pass")
    binding = {
        "source_path": "audit/e7i3a/result.json",
        "source_git_commit": commit,
        "source_evidence_sha256": evidence_sha,
        "classification": source["classification"],
        "rank_selection_zero_based": source["selection_zero_based"],
        "endpoints": source["endpoints"],
        "plaquettes": source["plaquettes"],
    }
    return source, binding


def collect(source: dict) -> tuple[dict[str, dict], list[dict]]:
    endpoint_results = {}
    all_levels = []
    for endpoint, endpoint_result in source["endpoint_results"].items():
        cases = {}
        for case_name, case in endpoint_result["cases"].items():
            levels = [
                make_level(case_name, case, level, entry)
                for level, entry in enumerate(case["wilson"]["levels"])
            ]
            scaling = within_run_scaling(levels)
            cases[case_name] = {
                "resolution": case["resolution"],
                "nominal_delta_k": case["delta_k"],
                "scaling": scaling,
            }
            for level in levels:
                all_levels.append({"endpoint": endpoint, "resolution": case["resolution"], **level})
        endpoint_results[endpoint] = cases
    return endpoint_results, all_levels


def overlap_reproducibility(all_levels: list[dict]) -> dict:
    result = {}
    for endpoint in ("FR00", "FR050"):
        endpoint_rows = [
            row for row in all_levels
            if row["endpoint"] == endpoint and row["resolution"] == 48
        ]
        rows_by_h: dict[float, list[dict]] = {}
        for row in endpoint_rows:
            rows_by_h.setdefault(round(row["h"], 15), []).append(row)
        comparisons = []
        for label, target_h in (("1/72", 1.0 / 72.0), ("1/144", 1.0 / 144.0)):
            rows = sorted(rows_by_h[round(target_h, 15)], key=lambda row: (row["case"], row["level"]))
            if len(rows) != 2:
                raise RuntimeError(f"expected two R48 replay rows for {endpoint} h={label}")
            first, second = rows
            comparisons.append({
                "h_label": label,
                "h": target_h,
                "sources": [f"{first['case']}:level{first['level']}", f"{second['case']}:level{second['level']}"],
                "REPLAY_PHASE_ABS_DIFFERENCE": float(abs(first["PHI"] - second["PHI"])),
                "REPLAY_DENSITY_PROXY_ABS_DIFFERENCE": float(abs(first["DETERMINANT_HOLONOMY_DENSITY_PROXY"] - second["DETERMINANT_HOLONOMY_DENSITY_PROXY"])),
            })
        result[endpoint] = comparisons
    return result


def resolution_sensitivity(all_levels: list[dict]) -> dict:
    result = {}
    for endpoint in ("FR00", "FR050"):
        comparisons = []
        for target_h, label in ((1.0 / 36.0, "1/36"), (1.0 / 72.0, "1/72"), (1.0 / 144.0, "1/144")):
            rows = [
                row for row in all_levels
                if row["endpoint"] == endpoint and row["resolution"] in (48, 64)
                and math.isclose(row["h"], target_h, rel_tol=0.0, abs_tol=1e-15)
            ]
            by_resolution = {row["resolution"]: row for row in rows}
            if set(by_resolution) != {48, 64}:
                raise RuntimeError(f"missing R48/R64 matching step for {endpoint} h={label}")
            r48, r64 = by_resolution[48], by_resolution[64]
            phase_difference = abs(r48["PHI"] - r64["PHI"])
            density_difference = abs(r48["DETERMINANT_HOLONOMY_DENSITY_PROXY"] - r64["DETERMINANT_HOLONOMY_DENSITY_PROXY"])
            comparisons.append({
                "h_label": label,
                "h": target_h,
                "DELTA_PHASE_RESOLUTION_ABS": float(phase_difference),
                "DELTA_PHASE_RESOLUTION_RELATIVE": safe_relative(r48["PHI"], r64["PHI"]),
                "DELTA_DENSITY_PROXY_RESOLUTION_ABS": float(density_difference),
                "DELTA_DENSITY_PROXY_RESOLUTION_RELATIVE": safe_relative(r48["DETERMINANT_HOLONOMY_DENSITY_PROXY"], r64["DETERMINANT_HOLONOMY_DENSITY_PROXY"]),
            })
        result[endpoint] = comparisons
    return result


def classify(endpoint: str, endpoint_data: dict, max_abs_phase: float, reference_phase: float) -> str:
    if max_abs_phase <= 0.01 * reference_phase and endpoint == "FR050":
        return "SYMMETRY_SUPPRESSED_OR_NEAR_ZERO"
    drift = max(item["scaling"]["max_density_proxy_relative_drift"] for item in endpoint_data.values())
    if drift <= 100.0 * math.ulp(1.0):
        return "SUPPORTED"
    return "SUPPORTED_WITH_VISIBLE_FINITE_STEP_SENSITIVITY"


def self_check(result: dict) -> None:
    assert result["PHASE_BRANCH_STATUS"] == "SAFE"
    assert result["source_binding"]["source_evidence_sha256"] == EXPECTED_SOURCE_SHA256
    for endpoint_data in result["endpoint_results"].values():
        for case in endpoint_data.values():
            levels = case["scaling"]["levels"]
            assert math.isclose(levels[0]["A_q"], levels[0]["h"] ** 2, rel_tol=0.0, abs_tol=0.0)
            assert all(math.isclose(item["AREA_RATIO"], 4.0, rel_tol=0.0, abs_tol=1e-12) for item in case["scaling"]["adjacent_refinement"])
    for endpoint, comparisons in result["overlapping_step_reproducibility"].items():
        assert len(comparisons) == 2, endpoint
    assert safe_relative(0.0, 0.0) is None
    assert safe_relative(2.0, 1.0) == 0.5
    assert json.dumps(result, sort_keys=True, indent=2).endswith("\n") is False


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    source, binding = load_source(root)
    endpoint_results, all_levels = collect(source)
    phase_values = [row["PHI"] for row in all_levels]
    max_abs_phase = max(abs(value) for value in phase_values)
    phase_status = "SAFE" if max_abs_phase < PHASE_BRANCH_SAFE_LIMIT else "UNRESOLVED"
    if phase_status != "SAFE":
        raise RuntimeError("principal-branch proximity makes local scaling ambiguous")
    overlap = overlap_reproducibility(all_levels)
    resolution = resolution_sensitivity(all_levels)
    endpoint_phase = {
        endpoint: max(abs(level["PHI"]) for case in cases.values() for level in case["scaling"]["levels"])
        for endpoint, cases in endpoint_results.items()
    }
    classifications = {
        endpoint: classify(endpoint, cases, endpoint_phase[endpoint], endpoint_phase["FR00"])
        for endpoint, cases in endpoint_results.items()
    }
    result = {
        "schema": "e7i3b_rank3_determinant_small_loop_scaling_v1",
        "work_order": "E7I.3B",
        "source_binding": binding,
        "phase_branch_safe_limit": PHASE_BRANCH_SAFE_LIMIT,
        "MAX_ABS_DETERMINANT_PHASE": max_abs_phase,
        "PHASE_BRANCH_STATUS": phase_status,
        "endpoint_results": endpoint_results,
        "overlapping_step_reproducibility": overlap,
        "resolution_sensitivity": resolution,
        "endpoint_max_abs_phase": endpoint_phase,
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
        "E7I3B_OVERALL": "RANK3_DETERMINANT_SMALL_LOOP_SCALING_READY_FOR_SUPERVISOR_AUDIT",
    }
    self_check(result)
    output = root / "audit" / "e7i3b" / "result.json"
    output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"overall": result["E7I3B_OVERALL"], "FR00": classifications["FR00"], "FR050": classifications["FR050"], "phase_branch": phase_status, "max_abs_phase": max_abs_phase}))


if __name__ == "__main__":
    main()
