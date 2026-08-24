"""Fail-closed semantic validator for the E9F.C1.RP1 preregistration."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

POLICY_SCHEMA = "trilatt_e9f_c1_rp1_recovery_policy_v1"
FINITE = "FINITE_STENCIL_QUALIFICATION_ARTIFACT_SUPPORTED"
LOW_GAP = "TRUE_POINTWISE_LOW_GAP_BLOCKER"
OUTER = "OUTER_BOUNDARY_CROSSING_STENCIL"
NEIGHBOR = "LOW_GAP_NEIGHBORHOOD_STENCIL_WITHOUT_DOMAIN_CROSSING"
F1 = "F1_UNIFORM_BAND2_SOURCE_GRID_FINE_STENCIL"
F2 = "F2_PREDECLARED_MIXED_STENCIL_ESTIMATOR"
FIXED_RESOLUTIONS = [64, 96]
FIXED_STENCILS = ["1/72", "1/144"]


class RP1ContractError(ValueError):
    pass


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_records(source: Mapping[str, Any]) -> list[dict[str, Any]]:
    records = []
    for diagnostic in source.get("diagnostics", []):
        if diagnostic.get("classification") not in {FINITE, LOW_GAP}:
            continue
        records.append({
            "sample_id": diagnostic.get("sample_id"),
            "sample_index": diagnostic.get("sample_index"),
            "center": diagnostic.get("center"),
            "classification": diagnostic.get("classification"),
            "classification_subtype": diagnostic.get("classification_subtype"),
            "center_gap": diagnostic.get("existing_numerical", {}).get("center_gap"),
        })
    return records


def _require_false(authorizations: Mapping[str, Any], fields: Iterable[str]) -> None:
    for field in fields:
        if authorizations.get(field) is not False:
            raise RP1ContractError(f"EXECUTION_FIREWALL_MUTATED:{field}")


def validate_policy_contract(contract: Mapping[str, Any], root: Path) -> None:
    if contract.get("schema") != POLICY_SCHEMA:
        raise RP1ContractError("POLICY_SCHEMA_MISMATCH")
    immutable = contract.get("immutable_inputs")
    if not isinstance(immutable, dict):
        raise RP1ContractError("IMMUTABLE_INPUTS_MISSING")
    source_path = root / immutable["source_artifact"]
    if not source_path.is_file() or _sha256(source_path) != immutable["source_artifact_sha256"]:
        raise RP1ContractError("IMMUTABLE_SOURCE_HASH_MISMATCH")
    source = json.loads(source_path.read_text(encoding="utf-8"))
    if source.get("corrected_numerical_payload_sha256") != immutable["numerical_payload_digest"]:
        raise RP1ContractError("NUMERICAL_PAYLOAD_DIGEST_MISMATCH")
    if immutable.get("failed_sample_records") != _source_records(source):
        raise RP1ContractError("IMMUTABLE_FAILED_SAMPLE_RECORDS_MISMATCH")
    if immutable.get("total_source_grid_samples") != 551 or immutable.get("qualified_at_c1") != 534 or immutable.get("failed_at_c1") != 17:
        raise RP1ContractError("IMMUTABLE_SOURCE_COUNTS_MISMATCH")
    if immutable.get("classification_counts") != {FINITE: 11, LOW_GAP: 6}:
        raise RP1ContractError("CLASSIFICATION_COUNT_MISMATCH")
    if immutable.get("classification_subtype_counts") != {OUTER: 8, NEIGHBOR: 3}:
        raise RP1ContractError("CLASSIFICATION_SUBTYPE_COUNT_MISMATCH")

    finite = contract.get("finite_stencil_policy", {})
    if finite.get("selected_future_policy") != F1:
        raise RP1ContractError("F1_NOT_SELECTED")
    alternatives = {item.get("policy_id"): item for item in finite.get("alternatives", [])}
    if set(alternatives) != {F1, F2}:
        raise RP1ContractError("FINITE_POLICY_ALTERNATIVES_INCOMPLETE")
    selected = alternatives[F1]
    if selected.get("selected") is not True or selected.get("stencil") != "1/144":
        raise RP1ContractError("F1_STENCIL_MUTATED")
    if selected.get("estimator_scope") != "all_551_band2_source_grid_samples":
        raise RP1ContractError("F1_SCOPE_MUTATED")
    if finite.get("no_silent_mixing_of_11_fine_with_540_coarse") is not True:
        raise RP1ContractError("F1_SILENT_MIXING_ALLOWED")
    if alternatives[F2].get("selected") is not False:
        raise RP1ContractError("F2_SELECTED")

    records = immutable["failed_sample_records"]
    low_gap_ids = [item["sample_id"] for item in records if item["classification"] == LOW_GAP]
    matrix = contract.get("rp2_diagnostic_matrix", {})
    if matrix.get("fixed_sample_ids") != low_gap_ids:
        raise RP1ContractError("RP2_SAMPLE_SET_MUTATED")
    if matrix.get("fixed_resolutions") != FIXED_RESOLUTIONS:
        raise RP1ContractError("RP2_RESOLUTION_MATRIX_MUTATED")
    if matrix.get("fixed_plaquette_stencils") != FIXED_STENCILS:
        raise RP1ContractError("RP2_STENCIL_MATRIX_MUTATED")
    if matrix.get("optional_escalation_present") is not False:
        raise RP1ContractError("RP2_OPTIONAL_ESCALATION_PRESENT")
    ladder = contract.get("low_gap_policy", {}).get("diagnostic_ladder", [])
    if [item.get("level") for item in ladder] != ["L0", "L1", "L2", "L3"]:
        raise RP1ContractError("LOW_GAP_LADDER_INCOMPLETE")
    if ladder[0].get("resolutions") != FIXED_RESOLUTIONS or "optional_higher_resolution" in ladder[0]:
        raise RP1ContractError("L0_MATRIX_NOT_FROZEN")
    if ladder[1].get("stencils") != FIXED_STENCILS or "optional_stencil" in ladder[1]:
        raise RP1ContractError("L1_MATRIX_NOT_FROZEN")

    l0_fields = contract.get("l0_exact_output_contract", {}).get("fields", [])
    required_l0 = {"ordered_frequencies_bands_1_2_3_4", "gap_12", "internal_gap_23", "upper_external_gap_34", "internal_gap_sign", "band_ordering", "r64_r96_absolute_gap_difference"}
    if set(l0_fields) != required_l0:
        raise RP1ContractError("L0_OUTPUT_CONTRACT_INCOMPLETE")
    l1 = contract.get("l1_exact_shadow_contract", {})
    if l1.get("bands_zero_based") != [2, 3] or l1.get("principal_branch") != "(-pi, pi]" or l1.get("diagnostic_only") is not True or l1.get("reducer_admissible") is not False:
        raise RP1ContractError("L1_SHADOW_CONTRACT_INVALID")
    if l1.get("area_normalized_estimator") != "OMEGA_RANK1_SHADOW=PHI_RANK1_WRAPPED/h^2" or l1.get("plaquette_area_q") != "h^2":
        raise RP1ContractError("L1_AREA_NORMALIZATION_MISSING")
    if l1.get("comparison_metrics") != ["DELTA_OMEGA_STENCIL", "DELTA_OMEGA_RESOLUTION"]:
        raise RP1ContractError("L1_COMPARISON_METRICS_INCOMPLETE")
    l2 = contract.get("l2_exact_contract", {})
    if l2.get("pair_zero_based") != [2, 3] or l2.get("thresholds") != {"MIN_EXTERNAL_PAIR_GAP": 0.02, "MIN_SIGMA": 0.9, "MAX_PRINCIPAL_ANGLE": 0.45, "MAX_PROJECTOR_DISTANCE": 0.3}:
        raise RP1ContractError("L2_CONTRACT_MUTATED")
    l3 = contract.get("l3_consistency_metric", {})
    if l3.get("metric") != "DELTA_PHASE_RANK1SUM_RANK2DET=abs(Arg(exp(i*(PHI_BAND2+PHI_BAND3-PHI_RANK2_DET))))" or "consistency_passed" in l3:
        raise RP1ContractError("L3_METRIC_UNDEFINED_OR_MUTATED")

    decisions = contract.get("decision_tree", {})
    if not {"CASE_A", "CASE_B", "CASE_C", "CASE_D"}.issubset(decisions):
        raise RP1ContractError("DECISION_TREE_INCOMPLETE")
    threshold = contract.get("threshold_governance", {})
    if threshold.get("current_min_external_gap") != 0.02 or threshold.get("threshold_change_authorized") is not False or threshold.get("source_anchor_blind_during_qualification") is not True:
        raise RP1ContractError("THRESHOLD_GOVERNANCE_INVALID")
    anchor = contract.get("source_anchor_firewall", {})
    if anchor.get("source_anchor_available_to_diagnostic_runner") is not False or anchor.get("no_source_paper_target_values") is not True:
        raise RP1ContractError("SOURCE_ANCHOR_FIREWALL_INVALID")
    firewall = contract.get("reducer_firewall", {})
    if firewall.get("band2_result_status_until_complete") != "INCOMPLETE_NOT_REPORTED" or firewall.get("diagnostic_only_is_reducer_admissible") is not False:
        raise RP1ContractError("REDUCER_FIREWALL_INVALID")
    if set(firewall.get("forbidden_rp2_outputs", [])) != {"RANK1_RECOVERED", "THRESHOLD_REVISED", "BAND2_SAMPLE_QUALIFIED_FOR_REDUCER", "numeric_band2_chern", "partial_band2_chern", "three_band_sum"}:
        raise RP1ContractError("RP2_REDUCER_OUTPUT_FIREWALL_INCOMPLETE")
    _require_false(contract.get("execution_authorization", {}), [
        "band2_recovery_execution_authorized", "berry_calculation_authorized", "chern_calculation_authorized",
        "live_mpb_authorized", "main_push_authorized", "scientific_sample_solves_authorized",
        "three_band_aggregate_authorized", "threshold_change_authorized",
    ])


def validate_manifest_path_set(manifest: Mapping[str, Any], actual_paths: Iterable[str]) -> None:
    declared, actual = set(manifest.get("changed_files", [])), set(actual_paths)
    if declared != actual:
        raise RP1ContractError(f"MANIFEST_CHANGED_PATH_SET_MISMATCH:{sorted(declared ^ actual)}")
    if "audit/e9f/rp1_c1_provenance_manifest.json" not in declared:
        raise RP1ContractError("MANIFEST_PATH_SELF_OMITTED")


def validate_process_review_index(review: Mapping[str, Any]) -> None:
    if {item["incident_id"] for item in review.get("incidents", [])} != set(review.get("repository_or_workflow_defects", [])):
        raise RP1ContractError("PROCESS_REVIEW_DEFECT_INDEX_INCOMPLETE")
