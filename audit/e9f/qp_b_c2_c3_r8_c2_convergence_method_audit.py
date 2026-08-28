"""Solver-free audit of the frozen R8.C1 convergence criterion.

This entrypoint consumes the bounded, published R8.C1 calibration projection
and its immutable acquisition binding.  It deliberately does not construct a
provider, open private arrays, or execute a solver.  The audit separates
solver-resolution convergence at fixed stencil from finite-difference stencil
convergence as h tends to zero.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
BINDING_PATH = ROOT / "audit/e9f/qp_b_c2_c3_r8_d3_acquisition_binding.json"
PRIOR_PATH = ROOT / "audit/e9f/qp_b_c2_c3_r8_c1_calibration.json"
DIAGNOSIS_PATH = ROOT / "audit/e9f/qp_b_c2_c3_r8_c2_convergence_diagnosis.json"
CONTRACT_PATH = ROOT / "audit/e9f/qp_b_c2_c3_r8_c2_prospective_validation_contract.json"

WORK_ORDER_ID = "MEPHC-E9F-C2-QP-B-C2-C3-R8-C2-M1-20260828-306"
BASE_SANDBOX_SHA = "bdf8ca8d1aca6d6d6d0327826fa771d2b67c2cf9"
MAIN_SHA = "5a4e9e839eff40f582c2404ff3eadd2bf8b676b5"
DATASET_ID = "a2935beba40ef0c4b524198e6d2f44b93630bdff4c645e61a47d31187012b3db"
MANIFEST_SHA256 = "55828e4a0eb6e24914807e42d13fa113457ce080ffe37c947b3c0cd7af1281d7"
ACQUISITION_SOURCE = "c8eeaa4e5fa78e25a5b7df07510b446b1f6d6738"
RESOLUTIONS = ("R96", "R128", "R160")
STENCILS = ("1/72", "1/144")
SAMPLE_IDS = (
    "fr=0;grid_i=-10;grid_j=-3;estimator=SOURCE_GRID",
    "fr=0;grid_i=-34;grid_j=9;estimator=SOURCE_GRID",
    "fr=0;grid_i=-6;grid_j=-1;estimator=SOURCE_GRID",
    "fr=0;grid_i=-34;grid_j=-16;estimator=SOURCE_GRID",
    "fr=0;grid_i=-34;grid_j=-17;estimator=SOURCE_GRID",
    "fr=0;grid_i=-34;grid_j=17;estimator=SOURCE_GRID",
    "fr=0;grid_i=-5;grid_j=0;estimator=SOURCE_GRID",
    "fr=0;grid_i=-4;grid_j=0;estimator=SOURCE_GRID",
)
HOLDOUT_SAMPLE_ID = "fr=0;grid_i=-34;grid_j=16;estimator=SOURCE_GRID"


class AuditError(RuntimeError):
    """Raised when a receipt-bound public input is not the expected input."""


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AuditError("JSON_OBJECT_REQUIRED")
    return value


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def srd(left: float, right: float) -> float:
    """The frozen symmetric relative difference, including its zero case."""
    left, right = float(left), float(right)
    if left == 0.0 and right == 0.0:
        return 0.0
    return 2.0 * abs(left - right) / (abs(left) + abs(right))


def relation(left: float, right: float, *, contraction: str, expansion: str, equality: str) -> str:
    if right < left:
        return contraction
    if right > left:
        return expansion
    return equality


def ratio(numerator: float, denominator: float) -> float | None:
    if denominator == 0.0:
        return None
    return numerator / denominator


def verify_inputs() -> tuple[dict[str, Any], dict[str, Any]]:
    binding = read_json(BINDING_PATH)
    prior = read_json(PRIOR_PATH)
    expected_binding = {
        "acquisition_dataset_id": DATASET_ID,
        "dataset_manifest_sha256": MANIFEST_SHA256,
        "acquisition_source_commit": ACQUISITION_SOURCE,
        "completed_key_count": 210,
        "reconciliation_status": "VERIFIED_COMPLETE_DATASET_RESULT_RECOVERED",
    }
    if any(binding.get(key) != value for key, value in expected_binding.items()):
        raise AuditError("ACQUISITION_BINDING_MISMATCH")
    if prior.get("schema") != "mephc-r8-c1-locked-set-calibration-v1":
        raise AuditError("PRIOR_C1_SCHEMA_MISMATCH")
    if prior.get("current_0p02_policy_calibration") != "INCONCLUSIVE":
        raise AuditError("C1_VERDICT_CHANGED")
    if prior.get("threshold_change_authorized") is not False:
        raise AuditError("C1_THRESHOLD_AUTHORIZATION_CHANGED")
    if prior.get("band2_chern_execution") is not False:
        raise AuditError("C1_BAND2_EXECUTION_CHANGED")
    if prior.get("dataset") != {
        "dataset_id": DATASET_ID,
        "manifest_sha256": MANIFEST_SHA256,
        "record_count": 210,
        "acquisition_source_commit": ACQUISITION_SOURCE,
    }:
        raise AuditError("PRIOR_DATASET_BINDING_MISMATCH")
    samples = prior.get("samples")
    if not isinstance(samples, dict) or set(samples) != set(SAMPLE_IDS):
        raise AuditError("LOCKED_SAMPLE_SET_MISMATCH")
    return binding, prior


def audit_sample(sample_id: str, prior_sample: dict[str, Any]) -> dict[str, Any]:
    stencils: dict[str, Any] = {}
    for stencil in STENCILS:
        source = prior_sample.get("stencils", {}).get(stencil)
        if not isinstance(source, dict) or set(source.get("omega", {})) != set(RESOLUTIONS):
            raise AuditError("OMEGA_SEQUENCE_INCOMPLETE")
        omega = {resolution: float(source["omega"][resolution]) for resolution in RESOLUTIONS}
        increment_96_128 = abs(omega["R128"] - omega["R96"])
        increment_128_160 = abs(omega["R160"] - omega["R128"])
        stencils[stencil] = {
            "omega_R96": omega["R96"],
            "omega_R128": omega["R128"],
            "omega_R160": omega["R160"],
            "abs_increment_96_128": increment_96_128,
            "abs_increment_128_160": increment_128_160,
            "abs_increment_ratio_128_160_over_96_128": ratio(increment_128_160, increment_96_128),
            "second_absolute_resolution_increment": relation(
                increment_96_128,
                increment_128_160,
                contraction="RESOLUTION_INCREMENT_CONTRACTS",
                expansion="RESOLUTION_INCREMENT_EXPANDS",
                equality="RESOLUTION_INCREMENT_EQUAL",
            ),
            "nonmonotonic_resolution_sequence": (
                omega["R128"] < min(omega["R96"], omega["R160"])
                or omega["R128"] > max(omega["R96"], omega["R160"])
            ),
        }

    signed_delta = {
        resolution: stencils["1/72"][f"omega_{resolution}"]
        - stencils["1/144"][f"omega_{resolution}"]
        for resolution in RESOLUTIONS
    }
    abs_delta = {resolution: abs(value) for resolution, value in signed_delta.items()}
    stencil_srd = {
        resolution: srd(
            stencils["1/72"][f"omega_{resolution}"],
            stencils["1/144"][f"omega_{resolution}"],
        )
        for resolution in RESOLUTIONS
    }
    abs_classification = relation(
        abs_delta["R128"],
        abs_delta["R160"],
        contraction="ABS_STENCIL_DIFFERENCE_CONTRACTS",
        expansion="ABS_STENCIL_DIFFERENCE_EXPANDS",
        equality="ABS_STENCIL_DIFFERENCE_EQUAL",
    )
    reversal = abs_classification == "ABS_STENCIL_DIFFERENCE_CONTRACTS" and stencil_srd["R160"] > stencil_srd["R128"]
    nonmonotonic = any(item["nonmonotonic_resolution_sequence"] for item in stencils.values())
    increments_contract_both = all(
        item["second_absolute_resolution_increment"] == "RESOLUTION_INCREMENT_CONTRACTS"
        for item in stencils.values()
    )
    role = str(prior_sample.get("role", ""))
    unresolved: list[str] = []
    if abs_classification == "ABS_STENCIL_DIFFERENCE_EXPANDS":
        unresolved.append("ABS_STENCIL_DISCREPANCY_EXPANDS_R128_TO_R160")
    if not increments_contract_both:
        unresolved.append("RESOLUTION_INCREMENT_CONTRACTION_FAILS_AT_ONE_OR_BOTH_STENCILS")
    if nonmonotonic:
        unresolved.append("NONMONOTONIC_RESOLUTION_SEQUENCE")
    return {
        "sample_id": sample_id,
        "role": role,
        "signed_stencil_delta": signed_delta,
        "abs_stencil_delta": abs_delta,
        "stencil_srd": stencil_srd,
        "abs_stencil_delta_ratio_160_over_128": ratio(abs_delta["R160"], abs_delta["R128"]),
        "stencil_srd_ratio_160_over_128": ratio(stencil_srd["R160"], stencil_srd["R128"]),
        "abs_stencil_difference_classification": abs_classification,
        "srd_normalization_reversal": reversal,
        "stencils": stencils,
        "resolution_increment_contraction_at_both_stencils": increments_contract_both,
        "nonmonotonic_resolution_sequence": nonmonotonic,
        "unresolved_numerical_behavior": unresolved,
    }


def count_for(items: list[dict[str, Any]], predicate: Any) -> int:
    return sum(1 for item in items if predicate(item))


def role_counts(samples: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    for role in ("CALIBRATION_CONTROL", "STENCIL_DIAGNOSTIC", "POLICY_CHALLENGE"):
        group = [item for item in samples if item["role"] == role]
        result[role] = {
            "sample_count": len(group),
            "srd_normalization_reversal_count": count_for(group, lambda x: x["srd_normalization_reversal"]),
            "abs_stencil_difference_expands_count": count_for(
                group, lambda x: x["abs_stencil_difference_classification"] == "ABS_STENCIL_DIFFERENCE_EXPANDS"
            ),
            "both_stencil_resolution_contraction_count": count_for(
                group, lambda x: x["resolution_increment_contraction_at_both_stencils"]
            ),
            "nonmonotonic_resolution_sequence_count": count_for(group, lambda x: x["nonmonotonic_resolution_sequence"]),
        }
    return result


def mathematical_audit() -> dict[str, Any]:
    return {
        "frozen_criterion": "STENCIL_SRD[R160] < STENCIL_SRD[R128]",
        "axis_A_solver_resolution": {
            "definition": "At each fixed h, study OMEGA_R(h) as R increases.",
            "mathematical_statement": "OMEGA_R(h) -> OMEGA_infinity(h) does not imply a monotone sequence in R.",
            "diagnostic": "A three-point overshoot or an expanding second increment is evidence about resolution behavior at fixed h.",
        },
        "axis_B_finite_difference_stencil": {
            "definition": "At each fixed R, study OMEGA_R(h) as h -> 0.",
            "stencil_difference": "D_R(h1,h2) = OMEGA_R(h1) - OMEGA_R(h2).",
            "srd_definition": "STENCIL_SRD[R] = 2*abs(D_R)/(abs(OMEGA_R(h1))+abs(OMEGA_R(h2))).",
            "diagnostic": "The denominator varies with R, so a decreasing or increasing SRD is not a stencil-limit proof.",
        },
        "answer_to_monotonicity_question": "Solver-resolution convergence alone does not mathematically imply monotonic decrease of STENCIL_SRD across R.",
        "decision": "STENCIL_SRD_MONOTONIC_CONTRACTION_NOT_JUSTIFIED_AS_GENERAL_SOLVER_CONVERGENCE_REQUIREMENT",
    }


def prospective_contract() -> dict[str, Any]:
    return {
        "status": "DESIGNED_NOT_EXECUTED",
        "principle": "Treat solver-resolution convergence and stencil convergence as separate axes.",
        "solver_resolution_axis": {
            "fixed_stencils": list(STENCILS),
            "evaluate_resolutions": ["R96", "R128", "R160", "R192"],
            "R192_required": True,
            "scientific_reason": "Existing control-2 and outer-boundary sequences contain R128 overshoots, so three points do not establish the next-resolution behavior at fixed h.",
            "minimal_new_provider_request_estimate": 70,
            "request_count_basis": "Eight current samples times nine point locations at one new resolution gives 72 logical demands; the two exact cross-sample duplicate relations reduce this to 70 unique requests.",
        },
        "stencil_axis": {
            "fixed_resolutions": list(RESOLUTIONS),
            "current_stencils": list(STENCILS),
            "third_finer_stencil": "1/288",
            "third_stencil_required": True,
            "scientific_reason": "Two stencil values provide one interval difference and cannot test convergence or distinguish cancellation from a finite-stencil limit.",
            "minimal_new_provider_request_estimate": 96,
            "request_count_basis": "Eight current samples times three fixed resolutions times four new off-center points; the center is reused and no current canonical point is assumed to match.",
        },
        "holdout": {
            "sample_id": HOLDOUT_SAMPLE_ID,
            "status": "RESERVED_PROSPECTIVE_HOLDOUT",
            "used_as_current_evidence": False,
            "values_fabricated": False,
        },
        "separate_future_questions": {
            "Q1": "Is the historical 0.02 external-gap qualification policy empirically conservative or necessary for reliable rank1 association/curvature?",
            "Q2": "Are the finite-difference Berry-curvature estimates themselves sufficiently converged in h?",
            "separation_rule": "Q1 requires an external-gap qualification study; Q2 requires independent h-convergence evidence. Neither question is answered by the other metric.",
        },
    }


def analyze() -> dict[str, Any]:
    binding, prior = verify_inputs()
    samples = [audit_sample(sample_id, prior["samples"][sample_id]) for sample_id in SAMPLE_IDS]
    counts = {
        "sample_count": len(samples),
        "srd_normalization_reversal_count": count_for(samples, lambda x: x["srd_normalization_reversal"]),
        "abs_stencil_difference_expands_count": count_for(
            samples, lambda x: x["abs_stencil_difference_classification"] == "ABS_STENCIL_DIFFERENCE_EXPANDS"
        ),
        "both_stencil_resolution_contraction_count": count_for(
            samples, lambda x: x["resolution_increment_contraction_at_both_stencils"]
        ),
        "nonmonotonic_resolution_sequence_count": count_for(samples, lambda x: x["nonmonotonic_resolution_sequence"]),
    }
    return {
        "schema": "mephc-r8-c2-convergence-method-audit-v1",
        "work_order_id": WORK_ORDER_ID,
        "base_sandbox_sha": BASE_SANDBOX_SHA,
        "main_sha": MAIN_SHA,
        "dataset": {
            "dataset_id": DATASET_ID,
            "manifest_sha256": MANIFEST_SHA256,
            "record_count": 210,
            "acquisition_source_commit": ACQUISITION_SOURCE,
        },
        "prior_c1_artifact_sha256": sha256(PRIOR_PATH),
        "execution": {
            "native_invocations": 0,
            "provider_requests": 0,
            "solver_executions": 0,
            "mpb_execution": False,
        },
        "prior_c1_verdict": {
            "current_0p02_policy_calibration": "INCONCLUSIVE",
            "threshold_change_authorized": False,
            "c1_rescoring": False,
        },
        "samples": {item["sample_id"]: item for item in samples},
        "counts": counts,
        "counts_by_role": role_counts(samples),
        "mathematical_audit": mathematical_audit(),
        "method_audit_decision": "STENCIL_SRD_MONOTONIC_CONTRACTION_NOT_JUSTIFIED_AS_GENERAL_SOLVER_CONVERGENCE_REQUIREMENT",
        "prospective_validation_contract": prospective_contract(),
        "current_c1_verdict_unchanged": True,
        "threshold_change_authorized": False,
        "c1_rescoring": False,
        "terminal": "E9F_C2_QP_B_C2_C3_R8_C2_M1_CONVERGENCE_METHOD_AUDIT_COMPLETE",
    }


def diagnosis_artifact(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": result["schema"],
        "work_order_id": result["work_order_id"],
        "base_sandbox_sha": result["base_sandbox_sha"],
        "main_sha": result["main_sha"],
        "dataset": result["dataset"],
        "prior_c1_artifact_sha256": result["prior_c1_artifact_sha256"],
        "execution": result["execution"],
        "prior_c1_verdict": result["prior_c1_verdict"],
        "samples": result["samples"],
        "counts": result["counts"],
        "counts_by_role": result["counts_by_role"],
        "mathematical_audit": result["mathematical_audit"],
        "method_audit_decision": result["method_audit_decision"],
        "current_c1_verdict_unchanged": result["current_c1_verdict_unchanged"],
        "threshold_change_authorized": result["threshold_change_authorized"],
        "c1_rescoring": result["c1_rescoring"],
        "terminal": result["terminal"],
    }


def contract_artifact(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "mephc-r8-c2-prospective-validation-contract-v1",
        "work_order_id": result["work_order_id"],
        "dataset": result["dataset"],
        "prior_c1_artifact_sha256": result["prior_c1_artifact_sha256"],
        "status": result["prospective_validation_contract"]["status"],
        "principle": result["prospective_validation_contract"]["principle"],
        "solver_resolution_axis": result["prospective_validation_contract"]["solver_resolution_axis"],
        "stencil_axis": result["prospective_validation_contract"]["stencil_axis"],
        "holdout": result["prospective_validation_contract"]["holdout"],
        "separate_future_questions": result["prospective_validation_contract"]["separate_future_questions"],
        "nonexecuting": True,
        "terminal": result["terminal"],
    }


def result_summary(result: dict[str, Any]) -> dict[str, Any]:
    counts = result["counts"]
    contract = result["prospective_validation_contract"]
    return {
        "schema": result["schema"],
        "work_order_id": result["work_order_id"],
        "base_sandbox_sha": result["base_sandbox_sha"],
        "dataset_id": DATASET_ID,
        "dataset_manifest_sha256": MANIFEST_SHA256,
        "sample_count": counts["sample_count"],
        "srd_normalization_reversal_count": counts["srd_normalization_reversal_count"],
        "abs_stencil_difference_expands_count": counts["abs_stencil_difference_expands_count"],
        "both_stencil_resolution_contraction_count": counts["both_stencil_resolution_contraction_count"],
        "nonmonotonic_resolution_sequence_count": counts["nonmonotonic_resolution_sequence_count"],
        "method_audit_decision": result["method_audit_decision"],
        "prospective_validation_contract_status": contract["status"],
        "third_stencil_required": contract["stencil_axis"]["third_stencil_required"],
        "R192_required": contract["solver_resolution_axis"]["R192_required"],
        "minimal_new_provider_request_estimate_R192": contract["solver_resolution_axis"]["minimal_new_provider_request_estimate"],
        "minimal_new_provider_request_estimate_h_1_288": contract["stencil_axis"]["minimal_new_provider_request_estimate"],
        "current_0p02_policy_calibration": "INCONCLUSIVE",
        "c1_rescoring": False,
        "threshold_change_authorized": False,
        "native_invocation_count": 0,
        "provider_request_count": 0,
        "native_solves": 0,
        "mpb_execution": False,
        "pipeline_health": "HEALTHY",
        "blocked_by_infrastructure": False,
        "result_sha256": hashlib.sha256(canonical(result)).hexdigest(),
        "terminal": result["terminal"],
    }


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    try:
        result = analyze()
        write_json(DIAGNOSIS_PATH, diagnosis_artifact(result))
        write_json(CONTRACT_PATH, contract_artifact(result))
        print("MEPHC_NATIVE_RESULT_JSON=" + canonical(result_summary(result)).decode("utf-8"))
        return 0
    except Exception as exc:
        print("MEPHC_NATIVE_RESULT_JSON=" + canonical({
            "schema": "mephc-r8-c2-convergence-method-audit-v1",
            "state": "failed",
            "error_code": type(exc).__name__,
            "detail": str(exc)[:1000],
            "native_invocation_count": 0,
            "provider_request_count": 0,
            "native_solves": 0,
            "mpb_execution": False,
            "terminal": "E9F_C2_QP_B_C2_C3_R8_C2_M1_FAIL_CLOSED",
        }).decode("utf-8"))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
