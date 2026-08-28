"""Solver-free terminal synthesis for the corrected FR04 source branch."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
WORK_ORDER_ID = "MEPHC-E9F-D11-FR04-SOURCE-REPRODUCTION-TERMINAL-SYNTHESIS-20260829-341"
BASE_SANDBOX_SHA = "851dc8858b6282ddd71a2acb3783565b46926b09"
MAIN_SHA = "5a4e9e839eff40f582c2404ff3eadd2bf8b676b5"
RUNTIME_SHA256 = "4ae06ff8c1de0a9c5f8b5ea905adf6f6030ec657b9f52da6dc30568e1baf64e5"

ARTIFACTS = {
    "audit/e9f/d7_fr04_berry_normalization_replay.json": "2ba2eb5c81d256ae420cfa6c71bf9282345f74b4018a81c110e88fab4d96270b",
    "audit/e9f/d7_fr04_three_band_qualification_berry.json": "9a65d593486cc1462029095f3c2e2b9ee294d59aaf1ab762ab88418d02e35882",
    "audit/e9f/d7_fr04_source_grid_reduction.json": "665cc0092e31defe37bf71f38092cfb15b3ca835d5d8dd618722a2e05d863468",
    "audit/e9f/d8_fr04_nonabelian_provenance_replay.json": "fbc6a4e789420e9de8e0e46535857ef32cb20cb9f4fc89c5570e9c09996b7356",
    "audit/e9f/d8_fr04_composite_source_assessment.json": "c3e3a2f301908a39210e8d674e8d6521739535ae9538d9dfb21da53ad853615b",
    "audit/e9f/d9r2_fr04_residual_composite_dataset_reconciliation.json": "b784365c2fc6b1492289ab70ac64fc17b236b33e8b5365c8528fbe4152739cc2",
    "audit/e9f/d10_fr04_composite_method_validation_result.json": "ff0e2aefc81d076b6b418fd4fa28b7a2281cfd71b64ea473692b8801aac94a9b",
    "audit/e9f/d10_fr04_primary_stencil_convergence.json": "9f02ca515efbf9b950b3c9d23109ebb6717fd376f6ac2f9c6c421087691af459",
    "audit/e9f/d10_fr04_refined_stencil_convergence.json": "075f0c30b39bb62d7a4dd96a6586d502fd985cb7cb3829335f31d4b9ed713872",
    "audit/e9f/d10_fr04_structural_threshold_provenance.json": "e07804b801e5bf71e08fb41a6ebe9239b9a85dcf7d155a3bffb4792ffc6bad43",
}

OUT = ROOT / "audit/e9f/d11_fr04_source_reproduction_terminal_assessment.json"


class SynthesisError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise SynthesisError(f"FILE_UNAVAILABLE:{path}") from exc


def read_json(relative: str) -> dict[str, Any]:
    path = ROOT / relative
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SynthesisError(f"JSON_UNAVAILABLE:{relative}") from exc
    if not isinstance(value, dict):
        raise SynthesisError(f"JSON_OBJECT_REQUIRED:{relative}")
    return value


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def git_head() -> str:
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False)
    if result.returncode or len(result.stdout.strip()) != 40:
        raise SynthesisError("CURRENT_SOURCE_COMMIT_UNAVAILABLE")
    return result.stdout.strip()


def verify_bound_artifacts() -> dict[str, dict[str, Any]]:
    loaded: dict[str, dict[str, Any]] = {}
    for relative, expected in ARTIFACTS.items():
        path = ROOT / relative
        actual = sha256_file(path)
        if actual != expected:
            raise SynthesisError(f"BOUND_ARTIFACT_HASH_MISMATCH:{relative}")
        loaded[relative] = read_json(relative)
    return loaded


def exact_failure_cells(primary: dict[str, Any], rank: str) -> list[list[int]]:
    rows = primary.get("summaries", {}).get(rank, {}).get("cell_records")
    if not isinstance(rows, list):
        raise SynthesisError(f"D10_PRIMARY_ROWS_MISSING:{rank}")
    return [row["grid_index"] for row in rows if row.get("all_resolution_criteria_pass") is not True]


def refined_failures(refined: dict[str, Any], rank: str) -> list[dict[str, Any]]:
    rows = refined.get("summaries", {}).get(rank, {}).get("representative_records")
    if not isinstance(rows, list):
        raise SynthesisError(f"D10_REFINED_ROWS_MISSING:{rank}")
    criteria = ("odd_contraction", "even_contraction", "terminal_parity_consistency", "terminal_nonincrease", "terminal_consistency")
    result = []
    for row in rows:
        failed = [name for name in criteria if row.get(name) is not True]
        if failed:
            result.append({"grid_index": row.get("grid_index"), "failed_criteria": failed})
    return result


def synthesis() -> dict[str, Any]:
    files = verify_bound_artifacts()
    d7_norm = files["audit/e9f/d7_fr04_berry_normalization_replay.json"]
    d7_qual = files["audit/e9f/d7_fr04_three_band_qualification_berry.json"]
    d7_reduction = files["audit/e9f/d7_fr04_source_grid_reduction.json"]
    d8 = files["audit/e9f/d8_fr04_composite_source_assessment.json"]
    d10 = files["audit/e9f/d10_fr04_composite_method_validation_result.json"]
    primary = files["audit/e9f/d10_fr04_primary_stencil_convergence.json"]
    refined = files["audit/e9f/d10_fr04_refined_stencil_convergence.json"]
    structural = files["audit/e9f/d10_fr04_structural_threshold_provenance.json"]

    if d7_norm.get("status") != "PASS_EXACT_ACCEPTED_PRODUCTION_REPLAY":
        raise SynthesisError("D7_NORMALIZATION_NOT_EXACT")
    if d7_qual.get("berry_normalization_provenance_status") != "PASS_EXACT_ACCEPTED_PRODUCTION_REPLAY":
        raise SynthesisError("D7_QUALIFICATION_PROVENANCE_NOT_EXACT")
    if d7_qual.get("anchors_used_for_fitting") or d7_qual.get("anchors_used_for_qualification") or d7_qual.get("anchors_used_for_selection"):
        raise SynthesisError("D7_SOURCE_ANCHOR_CONTAMINATION")
    bands = d7_reduction.get("band_summaries", {})
    expected_bands = {
        "0": ("COMPLETE", 641, 0, -0.021172241417018383, 0.008827758582981616),
        "1": ("INCOMPLETE_NOT_REPORTED", 541, 100, None, None),
        "2": ("INCOMPLETE_NOT_REPORTED", 531, 110, None, None),
    }
    for key, (status, qualified, missing, chern, error) in expected_bands.items():
        item = bands.get(key)
        if not isinstance(item, dict) or (item.get("source_grid_status"), item.get("qualified_count"), item.get("not_reported_count"), item.get("source_grid_valley_chern"), item.get("source_anchor_abs_error")) != (status, qualified, missing, chern, error):
            raise SynthesisError(f"D7_BAND_SUMMARY_MISMATCH:{key}")

    if d8.get("pair12_additivity_comparison_count") != 531 or d8.get("first3_source_sum_comparison_status") != "NOT_COMPARABLE_INCOMPLETE":
        raise SynthesisError("D8_SOURCE_ASSESSMENT_MISMATCH")
    d8_reconciliation = d8.get("d7_failure_set_reconciliation", {})
    if (d8_reconciliation.get("band1_band2_failure_intersection_count"), d8_reconciliation.get("band1_only_failure_count"), d8_reconciliation.get("band2_only_failure_count")) != (100, 0, 10):
        raise SynthesisError("D8_FAILURE_SET_RECONCILIATION_MISMATCH")
    if structural.get("status") != "PASS_EXACT_ACCEPTED_IMPLEMENTATION_REPLAY" or structural.get("reciprocal_space_jacobian_used") is not False:
        raise SynthesisError("D10_STRUCTURAL_PROVENANCE_MISMATCH")

    expected_d10 = {
        "dataset_binding_status": "VERIFIED_EXISTING_IMMUTABLE_DATASET",
        "d10_dataset_record_count": 420,
        "rank2_primary_structurally_evaluable_cell_count": 10,
        "rank2_primary_odd_contraction_pass_count": 10,
        "rank2_primary_even_contraction_pass_count": 8,
        "rank2_primary_terminal_parity_pass_count": 10,
        "rank2_primary_all_resolution_criteria_pass_count": 8,
        "rank2_robust_positive_gap_pass_count": 10,
        "rank2_refined_structurally_evaluable_count": 5,
        "rank2_refined_odd_contraction_pass_count": 5,
        "rank2_refined_even_contraction_pass_count": 4,
        "rank2_refined_terminal_parity_pass_count": 5,
        "rank2_cross_stencil_nonincrease_pass_count": 4,
        "rank2_cross_stencil_terminal_consistency_pass_count": 5,
        "rank2_refined_all_criteria_pass_count": 3,
        "rank3_primary_structurally_evaluable_cell_count": 10,
        "rank3_primary_odd_contraction_pass_count": 10,
        "rank3_primary_even_contraction_pass_count": 8,
        "rank3_primary_terminal_parity_pass_count": 10,
        "rank3_primary_all_resolution_criteria_pass_count": 8,
        "rank3_robust_positive_gap_pass_count": 10,
        "rank3_refined_structurally_evaluable_count": 5,
        "rank3_refined_odd_contraction_pass_count": 5,
        "rank3_refined_even_contraction_pass_count": 4,
        "rank3_refined_terminal_parity_pass_count": 5,
        "rank3_cross_stencil_nonincrease_pass_count": 4,
        "rank3_cross_stencil_terminal_consistency_pass_count": 5,
        "rank3_refined_all_criteria_pass_count": 3,
        "rank2_method_support_status": "METHOD_NOT_ESTABLISHED_ON_LOCKED_RESIDUAL_SET",
        "rank3_method_support_status": "METHOD_NOT_ESTABLISHED_ON_LOCKED_RESIDUAL_SET",
        "production_threshold_unchanged": True,
        "production_composite_chern_emitted": False,
        "native_invocation_count": 0,
        "provider_request_count": 0,
        "native_solves": 0,
        "mpb_execution": False,
    }
    if any(d10.get(key) != value for key, value in expected_d10.items()):
        raise SynthesisError("D10_RESULT_SUMMARY_MISMATCH")

    primary_failures = {rank: exact_failure_cells(primary, rank) for rank in ("rank2", "rank3")}
    refined_failure_map = {rank: refined_failures(refined, rank) for rank in ("rank2", "rank3")}
    expected_primary_failures = [[-5, -1], [-5, 1]]
    if primary_failures != {"rank2": expected_primary_failures, "rank3": expected_primary_failures}:
        raise SynthesisError("D10_PRIMARY_FAILURE_CELLS_MISMATCH")
    expected_refined = [{"grid_index": [-35, -15], "failed_criteria": ["terminal_nonincrease"]}, {"grid_index": [-5, -1], "failed_criteria": ["even_contraction"]}]
    if refined_failure_map != {"rank2": expected_refined, "rank3": expected_refined}:
        raise SynthesisError("D10_REFINED_FAILURES_MISMATCH")

    result: dict[str, Any] = {
        "schema": "mephc-e9f-d11-fr04-source-reproduction-terminal-synthesis-v1",
        "work_order_id": WORK_ORDER_ID,
        "base_sandbox_sha": BASE_SANDBOX_SHA,
        "main_sha": MAIN_SHA,
        "science_runtime_sha256": RUNTIME_SHA256,
        "machine_contract_status": "PASS",
        "all_bound_artifact_hashes_verified": True,
        "bound_artifact_hashes": ARTIFACTS,
        "source_model_reproduction_status": "VALIDATED_CORRECTED_SOURCE_MODEL",
        "spectral_reproduction_status": "VALIDATED_AT_ACCEPTED_FR04_REFERENCE",
        "berry_normalization_status": "VALIDATED_EXACT_PRODUCTION_REPLAY",
        "band0_source_chern_reproduction_status": "REPRODUCED_WITH_RECORDED_DIFFERENCE",
        "band0_valley_chern": -0.021172241417018383,
        "band0_source_anchor": -0.03,
        "band0_source_anchor_abs_difference": 0.008827758582981616,
        "band1_source_chern_reproduction_status": "UNRESOLVED_UNDER_VALIDATED_PRODUCTION_POLICY",
        "band1_qualified_count": 541,
        "band1_not_reported_count": 100,
        "band2_source_chern_reproduction_status": "UNRESOLVED_UNDER_VALIDATED_PRODUCTION_POLICY",
        "band2_qualified_count": 531,
        "band2_not_reported_count": 110,
        "d8_common_band1_band2_failure_count": 100,
        "d8_residual_composite_cell_count": 10,
        "rank2_method_support_status": d10["rank2_method_support_status"],
        "rank3_method_support_status": d10["rank3_method_support_status"],
        "rank2_primary_even_failure_cells": primary_failures["rank2"],
        "rank3_primary_even_failure_cells": primary_failures["rank3"],
        "rank2_refined_failed_representatives_and_criteria": refined_failure_map["rank2"],
        "rank3_refined_failed_representatives_and_criteria": refined_failure_map["rank3"],
        "current_0p02_production_policy_action": "RETAIN_UNCHANGED",
        "global_threshold_change_authorized": False,
        "composite_threshold_change_authorized": False,
        "production_composite_chern_authorized": False,
        "additional_fr04_resolution_or_stencil_chase_authorized": False,
        "fr04_source_reproduction_branch_status": "CLOSED_PARTIAL_REPRODUCTION_WITH_METHOD_LIMIT_EXPLICIT",
        "native_invocation_count": 0,
        "provider_request_count": 0,
        "native_solves": 0,
        "mpb_execution": False,
        "pipeline_health": "HEALTHY",
        "blocked_by_infrastructure": False,
        "scientific_work_must_stop": False,
        "next_scientific_state": "E9F_FR04_SOURCE_REPRODUCTION_TERMINAL_ASSESSMENT_COMPLETE_READY_FOR_NEXT_PROJECT_PHASE",
        "return_to_supervisor": True,
        "terminal": "E9F_D11_FR04_SOURCE_REPRODUCTION_TERMINAL_SYNTHESIS_COMPLETE",
    }
    atomic_json(OUT, result)
    return result


def main() -> int:
    try:
        result = synthesis()
        print("MEPHC_NATIVE_RESULT_JSON=" + json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
        return 0
    except Exception as exc:
        failure = {"schema": "mephc-e9f-d11-fr04-source-reproduction-terminal-synthesis-v1", "work_order_id": WORK_ORDER_ID, "state": "failed", "error_code": type(exc).__name__, "detail": str(exc)[:512], "native_invocation_count": 0, "provider_request_count": 0, "solver_executions": 0, "native_solves": 0, "mpb_execution": False, "terminal": "E9F_D11_FR04_SOURCE_REPRODUCTION_TERMINAL_SYNTHESIS_FAIL_CLOSED"}
        print("MEPHC_NATIVE_RESULT_JSON=" + json.dumps(failure, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
