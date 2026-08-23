"""E9D.C2 corrected source-bound comparator; no new solver."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BANDS = (0, 1, 2)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sign(value):
    return "POSITIVE" if value > 0 else "NEGATIVE" if value < 0 else "ZERO"


def map_metrics(result, band):
    rows = result["numerical_map"]
    center = next(row for row in rows if row["grid_i"] == 0 and row["grid_j"] == 0)
    values = [(row, row["bands"][band]["Omega_over_a2"]) for row in rows if row["bands"][band]["Omega_over_a2"] is not None]
    center_value = center["bands"][band]["Omega_over_a2"]
    center_sign = sign(center_value)
    dominant = [(row, value) for row, value in values if sign(value) == center_sign]
    opposite = [(row, value) for row, value in values if sign(value) != center_sign]
    dominant_max = max(dominant, key=lambda item: abs(item[1]))
    opposite_max = max(opposite, key=lambda item: abs(item[1])) if opposite else (None, None)
    total_abs = sum(abs(value) for _, value in values)
    offcenter_abs = sum(abs(value) for row, value in values if row["grid_i"] != 0 or row["grid_j"] != 0)
    return {
        "center_value": center_value,
        "center_sign": center_sign,
        "strict_any_pixel_sign_reversal": bool(opposite),
        "opposite_sign_pixel_count": len(opposite),
        "opposite_sign_max_abs": None if opposite_max[1] is None else abs(opposite_max[1]),
        "opposite_sign_max_value": opposite_max[1],
        "opposite_sign_max_location": None if opposite_max[0] is None else opposite_max[0]["offset_from_K_prime"],
        "dominant_sign_max_abs": abs(dominant_max[1]),
        "dominant_sign_max_value": dominant_max[1],
        "dominant_sign_max_location": dominant_max[0]["offset_from_K_prime"],
        "opposite_to_dominant_abs_ratio": 0.0 if opposite_max[1] is None else abs(opposite_max[1]) / max(abs(dominant_max[1]), 1e-15),
        "off_center_abs_weight_fraction": offcenter_abs / max(total_abs, 1e-15),
        "abs_max_centered": dominant_max[0]["grid_i"] == 0 and dominant_max[0]["grid_j"] == 0 if opposite_max[1] is None or abs(dominant_max[1]) >= abs(opposite_max[1]) else False,
        "max_abs_location": (dominant_max[0]["offset_from_K_prime"] if abs(dominant_max[1]) >= (0.0 if opposite_max[1] is None else abs(opposite_max[1])) else opposite_max[0]["offset_from_K_prime"]),
        "positive_pixel_count": sum(value > 0 for _, value in values),
        "negative_pixel_count": sum(value < 0 for _, value in values),
        "reported_pixel_count": len(values),
    }


def run(output):
    contract_path = ROOT / "audit/e9d/c2_paper_map_contract.json"
    result_path = ROOT / "audit/e9d/result.json"
    historical_c1 = ROOT / "audit/e9d/c1_comparison_result.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8-sig"))
    result = json.loads(result_path.read_text(encoding="utf-8-sig"))
    if not all((ROOT / path).exists() for path in ("audit/e9d/raw_result.json", "audit/e9d/result.json", "audit/e9d/c1_comparison_result.json")):
        raise RuntimeError("required historical E9D files are missing")
    metrics = {band: map_metrics(result, band) for band in BANDS}
    source = contract["source"]["text_bound_semantics"]
    comparisons = []
    for band in BANDS:
        number = band + 1
        source_band = source[f"band{number}"]
        observed = metrics[band]
        center_match = observed["center_sign"] == source_band["sign_at_k"]
        dominant_match = observed["center_sign"] == source_band["dominant_near_k"]
        if number == 1:
            primary_match = observed["abs_max_centered"]
            material_reversal = "UNDETERMINED"
            off_center_match = observed["opposite_to_dominant_abs_ratio"] < 0.1
        elif number == 2:
            primary_match = observed["abs_max_centered"]
            material_reversal = observed["opposite_sign_pixel_count"] == 0
            off_center_match = observed["off_center_abs_weight_fraction"] > 0.0
        else:
            primary_match = not observed["abs_max_centered"]
            material_reversal = observed["opposite_to_dominant_abs_ratio"] > 1.0
            off_center_match = material_reversal
        comparisons.append({
            "band_one_based": number,
            "metrics": observed,
            "center_sign_match": center_match,
            "primary_feature_region_match": primary_match,
            "dominant_sign_structure_match": dominant_match,
            "material_sign_reversal_match": material_reversal,
            "spatial_extent_class": source_band.get("spatial_extent"),
            "off_center_structure_match": off_center_match,
        })
    radii = [result["distribution_descriptors"][f"band_{band + 1}"]["second_moment_radius_of_abs_omega"] for band in BANDS]
    extent_match = radii[0] < radii[1] and radii[0] < radii[2]
    for row in comparisons:
        row["spatial_extent_order_match"] = extent_match
    e9c = json.loads((ROOT / "audit/e9c/result.json").read_text(encoding="utf-8-sig"))
    at_k = [abs(e9c["results"]["64"]["PUBLIC_K_PRIME"][str(band)]["primary"]["omega_over_a2_wilson"]) for band in BANDS]
    at_k_strength = at_k[0] > at_k[1] > at_k[2]
    core = all(
        row["center_sign_match"] and row["primary_feature_region_match"]
        and row["dominant_sign_structure_match"] and row["spatial_extent_order_match"]
        and row["off_center_structure_match"]
        and (row["material_sign_reversal_match"] in (True, "UNDETERMINED"))
        for row in comparisons
    )
    fine = all(row["material_sign_reversal_match"] in (True, "UNDETERMINED") for row in comparisons)
    payload = {
        "schema": "trilatt_e9d_c2_corrected_source_bound_comparison_result_v1",
        "work_order_id": contract["work_order_id"],
        "base_sandbox_sha": contract["base_sandbox_sha"],
        "expected_main_head": contract["expected_main_head"],
        "new_mpb_solver_requests": 0,
        "new_berry_calculation": "NONE",
        "original_e9d_numerical_evidence_unchanged": True,
        "c1_preserved_as_historical_comparator_defect": True,
        "source_contract_sha256": sha(contract_path),
        "original_e9d_result_sha256": sha(result_path),
        "historical_c1_result_sha256": sha(historical_c1),
        "source": contract["source"],
        "band_comparisons": comparisons,
        "at_k_relative_strength": {"values_abs_omega_over_a2": at_k, "source_order": "|Omega1|>|Omega2|>|Omega3|", "status": "REPRODUCED" if at_k_strength else "NOT_REPRODUCED"},
        "map_wide_relative_strength": "INSUFFICIENT_SOURCE_SUPPORT",
        "classifications": {
            "band2_source_sign_reversal_corrected": True,
            "any_pixel_sign_reversal_tautology_removed": True,
            "spatial_extent_partial_order_used": True,
            "sign_structure": "REPRODUCED" if all(row["center_sign_match"] and row["dominant_sign_structure_match"] for row in comparisons) else "NOT_REPRODUCED",
            "peak_region": "REPRODUCED" if all(row["primary_feature_region_match"] for row in comparisons) else "NOT_REPRODUCED",
            "fine_structure": "REPRODUCED" if fine else "NOT_REPRODUCED",
            "spatial_concentration_trend": "REPRODUCED" if extent_match else "NOT_REPRODUCED",
            "at_k_relative_band_strength": "REPRODUCED" if at_k_strength else "NOT_REPRODUCED",
            "map_wide_relative_band_strength": "INSUFFICIENT_SOURCE_SUPPORT",
            "overall_distribution_fidelity": "SUPPORTED" if core else "NOT_SUPPORTED",
            "paper_comparison_policy": contract["comparison_policy"],
        },
        "valley_chern": "NOT_AUTHORIZED",
        "full_bz_chern": "NOT_AUTHORIZED",
        "E9D_C2_OVERALL": "CORRECTED_SOURCE_BOUND_FR0_DISTRIBUTION_COMPARISON_READY_FOR_SUPERVISOR_DECISION" if core else "FAIL_CLOSED",
    }
    Path(output).write_text(json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    payload = run(Path(__file__).resolve().parent / "c2_comparison_result.json")
    print(json.dumps({"schema": payload["schema"], "E9D_C2_OVERALL": payload["E9D_C2_OVERALL"], "classifications": payload["classifications"]}, sort_keys=True))

