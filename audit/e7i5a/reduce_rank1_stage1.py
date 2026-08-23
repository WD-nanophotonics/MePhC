"""Reduce E7I.5A.C1 rank-1 checkpoints without new solver calls."""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import math
import subprocess
from pathlib import Path

from shapely.geometry import Point

from audit.e7i5a.run_rank1_stage1_orchestrator import (
    CHECKPOINT_SCHEMA_VERSION,
    EXPECTED_ELEMENTS,
    SPACING,
    TARGET_BANDS,
    WORK_ORDER,
    prepare,
    result_invariants,
)

SEALED_COMPOSITE_STAGE1_CHERN = 0.00039168033110070674
PAPER_STYLE_REFERENCE = {"0": -0.10, "1": 0.54, "2": -0.43}


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_head(root: Path) -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()


def finite_number(value) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value))


def close_list(left, right, tolerance: float = 1e-14) -> bool:
    return len(left) == len(right) and all(
        math.isclose(float(a), float(b), rel_tol=0.0, abs_tol=tolerance)
        for a, b in zip(left, right)
    )


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def spatial_category(q, domain) -> str:
    point = Point(float(q[0]), float(q[1]))
    boundary_distance = domain.polygon.boundary.distance(point)
    radius = math.hypot(float(q[0]), float(q[1]))
    if boundary_distance <= 2.0 * SPACING:
        return "GAMMA_EXCLUSION_BOUNDARY" if radius <= 0.16 else "OUTER_BOUNDARY"
    if sum((float(q[j]) - (2.0 / 3.0, 0.0)[j]) ** 2 for j in range(2)) <= 0.20 ** 2:
        return "K_REGION"
    return "INTERIOR"


def failure_class(final: dict) -> str | None:
    if final.get("qualified") is True:
        return None
    if final.get("center_profile_passed") is False:
        return "CENTER_ISOLATION_PROFILE_FAILURE"
    profile = final.get("profile", [])
    if any(row.get("profile") == "LOW_GAP_FAIL" for row in profile):
        return "PRIMARY_LEVEL_ISOLATION_PROFILE_FAILURE"
    if final.get("reference_profile_passed") is False:
        return "REFERENCE_LEVEL_ISOLATION_PROFILE_FAILURE"
    if final.get("path_status") not in {"PATH_SINGLE_BAND_QUALIFIED", "PATH_SUBSPACE_QUALIFIED"}:
        return "PATH_CONTINUITY_FAILURE"
    if final.get("boundary_status") != "PLAQUETTE_BOUNDARY_SINGLE_BAND_QUALIFIED":
        return "BOUNDARY_QUALIFICATION_FAILURE"
    if final.get("interior_status") != "PLAQUETTE_INTERIOR_SINGLE_BAND_QUALIFIED":
        return "INTERIOR_SPOKE_FAILURE"
    refinement = final.get("refinement")
    if refinement is not None and refinement.get("status") != "PLAQUETTE_REFINEMENT_SINGLE_BAND_QUALIFIED":
        return "REFINEMENT_FAILURE"
    if final.get("wilson_status") != "WILSON_LOOP_QUALIFIED":
        return "WILSON_FAILURE"
    if final.get("determinant_phase") is not None and not finite_number(final.get("determinant_phase")):
        return "PHASE_OR_NONFINITE_FAILURE"
    attempts = final.get("attempts", [])
    if attempts and all(not attempt.get("qualified") for attempt in attempts):
        return "LOCAL_DELTA_LADDER_EXHAUSTED"
    return "UNEXPECTED_FAILURE"


