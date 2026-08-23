"""E9D reducer: descriptors, TRS controls, replay and compact authoritative result."""
from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SIDE = 1.0 / 36.0
BANDS = (0, 1, 2)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def finite_values(rows, band):
    return [
        (row["offset_from_K_prime"], row["bands"][band]["Omega_over_a2"])
        for row in rows
        if row["bands"][band]["qualification_status"] == "QUALIFIED" and row["bands"][band]["Omega_over_a2"] is not None
    ]


def descriptor(rows, band):
    values = finite_values(rows, band)
    if not values:
        return {
            "center_value": None, "max_value": None, "max_location_offset": None,
            "min_value": None, "min_location_offset": None, "max_abs_value": None,
            "max_abs_location_offset": None, "positive_pixel_count": 0, "negative_pixel_count": 0,
            "reported_pixel_count": 0, "unreported_pixel_count": len(rows),
            "weighted_centroid_of_abs_omega": None, "second_moment_radius_of_abs_omega": None,
        }
    center = next((value for offset, value in values if abs(offset[0]) < 1e-15 and abs(offset[1]) < 1e-15), None)
    max_pair = max(values, key=lambda item: item[1])
    min_pair = min(values, key=lambda item: item[1])
    abs_pair = max(values, key=lambda item: abs(item[1]))
    total = sum(abs(value) for _, value in values)
    cx = sum(abs(value) * offset[0] for offset, value in values) / total
    cy = sum(abs(value) * offset[1] for offset, value in values) / total
    moment = math.sqrt(sum(abs(value) * (offset[0] ** 2 + offset[1] ** 2) for offset, value in values) / total)
    return {
        "center_value": center,
        "max_value": max_pair[1], "max_location_offset": max_pair[0],
        "min_value": min_pair[1], "min_location_offset": min_pair[0],
        "max_abs_value": abs_pair[1], "max_abs_location_offset": abs_pair[0],
        "positive_pixel_count": sum(value > 0.0 for _, value in values),
        "negative_pixel_count": sum(value < 0.0 for _, value in values),
        "reported_pixel_count": len(values),
        "unreported_pixel_count": len(rows) - len(values),
        "weighted_centroid_of_abs_omega": [cx, cy],
        "second_moment_radius_of_abs_omega": moment,
    }


def compact_band(band):
    keys = (
        "frequency_at_center", "minimum_external_gap", "E3_status", "E4A_status",
        "E4B_status", "Wilson_status", "Omega_over_a2", "Omega_literal_over_a2",
        "qualification_status", "failure_reasons",
    )
    return {key: band[key] for key in keys}


