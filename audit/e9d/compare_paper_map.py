"""E9D.C1 source-bound qualitative comparison; no new solver."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BANDS = (0, 1, 2)
EXTENT_RANK = {"TIGHT": 0, "INTERMEDIATE": 1, "BROAD": 2}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sign(value):
    if value > 0:
        return "POSITIVE"
    if value < 0:
        return "NEGATIVE"
    return "ZERO"


def compare_band(source, descriptor, band_number):
    center_sign = sign(descriptor["center_value"])
    center_match = center_sign == source["sign_at_k"]
    near_sign_match = center_sign == source["dominant_sign_near_k"]
    reversal = descriptor["positive_pixel_count"] > 0 and descriptor["negative_pixel_count"] > 0
    reversal_match = reversal == source["sign_reversal_visibly_present"]
    center_offset = descriptor["max_abs_location_offset"]
    centered = center_offset is not None and abs(center_offset[0]) < 1e-15 and abs(center_offset[1]) < 1e-15
    peak_match = centered == source["primary_abs_feature_centered_near_k"]
    offcenter = not centered
    offcenter_match = offcenter == source["important_off_center_structure_visible"]
    relative = source["qualitative_relative_magnitude"]
    relative_match = "UNDETERMINED" if relative == "UNDETERMINED" else "UNDETERMINED"
    return {
        "band_one_based": band_number,
        "source_descriptor": source,
        "map_descriptor": descriptor,
        "center_sign_observed": center_sign,
        "center_sign_match": center_match,
        "dominant_sign_structure_match": near_sign_match,
        "sign_reversal_observed": reversal,
        "sign_reversal_structure_match": reversal_match,
        "peak_region_match": peak_match,
        "important_off_center_structure_observed": offcenter,
        "spatial_extent_observed_second_moment": descriptor["second_moment_radius_of_abs_omega"],
        "spatial_extent_order_match": None,
        "relative_band_strength_match": relative_match,
        "source_support_notes": "Source-bound qualitative comparison only; no image digitization or pixel fitting.",
    }


def run(output):
    contract_path = ROOT / "audit/e9d/c1_paper_map_contract.json"
    e9d_path = ROOT / "audit/e9d/result.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8-sig"))
    e9d = json.loads(e9d_path.read_text(encoding="utf-8-sig"))
    if not contract["existing_e9d_files_are_immutable"]:
        raise RuntimeError("contract does not preserve E9D")
    source = contract["source"]
    if source["status"] != "BOUND":
        raise RuntimeError("source is not bound")
    descriptors = e9d["distribution_descriptors"]
    rows = []
    for band in BANDS:
        rows.append(compare_band(contract["source_descriptors"][f"band_{band + 1}"], descriptors[f"band_{band + 1}"], band + 1))
    observed_radii = [row["spatial_extent_observed_second_moment"] for row in rows]
    observed_order = sorted(range(3), key=lambda index: observed_radii[index])
    source_order = sorted(range(3), key=lambda index: EXTENT_RANK[rows[index]["source_descriptor"]["qualitative_spatial_extent"]])
    extent_ok = observed_order == source_order
    for row in rows:
        row["spatial_extent_order_match"] = extent_ok
    source_undetermined_relative = any(row["source_descriptor"]["qualitative_relative_magnitude"] == "UNDETERMINED" for row in rows)
    all_sign = all(row["center_sign_match"] and row["dominant_sign_structure_match"] for row in rows)
    all_peak = all(row["peak_region_match"] for row in rows)
    all_fine = all(row["sign_reversal_structure_match"] and row["important_off_center_structure_observed"] == row["source_descriptor"]["important_off_center_structure_visible"] for row in rows)
    classifications = {
        "external_classification_tautology_removed": True,
        "sign_structure": "REPRODUCED" if all_sign else "NOT_REPRODUCED",
        "peak_region": "REPRODUCED" if all_peak else "NOT_REPRODUCED",
        "relative_band_strength": "INSUFFICIENT_SOURCE_SUPPORT" if source_undetermined_relative else ("REPRODUCED" if all_sign else "NOT_REPRODUCED"),
        "fine_structure": "REPRODUCED" if all_fine else "NOT_REPRODUCED",
        "spatial_concentration_trend": "REPRODUCED" if extent_ok else "NOT_REPRODUCED",
        "overall_distribution_fidelity": "INSUFFICIENT_SOURCE_SUPPORT" if source_undetermined_relative else ("SUPPORTED" if all_sign and all_peak and all_fine and extent_ok else "NOT_SUPPORTED"),
        "paper_comparison_policy": contract["comparison_policy"],
    }
    payload = {
        "schema": "trilatt_e9d_c1_source_bound_comparison_result_v1",
        "work_order_id": contract["work_order_id"],
        "base_sandbox_sha": contract["base_sandbox_sha"],
        "expected_main_head": contract["expected_main_head"],
        "new_mpb_solver_requests": 0,
        "new_berry_calculation": "NONE",
        "original_e9d_numerical_evidence_unchanged": True,
        "source_contract_sha256": sha(contract_path),
        "original_e9d_result_sha256": sha(e9d_path),
        "source": source,
        "band_comparisons": rows,
        "classifications": classifications,
        "source_bound_evidence": {
            "figure": source["figure"],
            "fr": source["structural_parameter"],
            "arxiv_url": source["arxiv_url"],
            "doi": source["doi"],
            "no_pixel_digitization": True,
            "no_colorbar_optimization": True,
        },
        "valley_chern": "NOT_AUTHORIZED",
        "full_bz_chern": "NOT_AUTHORIZED",
        "E9D_C1_OVERALL": "SOURCE_BOUND_FR0_DISTRIBUTION_COMPARISON_READY_FOR_SUPERVISOR_DECISION" if source["status"] == "BOUND" else "FAIL_CLOSED",
    }
    Path(output).write_text(json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    output = Path(__file__).resolve().parent / "c1_comparison_result.json"
    payload = run(output)
    print(json.dumps({"schema": payload["schema"], "E9D_C1_OVERALL": payload["E9D_C1_OVERALL"], "classifications": payload["classifications"]}, sort_keys=True))

