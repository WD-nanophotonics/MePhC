"""Reduce E7I.5A rank-1 Stage-1 checkpoints without new solver calls."""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import math
from pathlib import Path

from audit.e7i5a.run_rank1_stage1_orchestrator import (
    EXPECTED_ELEMENTS,
    TARGET_BANDS,
    WORK_ORDER,
    prepare,
    result_invariants,
)

EXPECTED_RUNNER_SHA = "194311f3cb2472b457785a2f97f6d96d5042e987"
SEALED_COMPOSITE_STAGE1_CHERN = 0.00039168033110070674
PAPER_STYLE_REFERENCE = {"band_0": -0.10, "band_1": 0.54, "band_2": -0.43}


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def finite_number(value) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value))


def close_list(left, right, tolerance: float = 1e-14) -> bool:
    return len(left) == len(right) and all(math.isclose(float(a), float(b), rel_tol=0.0, abs_tol=tolerance) for a, b in zip(left, right))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def reduce_stage1(root: Path, checkpoint_dir: Path, result_path: Path, manifest_path: Path) -> dict:
    _, _, _, sample = prepare(root)
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
    by_band = {
        str(band): {
            "checkpoint_count": 0,
            "qualified_count": 0,
            "qualified_weight": 0.0,
            "total_weight": 0.0,
            "weighted_omega_sum": 0.0,
            "status_counts": collections.Counter(),
            "attempt_count": 0,
            "qualified_attempt_count": 0,
            "low_gap_profile_count": 0,
            "center_profile_failed_count": 0,
            "raw_full_gram_max_off_diagonal": 0.0,
            "target_normalization_error_max": 0.0,
            "omega_sign_counts": collections.Counter(),
        }
        for band in TARGET_BANDS
    }
    seen = set()

    for path in files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        require(payload.get("schema") == "e7i5a_rank1_element_checkpoint_v1", f"{path.name}: schema mismatch")
        require(payload.get("complete") is True, f"{path.name}: incomplete checkpoint")
        require(payload.get("runner_code_git_sha") == EXPECTED_RUNNER_SHA, f"{path.name}: runner SHA mismatch")
        element_id = payload.get("element_id")
        require(element_id in expected, f"{path.name}: unexpected element {element_id!r}")
        require(element_id not in seen, f"duplicate element {element_id!r}")
        seen.add(element_id)
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
            require((omega is None) == (not qualified), f"{path.name} band {band}: qualified/omega mismatch")
            stats = by_band[band_key]
            stats["checkpoint_count"] += 1
            stats["total_weight"] += float(payload["integration_weight"])
            stats["status_counts"][final.get("path_status", "MISSING")] += 1
            stats["attempt_count"] += len(band_payload.get("attempts", []))
            stats["qualified_attempt_count"] += sum(1 for attempt in band_payload.get("attempts", []) if attempt.get("qualified") is True)
            if qualified:
                stats["qualified_count"] += 1
                stats["qualified_weight"] += float(payload["integration_weight"])
                stats["weighted_omega_sum"] += float(payload["integration_weight"]) * float(omega)
                stats["omega_sign_counts"]["positive" if omega > 0 else "negative" if omega < 0 else "zero"] += 1
            if final.get("center_profile_passed") is False:
                stats["center_profile_failed_count"] += 1
            for profile_row in final.get("profile", []):
                if profile_row.get("R64_nearest_gap") is not None:
                    stats["low_gap_profile_count"] += 1
                raw = profile_row.get("raw", {})
                stats["raw_full_gram_max_off_diagonal"] = max(stats["raw_full_gram_max_off_diagonal"], float(raw.get("raw_full_gram_max_off_diagonal", 0.0)))
                stats["target_normalization_error_max"] = max(stats["target_normalization_error_max"], float(raw.get("target_normalization_error", 0.0)))
            element_row["bands"][band_key] = {
                "qualified": qualified,
                "omega_trace_q": omega,
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
            "attempt_count": stats["attempt_count"],
            "qualified_attempt_count": stats["qualified_attempt_count"],
            "low_gap_profile_count": stats["low_gap_profile_count"],
            "center_profile_failed_count": stats["center_profile_failed_count"],
            "raw_full_gram_max_off_diagonal": stats["raw_full_gram_max_off_diagonal"],
            "target_normalization_error_max": stats["target_normalization_error_max"],
            "omega_sign_counts": dict(stats["omega_sign_counts"]),
            "paper_style_reference": PAPER_STYLE_REFERENCE[f"band_{band}"],
        }

    result = {
        "schema": "e7i5a_rank1_stage1_reduction_v1",
        "work_order": WORK_ORDER,
        "calculation_runner_code_git_sha": EXPECTED_RUNNER_SHA,
        "reducer_git_head": None,
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
    result_path.write_text(json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    manifest = {
        "schema": "e7i5a_rank1_stage1_reduction_manifest_v1",
        "work_order": WORK_ORDER,
        "calculation_runner_code_git_sha": EXPECTED_RUNNER_SHA,
        "checkpoint_count": len(files),
        "total_integration_weight": total_weight,
        "elements": sorted(rows, key=lambda row: row["element_id"]),
    }
    manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
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