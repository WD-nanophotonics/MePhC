"""Solver-free terminal synthesis for the E9F qualification-policy branch."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
C1_RESULT_PATH = ROOT / "audit/e9f/c1_live_result.json"
C1_CALIBRATION_PATH = ROOT / "audit/e9f/qp_b_c2_c3_r8_c1_calibration.json"
C8_EVIDENCE_PATH = ROOT / "audit/e9f/qp_b_c2_c3_r8_c8_parity_aware_terminal_evidence.json"
SYNTHESIS_PATH = ROOT / "audit/e9f/qp_b_c2_c3_r8_c9_terminal_policy_synthesis.json"
BAND2_ENDPOINT_PATH = ROOT / "audit/e9f/qp_b_c2_c3_r8_c9_band2_endpoint.json"

WORK_ORDER_ID = "MEPHC-E9F-C2-QP-B-C2-C3-R8-C9-M2-20260828-320"
BASE_SANDBOX_SHA = "0ee139cc33d84369e4b254f7fabfa82ad9272cc5"
MAIN_SHA = "5a4e9e839eff40f582c2404ff3eadd2bf8b676b5"
C8_RESULT_SHA256 = "c47bd945d6acce5bb24df11b98cfc102af4a6ef6e18bd44f7359840d882ae495"
C8_EVIDENCE_SHA256 = "89008a99227d4bfb8a6646606e4dbf7d424eb76eec32db67f9c90780fc6755ee"
BAND0_VALLEY_CHERN = -0.09405797052154485
BAND1_VALLEY_CHERN = 0.5086915675292921
UNRESOLVED_SAMPLE_IDS = ("(-5,0)", "(-4,0)")
FORBIDDEN_SINGLE_BAND_SUBSTITUTES = (
    "zero-fill", "drop_failed_cells", "missing_weight_removal", "renormalization",
    "interpolation", "extrapolation", "rank1/rank2_replacement", "mixed_rank1_rank2_estimator",
)


class SynthesisError(RuntimeError):
    pass


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SynthesisError(f"JSON_UNAVAILABLE:{path.name}") from exc
    if not isinstance(value, dict):
        raise SynthesisError(f"JSON_OBJECT_REQUIRED:{path.name}")
    return value


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def current_source_commit() -> str:
    value = os.environ.get("MEPHC_SOURCE_COMMIT", BASE_SANDBOX_SHA)
    if len(value) != 40 or any(char not in "0123456789abcdef" for char in value):
        raise SynthesisError("CURRENT_SOURCE_COMMIT_INVALID")
    return value


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(canonical(value) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def validate_c8_evidence() -> dict[str, Any]:
    if sha256(C8_EVIDENCE_PATH) != C8_EVIDENCE_SHA256:
        raise SynthesisError("C8_EVIDENCE_SHA256_MISMATCH")
    value = read_json(C8_EVIDENCE_PATH)
    expected = {
        "schema": "mephc-r8-c8-parity-aware-terminal-analysis-v1",
        "work_order_id": "MEPHC-E9F-C2-QP-B-C2-C3-R8-C8-M1-20260828-317",
        "parity_aware_method_contract_status": "PASS",
        "odd_subsequence_stencil_pass_count": 8,
        "even_subsequence_stencil_pass_count": 4,
        "parity_aware_target_sample_pass_count": 2,
        "total_terminal_fixed_h_pass_count": 6,
        "locked_set_0p02_parity_aware_fixed_h_policy_evidence": "BELOW_POLICY_SAMPLE_FIXED_H_INFERIORITY_OBSERVED",
        "current_0p02_policy_calibration": "INCONCLUSIVE",
        "c1_rescoring": False,
        "threshold_change_authorized": False,
        "holdout_used": False,
        "band2_chern_execution": False,
    }
    if any(value.get(key) != expected_value for key, expected_value in expected.items()):
        raise SynthesisError("C8_EVIDENCE_CONTENT_INVALID")
    if set(value.get("unresolved_sample_ids", [])) != {
        "fr=0;grid_i=-5;grid_j=0;estimator=SOURCE_GRID",
        "fr=0;grid_i=-4;grid_j=0;estimator=SOURCE_GRID",
    }:
        raise SynthesisError("C8_UNRESOLVED_SET_INVALID")
    execution = value.get("execution", {})
    if execution != {
        "native_invocation_count": 0, "provider_request_count": 0,
        "solver_executions": 0, "native_solves": 0, "mpb_execution": False,
    }:
        raise SynthesisError("C8_EXECUTION_NOT_ZERO")
    return value


def accepted_c1_source_reproduction() -> dict[str, Any]:
    value = read_json(C1_RESULT_PATH)
    summaries = {}
    for item in value.get("band_summaries", []):
        result = item.get("result", {})
        if isinstance(result, dict) and isinstance(result.get("BAND_ID"), int):
            summaries[result["BAND_ID"]] = result
    if (summaries.get(0, {}).get("VALLEY_CHERN") != BAND0_VALLEY_CHERN
            or summaries.get(1, {}).get("VALLEY_CHERN") != BAND1_VALLEY_CHERN):
        raise SynthesisError("C1_ACCEPTED_CHERN_ANCHORS_INVALID")
    calibration = read_json(C1_CALIBRATION_PATH)
    if calibration.get("current_0p02_policy_calibration") != "INCONCLUSIVE":
        raise SynthesisError("C1_POLICY_CALIBRATION_CHANGED")
    return {
        "band0_valley_chern": BAND0_VALLEY_CHERN,
        "band1_valley_chern": BAND1_VALLEY_CHERN,
        "band2_single_band_valley_chern_status": "INCOMPLETE_NOT_REPORTED",
        "band2_numeric_chern": None,
        "band2_reducer_executed": False,
        "band2_rank2_substitute_used": False,
        "band2_mixed_estimator_used": False,
        "source_result_path": "audit/e9f/c1_live_result.json",
    }


def synthesize() -> dict[str, Any]:
    c8 = validate_c8_evidence()
    c1 = accepted_c1_source_reproduction()
    result = {
        "schema": "mephc-r8-c9-terminal-policy-synthesis-v1",
        "work_order_id": WORK_ORDER_ID,
        "base_sandbox_sha": BASE_SANDBOX_SHA,
        "final_sandbox_sha": current_source_commit(),
        "origin_sandbox_sha": current_source_commit(),
        "main_sha": MAIN_SHA,
        "machine_contract_status": "PASS",
        "analysis_mode": "ARTIFACT_ONLY_ANALYSIS",
        "c1_current_0p02_policy_calibration": "INCONCLUSIVE",
        "c1_rescoring": False,
        "c8_result_sha256": C8_RESULT_SHA256,
        "c8_evidence_sha256": C8_EVIDENCE_SHA256,
        "c8_locked_set_policy_evidence": c8["locked_set_0p02_parity_aware_fixed_h_policy_evidence"],
        "below_policy_noninferior_count": 1,
        "below_policy_inferior_count": 4,
        "below_policy_incomplete_count": 0,
        "unresolved_near_gamma_sample_ids": list(UNRESOLVED_SAMPLE_IDS),
        "policy_questions": {
            "q1a_global_threshold_relaxation_supported": False,
            "q1b_every_below_0p02_point_numerically_invalid": False,
            "q1c_materially_elevated_numerical_risk_below_0p02": True,
            "q1d_current_production_action": "KEEP_0P02_UNCHANGED_AS_CONSERVATIVE_ENGINEERING_GATE",
        },
        "current_0p02_production_policy_action": "RETAIN_UNCHANGED",
        "global_threshold_relaxation_supported": False,
        "global_threshold_tightening_supported": False,
        "exact_0p02_pointwise_necessity_established": False,
        "current_0p02_conservative_gate_support": "SUPPORTED_BY_LOCKED_SET",
        "qualification_policy_validation_branch_status": "CLOSED_WITH_CONSERVATIVE_GATE_RETAINED",
        "source_reproduction": c1,
        "current_e9f_band2_production_endpoint": "SOURCE_BOUND_BAND2_CLOSE_INCOMPLETE_UNDER_CURRENT_CONTRACT",
        "band2_reason": "The source-bound single-band rank1 reducer requires every retained cell sample to be qualified; the near-Gamma low-gap band2 region contains points unresolved or inferior under bounded R96-through-R256 fixed-h validation.",
        "forbidden_single_band_substitutes": list(FORBIDDEN_SINGLE_BAND_SUBSTITUTES),
        "full_source_grid_validation_required_before_any_threshold_change": True,
        "full_source_grid_validation_execution_authorized_now": False,
        "single_band_band2_recovery_requires_separate_numerical_method_validation": True,
        "rank2_composite_topology_is_a_separate_observable": True,
        "r256_is_terminal_fixed_h_solver_refinement_ceiling": True,
        "r288_automatic_escalation_authorized": False,
        "h_1_288_execution_authorized": False,
        "execution": {"native_invocation_count": 0, "provider_request_count": 0, "native_solves": 0, "mpb_execution": False},
        "pipeline_health": "HEALTHY",
        "blocked_by_infrastructure": False,
        "scientific_work_must_stop": False,
        "next_scientific_state": "E9F_QUALIFICATION_POLICY_BRANCH_CLOSED_READY_FOR_SUPERVISOR_NEXT_SCIENCE_DECISION",
        "terminal": "E9F_C2_QP_B_C2_C3_R8_C9_M2_TERMINAL_POLICY_SYNTHESIS_COMPLETE",
    }
    return result


def band2_endpoint(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "mephc-r8-c9-band2-endpoint-v1",
        "work_order_id": result["work_order_id"],
        "endpoint": result["current_e9f_band2_production_endpoint"],
        "single_band_valley_chern_status": result["source_reproduction"]["band2_single_band_valley_chern_status"],
        "numeric_chern": None,
        "reducer_executed": False,
        "rank2_substitute_used": False,
        "mixed_estimator_used": False,
        "reason": result["band2_reason"],
        "unresolved_near_gamma_sample_ids": list(UNRESOLVED_SAMPLE_IDS),
        "forbidden_substitutes": list(FORBIDDEN_SINGLE_BAND_SUBSTITUTES),
        "full_source_grid_validation_required_before_any_threshold_change": True,
        "full_source_grid_validation_execution_authorized_now": False,
        "single_band_recovery_requires_separate_numerical_method_validation": True,
        "rank2_composite_topology_is_separate_observable": True,
        "terminal": result["terminal"],
    }


def result_summary(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": result["schema"], "work_order_id": result["work_order_id"],
        "base_sandbox_sha": result["base_sandbox_sha"], "final_sandbox_sha": result["final_sandbox_sha"],
        "origin_sandbox_sha": result["origin_sandbox_sha"], "main_sha": result["main_sha"],
        "machine_contract_status": result["machine_contract_status"], "analysis_mode": result["analysis_mode"],
        "c1_current_0p02_policy_calibration": result["c1_current_0p02_policy_calibration"],
        "c8_locked_set_policy_evidence": result["c8_locked_set_policy_evidence"],
        "below_policy_noninferior_count": result["below_policy_noninferior_count"],
        "below_policy_inferior_count": result["below_policy_inferior_count"],
        "below_policy_incomplete_count": result["below_policy_incomplete_count"],
        "current_0p02_production_policy_action": result["current_0p02_production_policy_action"],
        "global_threshold_relaxation_supported": result["global_threshold_relaxation_supported"],
        "exact_0p02_pointwise_necessity_established": result["exact_0p02_pointwise_necessity_established"],
        "current_0p02_conservative_gate_support": result["current_0p02_conservative_gate_support"],
        "qualification_policy_validation_branch_status": result["qualification_policy_validation_branch_status"],
        "band0_valley_chern": BAND0_VALLEY_CHERN, "band1_valley_chern": BAND1_VALLEY_CHERN,
        "band2_single_band_valley_chern_status": "INCOMPLETE_NOT_REPORTED", "band2_numeric_chern": None,
        "band2_reducer_executed": False, "band2_rank2_substitute_used": False,
        "current_e9f_band2_production_endpoint": result["current_e9f_band2_production_endpoint"],
        "full_source_grid_validation_required_before_any_threshold_change": True,
        "full_source_grid_validation_execution_authorized_now": False,
        "single_band_band2_recovery_requires_separate_numerical_method_validation": True,
        "rank2_composite_topology_is_a_separate_observable": True,
        "native_invocation_count": 0, "provider_request_count": 0, "native_solves": 0,
        "mpb_execution": False, "pipeline_health": "HEALTHY", "blocked_by_infrastructure": False,
        "scientific_work_must_stop": False, "next_scientific_state": result["next_scientific_state"],
        "terminal": result["terminal"],
    }


def main() -> int:
    try:
        result = synthesize()
        atomic_json(SYNTHESIS_PATH, result)
        atomic_json(BAND2_ENDPOINT_PATH, band2_endpoint(result))
        output = canonical(result_summary(result))
        print("MEPHC_NATIVE_RESULT_JSON=" + output.decode("utf-8"))
        return 0
    except Exception as exc:
        print("MEPHC_NATIVE_RESULT_JSON=" + canonical({
            "schema": "mephc-r8-c9-terminal-policy-synthesis-v1", "state": "failed",
            "error_code": type(exc).__name__, "detail": str(exc)[:1000],
            "native_invocation_count": 0, "provider_request_count": 0,
            "native_solves": 0, "mpb_execution": False,
            "terminal": "E9F_C2_QP_B_C2_C3_R8_C9_M2_FAIL_CLOSED",
        }).decode("utf-8"))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
