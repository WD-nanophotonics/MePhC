"""Validation-only contract for the preregistered E9F.C1.RP1 policy."""
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

class RP1ContractError(ValueError):
    pass

def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def _source_records(source: Mapping[str, Any]) -> list[dict[str, Any]]:
    records = []
    for diagnostic in source.get("diagnostics", []):
        if diagnostic.get("classification") not in {FINITE, LOW_GAP}:
            continue
        numerical = diagnostic.get("existing_numerical", {})
        records.append({"sample_id": diagnostic.get("sample_id"), "sample_index": diagnostic.get("sample_index"),
                        "center": diagnostic.get("center"), "classification": diagnostic.get("classification"),
                        "classification_subtype": diagnostic.get("classification_subtype"),
                        "center_gap": numerical.get("center_gap")})
    return records

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
    if finite.get("selected_future_policy") != "F1_UNIFORM_BAND2_SOURCE_GRID_FINE_STENCIL":
        raise RP1ContractError("F1_NOT_SELECTED")
    if {item.get("policy_id") for item in finite.get("alternatives", [])} != {"F1_UNIFORM_BAND2_SOURCE_GRID_FINE_STENCIL", "F2_PREDECLARED_MIXED_STENCIL_ESTIMATOR"}:
        raise RP1ContractError("FINITE_POLICY_ALTERNATIVES_INCOMPLETE")
    if [item.get("level") for item in contract.get("low_gap_policy", {}).get("diagnostic_ladder", [])] != ["L0", "L1", "L2", "L3"]:
        raise RP1ContractError("LOW_GAP_LADDER_INCOMPLETE")
    decisions = contract.get("decision_tree", {})
    if not {"CASE_A", "CASE_B", "CASE_C", "CASE_D"}.issubset(decisions):
        raise RP1ContractError("DECISION_TREE_INCOMPLETE")
    threshold = contract.get("threshold_governance", {})
    if threshold.get("current_min_external_gap") != 0.02 or threshold.get("threshold_change_authorized") is not False:
        raise RP1ContractError("THRESHOLD_GOVERNANCE_INVALID")
    if threshold.get("source_anchor_blind_during_qualification") is not True:
        raise RP1ContractError("SOURCE_ANCHOR_BLINDNESS_MISSING")
    firewall = contract.get("reducer_firewall", {})
    if firewall.get("band2_result_status_until_complete") != "INCOMPLETE_NOT_REPORTED":
        raise RP1ContractError("REDUCER_FIREWALL_INVALID")
    if firewall.get("diagnostic_only_is_reducer_admissible") is not False:
        raise RP1ContractError("DIAGNOSTIC_LEAKAGE_ALLOWED")
    if contract.get("execution_authorization", {}).get("live_mpb_authorized") is not False:
        raise RP1ContractError("LIVE_MPB_UNAUTHORIZED_IN_RP1")

def validate_manifest_path_set(manifest: Mapping[str, Any], actual_paths: Iterable[str]) -> None:
    declared, actual = set(manifest.get("changed_files", [])), set(actual_paths)
    if declared != actual:
        raise RP1ContractError(f"MANIFEST_CHANGED_PATH_SET_MISMATCH:{sorted(declared ^ actual)}")
    if "audit/e9f/rp1_provenance_manifest.json" not in declared:
        raise RP1ContractError("MANIFEST_PATH_SELF_OMITTED")

def validate_process_review_index(review: Mapping[str, Any]) -> None:
    if {item["incident_id"] for item in review.get("incidents", [])} != set(review.get("repository_or_workflow_defects", [])):
        raise RP1ContractError("PROCESS_REVIEW_DEFECT_INDEX_INCOMPLETE")