def reduce_stage1(root: Path, checkpoint_dir: Path, result_path: Path, manifest_path: Path) -> dict:
    _, _, domain, sample = prepare(root)
    expected = {
        sample.element_ids[index]: {
            "evaluation_q": [float(x) for x in sample.centers[index]],
            "integration_weight": float(sample.weights[index]),
        }
        for index in range(len(sample.centers))
    }
    files = sorted(checkpoint_dir.glob("*.json"))
    require(len(files) == EXPECTED_ELEMENTS, f"expected {EXPECTED_ELEMENTS} checkpoints, found {len(files)}")
    rows = []
    seen = set()
    bundle_values = set()
    worker_values = set()
    scientific_values = set()
    by_band = {
        str(band): {
            "checkpoint_count": 0,
            "qualified_count": 0,
            "qualified_weight": 0.0,
            "total_weight": 0.0,
            "weighted_omega_sum": 0.0,
            "status_counts": collections.Counter(),
            "failure_class_counts": collections.Counter(),
            "failure_weight_by_class": collections.Counter(),
            "spatial_counts": collections.Counter(),
            "spatial_weight_by_class": collections.Counter(),
            "first_blocking_element_ids": [],
            "center_nearest_gaps": [],
            "profile_passed_nearest_gaps": [],
            "gap_stability_ratios": [],
            "low_gap_profile_count": 0,
            "center_profile_failed_count": 0,
            "raw_full_gram_max_off_diagonal": 0.0,
            "target_normalization_error_max": 0.0,
            "omega_sign_counts": collections.Counter(),
        }
        for band in TARGET_BANDS
    }

    for path in files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        require(payload.get("schema") == CHECKPOINT_SCHEMA_VERSION, f"{path.name}: schema mismatch")
        require(payload.get("complete") is True, f"{path.name}: incomplete checkpoint")
        for field, target in (
            ("checkpoint_schema_version", CHECKPOINT_SCHEMA_VERSION),
            ("calculation_bundle_sha256", payload.get("calculation_bundle_sha256")),
        ):
            require(payload.get(field) == target, f"{path.name}: {field} mismatch")
        element_id = payload.get("element_id")
        require(element_id in expected, f"{path.name}: unexpected element {element_id!r}")
        require(element_id not in seen, f"duplicate element {element_id!r}")
        seen.add(element_id)
        bundle_values.add(payload.get("calculation_bundle_sha256"))
        worker_values.add(payload.get("worker_source_sha256"))
        scientific_values.add(payload.get("scientific_contract_sha256"))
        contract = expected[element_id]
        require(close_list(payload.get("evaluation_q", []), contract["evaluation_q"]), f"{path.name}: evaluation_q mismatch")
        require(math.isclose(float(payload.get("integration_weight")), contract["integration_weight"], rel_tol=0.0, abs_tol=1e-14), f"{path.name}: weight mismatch")
        bands = payload.get("bands")
        require(isinstance(bands, dict) and set(bands) == {str(band) for band in TARGET_BANDS}, f"{path.name}: band set mismatch")
        element_row = {
            "element_id": element_id,
            "evaluation_q": payload["evaluation_q"],
            "integration_weight": payload["integration_weight"],
            "checkpoint_sha256": file_sha256(path),
            "bands": {},
        }
        for band in TARGET_BANDS:
            band_key = str(band)
            band_payload = bands[band_key]
            final = band_payload.get("final", {})
            require(result_invariants(final), f"{path.name} band {band}: result invariant failure")
            qualified = final["qualified"]
            omega = final["omega_trace_q"]
            stats = by_band[band_key]
            stats["checkpoint_count"] += 1
            stats["total_weight"] += float(payload["integration_weight"])
            stats["status_counts"][final.get("path_status", "MISSING")] += 1
            if qualified:
                stats["qualified_count"] += 1
                stats["qualified_weight"] += float(payload["integration_weight"])
                stats["weighted_omega_sum"] += float(payload["integration_weight"]) * float(omega)
                stats["omega_sign_counts"]["positive" if omega > 0 else "negative" if omega < 0 else "zero"] += 1
            else:
                cause = failure_class(final)
                category = spatial_category(payload["evaluation_q"], domain)
                stats["failure_class_counts"][cause] += 1
                stats["failure_weight_by_class"][cause] += float(payload["integration_weight"])
                stats["spatial_counts"][category] += 1
                stats["spatial_weight_by_class"][category] += float(payload["integration_weight"])
                if len(stats["first_blocking_element_ids"]) < 10:
                    stats["first_blocking_element_ids"].append(element_id)
            if final.get("center_profile_passed") is False:
                stats["center_profile_failed_count"] += 1
            for profile_row in final.get("profile", []):
                gap = profile_row.get("R48_nearest_gap")
                if profile_row.get("label") == "center" and finite_number(gap):
                    stats["center_nearest_gaps"].append(float(gap))
                if profile_row.get("profile") in {"LEGACY_STRICT_PASS", "LOW_GAP_PASS"} and finite_number(gap):
                    stats["profile_passed_nearest_gaps"].append(float(gap))
                ratio = profile_row.get("stability_ratio")
                if finite_number(ratio):
                    stats["gap_stability_ratios"].append(float(ratio))
                if profile_row.get("R64_nearest_gap") is not None:
                    stats["low_gap_profile_count"] += 1
                raw = profile_row.get("raw", {})
                stats["raw_full_gram_max_off_diagonal"] = max(stats["raw_full_gram_max_off_diagonal"], float(raw.get("raw_full_gram_max_off_diagonal", 0.0)))
                stats["target_normalization_error_max"] = max(stats["target_normalization_error_max"], float(raw.get("target_normalization_error", 0.0)))
            element_row["bands"][band_key] = {
                "qualified": qualified,
                "omega_trace_q": omega,
                "failure_class": failure_class(final),
                "spatial_category": None if qualified else spatial_category(payload["evaluation_q"], domain),
                "local_delta_k": final.get("local_delta_k"),
                "reference_delta_k": final.get("reference_delta_k"),
                "profile_passed": final.get("profile_passed"),
                "center_profile_passed": final.get("center_profile_passed"),
                "reference_profile_passed": final.get("reference_profile_passed"),
                "path_status": final.get("path_status"),
                "boundary_status": final.get("boundary_status"),
                "interior_status": final.get("interior_status"),
                "wilson_status": final.get("wilson_status"),
                "refinement_status": None if final.get("refinement") is None else final["refinement"].get("status"),
                "attempts": band_payload.get("attempts", []),
            }
        rows.append(element_row)

    require(len(seen) == EXPECTED_ELEMENTS, f"unique elements {len(seen)} != {EXPECTED_ELEMENTS}")
    require(len(bundle_values) == 1, f"multiple calculation bundles: {bundle_values}")
    require(len(worker_values) == 1, f"multiple worker source hashes: {worker_values}")
    require(len(scientific_values) == 1, f"multiple scientific contracts: {scientific_values}")
    total_weight = sum(float(row["integration_weight"]) for row in rows)
    result_bands = {}
    for band in TARGET_BANDS:
        key = str(band)
        stats = by_band[key]
        fraction = stats["qualified_weight"] / stats["total_weight"] if stats["total_weight"] else 0.0
        full_coverage = stats["qualified_count"] == EXPECTED_ELEMENTS and math.isclose(fraction, 1.0, rel_tol=0.0, abs_tol=1e-12)
        chern = stats["weighted_omega_sum"] / (2.0 * math.pi) if full_coverage else None
        result_bands[key] = {
            "checkpoint_count": stats["checkpoint_count"],
            "qualified_count": stats["qualified_count"],
            "qualified_weight": stats["qualified_weight"],
            "total_weight": stats["total_weight"],
            "qualified_weight_fraction": fraction,
            "full_coverage_qualified": full_coverage,
            "weighted_omega_sum_partial_or_full": stats["weighted_omega_sum"],
            "chern": chern,
            "chern_status": "FULL_COVERAGE_QUALIFIED" if full_coverage else "NOT_REPORTED_PARTIAL_COVERAGE",
            "status_counts": dict(stats["status_counts"]),
            "failure_class_counts": dict(stats["failure_class_counts"]),
            "failure_weight_by_class": dict(stats["failure_weight_by_class"]),
            "spatial_counts": dict(stats["spatial_counts"]),
            "spatial_weight_by_class": dict(stats["spatial_weight_by_class"]),
            "first_blocking_element_ids": stats["first_blocking_element_ids"],
            "min_center_nearest_gap": min(stats["center_nearest_gaps"]) if stats["center_nearest_gaps"] else None,
            "min_profile_passed_nearest_gap": min(stats["profile_passed_nearest_gaps"]) if stats["profile_passed_nearest_gaps"] else None,
            "min_gap_stability_ratio": min(stats["gap_stability_ratios"]) if stats["gap_stability_ratios"] else None,
            "low_gap_profile_count": stats["low_gap_profile_count"],
            "center_profile_failed_count": stats["center_profile_failed_count"],
            "raw_full_gram_max_off_diagonal": stats["raw_full_gram_max_off_diagonal"],
            "target_normalization_error_max": stats["target_normalization_error_max"],
            "omega_sign_counts": dict(stats["omega_sign_counts"]),
            "paper_style_reference": PAPER_STYLE_REFERENCE[key],
        }

    result = {
        "schema": "e7i5a_c1_rank1_stage1_reduction_v1",
        "work_order": WORK_ORDER,
        "checkpoint_schema_version": CHECKPOINT_SCHEMA_VERSION,
        "worker_source_sha256": next(iter(worker_values)),
        "scientific_contract_sha256": next(iter(scientific_values)),
        "calculation_bundle_sha256": next(iter(bundle_values)),
        "worker_code_git_sha": payload.get("worker_code_git_sha"),
        "reducer_git_head": git_head(root),
        "expected_elements": EXPECTED_ELEMENTS,
        "checkpoint_count": len(files),
        "unique_element_count": len(seen),
        "checkpoint_identity_status": "PASSED",
        "calculation_status": "CHECKPOINTS_COMPLETE",
        "per_band": result_bands,
        "sealed_composite_stage1_chern": SEALED_COMPOSITE_STAGE1_CHERN,
        "sealed_composite_comparison_status": "NOT_COMPARABLE_UNTIL_FULL_SINGLE_BAND_COVERAGE",
        "main_unchanged_required": True,
    }
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + chr(10), encoding="utf-8")
    manifest = {
        "schema": "e7i5a_c1_rank1_stage1_reduction_manifest_v1",
        "work_order": WORK_ORDER,
        "checkpoint_schema_version": CHECKPOINT_SCHEMA_VERSION,
        "worker_source_sha256": next(iter(worker_values)),
        "scientific_contract_sha256": next(iter(scientific_values)),
        "calculation_bundle_sha256": next(iter(bundle_values)),
        "checkpoint_count": len(files),
        "total_integration_weight": total_weight,
        "elements": sorted(rows, key=lambda row: row["element_id"]),
    }
    manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2, allow_nan=False) + chr(10), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint-dir", required=True, type=Path)
    parser.add_argument("--result", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    result = reduce_stage1(root, args.checkpoint_dir, args.result, args.manifest)
    print(json.dumps({
        "status": "REDUCTION_COMPLETE",
        "checkpoint_count": result["checkpoint_count"],
        "bands": {
            band: {
                "qualified_count": data["qualified_count"],
                "qualified_weight_fraction": data["qualified_weight_fraction"],
                "chern_status": data["chern_status"],
            }
            for band, data in result["per_band"].items()
        },
    }, sort_keys=True))


if __name__ == "__main__":
    main()