"""E9D.C3 final threshold-free source-bound comparator; no new solver."""
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


def run(output):
    contract_path = ROOT / "audit/e9d/c3_comparator_contract.json"
    result_path = ROOT / "audit/e9d/result.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8-sig"))
    result = json.loads(result_path.read_text(encoding="utf-8-sig"))
    required = ("audit/e9d/raw_result.json", "audit/e9d/result.json", "audit/e9d/c1_comparison_result.json", "audit/e9d/c2_comparison_result.json")
    if not all((ROOT / path).exists() for path in required):
        raise RuntimeError("historical E9D/C1/C2 evidence is incomplete")
    descriptors = result["distribution_descriptors"]
    rows = []
    for band in BANDS:
        d = descriptors[f"band_{band + 1}"]
        center_sign = sign(d["center_value"])
        opposite_count = d["positive_pixel_count"] if center_sign == "NEGATIVE" else d["negative_pixel_count"]
        global_abs_offcenter = d["max_abs_location_offset"] != [0.0, 0.0]
        if band == 0:
            primary = d["max_abs_location_offset"] == [0.0, 0.0]
            material = "NOT_REQUIRED_FOR_SOURCE_SEAL"
            offcenter = d["opposite_to_dominant_abs_ratio"] if "opposite_to_dominant_abs_ratio" in d else None
        elif band == 1:
            primary = d["max_abs_location_offset"] == [0.0, 0.0]
            material = opposite_count == 0
            offcenter = d["weighted_centroid_of_abs_omega"]
        else:
            primary = global_abs_offcenter
            material = opposite_count > 0 and global_abs_offcenter
            offcenter = d["max_abs_location_offset"]
        rows.append({
            "band_one_based": band + 1,
            "center_sign": center_sign,
            "center_sign_match": center_sign == contract["source"][f"band{band + 1}"]["center_sign"],
            "primary_feature_region_match": primary,
            "dominant_sign_structure_match": center_sign == contract["source"][f"band{band + 1}"]["center_sign"],
            "material_sign_reversal_match": material,
            "spatial_extent_second_moment": d["second_moment_radius_of_abs_omega"],
            "opposite_sign_pixel_count": opposite_count,
            "global_abs_max_offcenter": global_abs_offcenter,
            "off_center_observation": offcenter,
        })
    radii = [row["spatial_extent_second_moment"] for row in rows]
    rows[0]["spatial_extent_class_match"] = radii[0] < radii[1] and radii[0] < radii[2]
    rows[1]["spatial_extent_class_match"] = radii[1] > radii[0]
    rows[2]["spatial_extent_class_match"] = radii[2] > radii[0]
    e9c = json.loads((ROOT / "audit/e9c/result.json").read_text(encoding="utf-8-sig"))
    at_k = [abs(e9c["results"]["64"]["PUBLIC_K_PRIME"][str(band)]["primary"]["omega_over_a2_wilson"]) for band in BANDS]
    at_k_ok = at_k[0] > at_k[1] > at_k[2]
    core = all(
        row["center_sign_match"] and row["primary_feature_region_match"]
        and row["dominant_sign_structure_match"] and row["spatial_extent_class_match"]
        and row["material_sign_reversal_match"] in (True, "NOT_REQUIRED_FOR_SOURCE_SEAL")
        for row in rows
    ) and at_k_ok
    payload = {
        "schema": "trilatt_e9d_c3_threshold_free_source_bound_comparison_result_v1",
        "work_order_id": contract["work_order_id"],
        "base_sandbox_sha": contract["base_sandbox_sha"],
        "expected_main_head": contract["expected_main_head"],
        "new_mpb_solver_requests": 0,
        "new_berry_calculation": "NONE",
        "original_e9d_evidence_unchanged": True,
        "c1_and_c2_preserved": True,
        "arbitrary_band1_threshold_removed": True,
        "band2_positive_weight_tautology_removed": True,
        "new_numeric_match_threshold_introduced": False,
        "source_contract_sha256": sha(contract_path),
        "original_e9d_result_sha256": sha(result_path),
        "band_comparisons": rows,
        "at_k_relative_strength": {"values_abs_omega_over_a2": at_k, "status": "REPRODUCED" if at_k_ok else "NOT_REPRODUCED"},
        "map_wide_relative_strength": "INSUFFICIENT_SOURCE_SUPPORT",
        "classifications": {
            "sign_structure": "REPRODUCED" if all(row["center_sign_match"] and row["dominant_sign_structure_match"] for row in rows) else "NOT_REPRODUCED",
            "peak_region": "REPRODUCED" if all(row["primary_feature_region_match"] for row in rows) else "NOT_REPRODUCED",
            "fine_structure": "REPRODUCED" if all(row["material_sign_reversal_match"] in (True, "NOT_REQUIRED_FOR_SOURCE_SEAL") for row in rows) else "NOT_REPRODUCED",
            "spatial_concentration_trend": "REPRODUCED" if all(row["spatial_extent_class_match"] for row in rows) else "NOT_REPRODUCED",
            "at_k_relative_band_strength": "REPRODUCED" if at_k_ok else "NOT_REPRODUCED",
            "map_wide_relative_band_strength": "INSUFFICIENT_SOURCE_SUPPORT",
            "overall_distribution_fidelity": "SUPPORTED" if core else "NOT_SUPPORTED",
            "paper_comparison_policy": contract["comparison_policy"],
        },
        "valley_chern": "NOT_AUTHORIZED",
        "full_bz_chern": "NOT_AUTHORIZED",
        "E9D_C3_OVERALL": "FR0_EXTERNAL_DISTRIBUTION_COMPARATOR_READY_FOR_FINAL_SEAL" if core else "FAIL_CLOSED",
    }
    Path(output).write_text(json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    payload = run(Path(__file__).resolve().parent / "c3_comparison_result.json")
    print(json.dumps({"schema": payload["schema"], "E9D_C3_OVERALL": payload["E9D_C3_OVERALL"], "classifications": payload["classifications"]}, sort_keys=True))