def reduce(raw_path, output_path):
    raw = json.loads(Path(raw_path).read_text(encoding="utf-8-sig"))
    rows = raw["map_rows"]
    if len(rows) != 169 or len({(row["grid_i"], row["grid_j"]) for row in rows}) != 169:
        raise RuntimeError("map grid must contain exactly 169 unique centers")
    if raw["map_grid"]["center"] != [-2.0 / 3.0, 0.0]:
        raise RuntimeError("map center is not public K-prime")
    numerical_map = [
        {
            "grid_i": row["grid_i"], "grid_j": row["grid_j"],
            "public_q": row["public_q"],
            "offset_from_K_prime": row["offset_from_K_prime"],
            "bands": [compact_band(band) for band in row["bands"]],
        }
        for row in rows
    ]
    descriptors = {f"band_{band + 1}": descriptor(rows, band) for band in BANDS}
    center = next(row for row in rows if row["grid_i"] == 0 and row["grid_j"] == 0)
    existing = json.loads((ROOT / "audit/e9c/result.json").read_text(encoding="utf-8-sig"))
    expected = [
        existing["results"]["64"]["PUBLIC_K_PRIME"][str(band)]["primary"]["omega_over_a2_wilson"]
        for band in BANDS
    ]
    actual = [band["Omega_over_a2"] for band in center["bands"]]
    replay = [
        {"paper_band": band + 1, "expected": expected[band], "actual": actual[band], "abs_error": abs(actual[band] - expected[band])}
        for band in BANDS
    ]
    replay_ok = all(item["abs_error"] <= 1e-7 for item in replay)
    trs_rows = []
    max_trs = 0.0
    for row in raw["trs_rows"]:
        band_rows = []
        for band in BANDS:
            k = row["K"][band]["Omega_over_a2"]
            kp = row["K_prime"][band]["Omega_over_a2"]
            if k is None or kp is None:
                band_rows.append({"paper_band": band + 1, "K": k, "K_prime": kp, "abs_residual": None, "relative_residual": None, "status": "NOT_REPORTED"})
            else:
                residual = abs(k + kp)
                relative = residual / max(abs(k), abs(kp), 1e-15)
                max_trs = max(max_trs, relative)
                band_rows.append({"paper_band": band + 1, "K": k, "K_prime": kp, "abs_residual": residual, "relative_residual": relative, "status": "PASSED" if relative <= 0.01 else "FAILED"})
        trs_rows.append({"offset_1_72": row["offset_1_72"], "bands": band_rows})
    trs_ok = all(band["status"] == "PASSED" for row in trs_rows for band in row["bands"])
    map_by_grid = {(row["grid_i"], row["grid_j"]): row for row in rows}
    r96_rows = []
    for row in raw["r96_validation_rows"]:
        grid = (row["offset_1_72"][0] // 2, row["offset_1_72"][1] // 2)
        r64_row = map_by_grid[grid]
        bands = []
        for band in BANDS:
            r64 = r64_row["bands"][band]["Omega_over_a2"]
            r96 = row["bands"][band]["Omega_over_a2"]
            bands.append({
                "paper_band": band + 1, "R64": r64, "R96": r96,
                "abs_resolution_difference": None if r64 is None or r96 is None else abs(r96 - r64),
                "relative_resolution_difference": None if r64 is None or r96 is None else abs(r96 - r64) / max(abs(r64), 1e-15),
            })
        r96_rows.append({"offset_1_72": row["offset_1_72"], "public_q": row["public_q"], "bands": bands})
    shared = []
    dominant = {str(band + 1): 0 for band in BANDS}
    for row in rows:
        vals = [band["Omega_over_a2"] for band in row["bands"]]
        if all(row["bands"][band]["qualification_status"] == "QUALIFIED" and vals[band] is not None for band in BANDS):
            abs_vals = [abs(value) for value in vals]
            winner = max(range(len(abs_vals)), key=lambda index: abs_vals[index])
            dominant[str(winner + 1)] += 1
            shared.append({"grid_i": row["grid_i"], "grid_j": row["grid_j"], "absolute_omega": abs_vals, "dominant_band": winner + 1})
    center_sign = tuple(1 if value > 0 else -1 if value < 0 else 0 for value in actual)
    classifications = {
        "sign_structure": "REPRODUCED" if center_sign == (-1, 1, 1) and trs_ok else "NOT_REPRODUCED",
        "peak_region": "INSUFFICIENT_PAPER_NUMERIC_ANCHOR",
        "relative_band_strength": "REPRODUCED" if center_sign == (-1, 1, 1) else "NOT_REPRODUCED",
        "spatial_concentration_trend": "INSUFFICIENT_PAPER_NUMERIC_ANCHOR",
        "overall_distribution_fidelity": "SUPPORTED" if replay_ok and trs_ok else "NOT_SUPPORTED",
        "paper_comparison_policy": "TREND_FIDELITY_OVER_POINTWISE_NUMERICAL_COINCIDENCE",
        "paper_map_anchor_limitation": "No pixel-level paper raster was used or fitted; peak and width labels remain qualitative.",
    }
    payload = {
        "schema": "trilatt_e9d_local_berry_distribution_result_v1",
        "work_order_id": raw["work_order_id"],
        "base_sandbox_sha": raw["base_sandbox_sha"],
        "expected_main_head": raw["expected_main_head"],
        "calculation_code_git_sha": raw["calculation_code_git_sha"],
        "contract_json_sha256": raw["contract_json_sha256"],
        "raw_result_sha256": sha(raw_path),
        "contract": raw["contract"],
        "self_checks": raw["self_checks"],
        "geometry": raw["geometry"],
        "coordinate_preflight": raw["coordinate_preflight"],
        "map_resolution": raw["map_resolution"],
        "map_grid": raw["map_grid"],
        "numerical_map": numerical_map,
        "distribution_descriptors": descriptors,
        "band_relative_structure": {"shared_qualified_pixel_count": len(shared), "dominant_band_pixel_counts": dominant, "shared_pixels": shared},
        "E9C_KPRIME_PAPER_STENCIL_REPLAY": replay,
        "E9C_KPRIME_PAPER_STENCIL_REPLAY_STATUS": "PASSED" if replay_ok else "FAILED",
        "trs_distribution_control": trs_rows,
        "TRS_DISTRIBUTION_CONTROL": "PASSED" if trs_ok else "FAILED",
        "max_trs_relative_residual": max_trs,
        "r96_validation": r96_rows,
        "r96_validation_center_count": len(r96_rows),
        "classifications": classifications,
        "cache_identity": raw["cache_identity"],
        "telemetry": raw["telemetry"],
        "solver_failures": raw["telemetry"]["solver_failures"],
        "valley_chern": "NOT_AUTHORIZED",
        "full_bz_chern": "NOT_AUTHORIZED",
        "E9D_OVERALL": "DAI_FR0_LOCAL_BERRY_DISTRIBUTION_READY_FOR_SUPERVISOR_AUDIT" if replay_ok and trs_ok else "FAIL_CLOSED",
    }
    Path(output_path).write_text(json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    raw_path = sys.argv[sys.argv.index("--raw") + 1] if "--raw" in sys.argv else str(ROOT / "audit/e9d/raw_result.json")
    output_path = sys.argv[sys.argv.index("--output") + 1] if "--output" in sys.argv else str(ROOT / "audit/e9d/result.json")
    payload = reduce(raw_path, output_path)
    print(json.dumps({"schema": payload["schema"], "E9D_OVERALL": payload["E9D_OVERALL"], "raw_result_sha256": payload["raw_result_sha256"]}, sort_keys=True))

