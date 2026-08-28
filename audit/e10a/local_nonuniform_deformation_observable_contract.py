"""Solver-free E10A contract for a local nonuniform deformation observable."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
WORK_ORDER_ID = "MEPHC-E10A-LOCAL-NONUNIFORM-DEFORMATION-OBSERVABLE-CONTRACT-20260829-342"
BASE_SANDBOX_SHA = "dc8ad3d138179ea2257ff032390009faae4f8ed7"
MAIN_SHA = "5a4e9e839eff40f582c2404ff3eadd2bf8b676b5"
RUNTIME_SHA256 = "4ae06ff8c1de0a9c5f8b5ea905adf6f6030ec657b9f52da6dc30568e1baf64e5"
D11_ASSESSMENT_SHA256 = "5e942fccd63c3c152364961fca7d64376301f9592d1b6ce13253c69516d3ab86"

BOUND_PATHS = (
    "audit/e9f/d11_fr04_source_reproduction_terminal_assessment.json",
    "audit/e8a/result.json",
    "audit/e8a/weighted_berry_gradient.py",
    "audit/e8b/e8b_contract.json",
    "audit/e8b/closure.json",
    "audit/e8b/e8b_geometry.py",
    "audit/e8b/run_e8b.py",
)
OUT_CONTRACT = ROOT / "audit/e10a/local_nonuniform_deformation_observable_contract.json"
OUT_FEASIBILITY = ROOT / "audit/e10a/local_nonuniform_deformation_feasibility.json"


class ContractError(RuntimeError):
    pass


def digest_file(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise ContractError(f"FILE_UNAVAILABLE:{path}") from exc


def read_json(relative: str) -> dict[str, Any]:
    path = ROOT / relative
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"JSON_UNAVAILABLE:{relative}") from exc
    if not isinstance(value, dict):
        raise ContractError(f"JSON_OBJECT_REQUIRED:{relative}")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def verify_inputs() -> tuple[dict[str, str], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    hashes = {relative: digest_file(ROOT / relative) for relative in BOUND_PATHS}
    if hashes[BOUND_PATHS[0]] != D11_ASSESSMENT_SHA256:
        raise ContractError("D11_TERMINAL_ASSESSMENT_HASH_MISMATCH")
    d11 = read_json(BOUND_PATHS[0])
    e8a = read_json("audit/e8a/result.json")
    e8b_contract = read_json("audit/e8b/e8b_contract.json")
    e8b_closure = read_json("audit/e8b/closure.json")
    if d11.get("schema") != "mephc-e9f-d11-fr04-source-reproduction-terminal-synthesis-v1" or d11.get("terminal") != "E9F_D11_FR04_SOURCE_REPRODUCTION_TERMINAL_SYNTHESIS_COMPLETE":
        raise ContractError("D11_TERMINAL_ASSESSMENT_INVALID")
    if d11.get("all_bound_artifact_hashes_verified") is not True:
        raise ContractError("D11_BOUND_ARTIFACTS_NOT_VERIFIED")
    if e8a.get("schema") != "e8a_c1_weighted_berry_gradient_corrected_v1" or e8a.get("self_checks") != "PASSED":
        raise ContractError("E8A_RESULT_INVALID")
    classification = e8a.get("classification", {})
    required_e8a = {
        "physical_response_status": "GEOMETRIC_FUNCTIONAL_VALIDATED_DYNAMICAL_OBSERVABLE_NOT_YET_DERIVED",
        "deformation_physics_live_solve": "NOT_AUTHORIZED",
        "live_mpb": "NOT_AUTHORIZED",
        "weighted_direct_vs_ibp_periodic": "PASSED",
        "coordinate_covariance": "PASSED",
    }
    if any(classification.get(key) != value for key, value in required_e8a.items()):
        raise ContractError("E8A_CLASSIFICATION_INVALID")
    if e8b_contract.get("authorization", {}).get("local_nonuniform_deformation") is not False:
        raise ContractError("E8B_LOCAL_NONUNIFORM_AUTHORIZATION_INVALID")
    required_e8b = {
        "e8b_c2_overall": "E8B_FIRST_LIVE_AFFINE_WEIGHTED_RESPONSE_FULLY_AUDITABLE_AND_READY_FOR_FINAL_SUPERVISOR_SEAL",
        "main_unchanged": True,
    }
    if any(e8b_closure.get(key) != value for key, value in required_e8b.items()):
        raise ContractError("E8B_CLOSURE_INVALID")
    interpretation = e8b_closure.get("interpretation", {})
    expected_interpretation = {
        "UNIFORM_AFFINE_DEFORMATION": "VALIDATED_FOR_THIS_THREE_POINT_PILOT",
        "WEIGHTED_BERRY_GRADIENT_STRAIN_RESPONSE": "RESOLVED_BOUNDED_PILOT",
        "BCD_PHYSICAL_OBSERVABLE": "NOT_CLAIMED",
        "DYNAMICAL_HALL_SHIFT": "NOT_DERIVED",
        "NONLINEAR_HALL_COEFFICIENT": "NOT_DERIVED",
        "LOCAL_NONUNIFORM_DEFORMATION": "NOT_YET_STARTED",
        "STRAIN_DERIVATIVE_CONVERGENCE": "NOT_YET_ESTABLISHED",
        "STRAIN_LINEARITY": "NOT_YET_ESTABLISHED",
        "WEIGHT_DEPENDENCE": "NOT_YET_CHARACTERIZED",
    }
    if any(interpretation.get(key) != value for key, value in expected_interpretation.items()):
        raise ContractError("E8B_INTERPRETATION_INVALID")
    return hashes, d11, e8a, e8b_contract, e8b_closure


def build_documents() -> tuple[dict[str, Any], dict[str, Any]]:
    hashes, d11, e8a, e8b_contract, e8b_closure = verify_inputs()
    capability_matrix = [
        {"object": "local_omega_n_of_k", "status": "PARTIAL_STATIC_OR_SOLVER_BOUND", "missing": "No spatially varying local band-energy field omega_n(k_phys,r)."},
        {"object": "rank1_Omega_kk", "status": "VALIDATED_EXISTING", "missing": None},
        {"object": "rankN_determinant_Wilson_Omega_kk", "status": "VALIDATED_EXISTING_FOR_LOCKED_REPLAY", "missing": "No local-r dependence or phase-space extension."},
        {"object": "uniform_affine_geometry", "status": "VALIDATED_BOUNDED_E8B_PILOT", "missing": None},
        {"object": "spatially_varying_geometry", "status": "ABSENT", "missing": "Geometry/profile evaluator parameterized by r with provenance binding."},
        {"object": "grad_r_omega_n", "status": "ABSENT", "missing": "Gauge-invariant derivative of local band energy with respect to physical position."},
        {"object": "physical_k_dot", "status": "ABSENT", "missing": "A physically derived force/canonical momentum equation for the local lattice."},
        {"object": "Omega_kr_Omega_rk", "status": "ABSENT", "missing": "Mixed phase-space Berry curvature and its convention/transport equation."},
        {"object": "wavepacket_trajectory_integration", "status": "ABSENT", "missing": "Validated integrator for coupled r,k equations with local-Bloch validity checks."},
        {"object": "real_space_transverse_shift", "status": "ABSENT", "missing": "Observable map from trajectory to detector/sample displacement."},
        {"object": "uncertainty_qualification_propagation", "status": "PARTIAL_QUALIFICATION_ONLY", "missing": "Propagation of spectral/geometric uncertainty into displacement uncertainty."},
    ]
    missing_objects = [item["missing"] for item in capability_matrix if item["missing"]]
    equations = {
        "deformation": "F(r)=diag(exp(s(r)), exp(-s(r))); A(r)=F(r)A0; G(r)=A(r)^(-T)G0 in dimensionless basis convention.",
        "reciprocal_basis": "b_i(r)=(2*pi/a)[A(r)^(-T)]_i; k_phys(r)=B(r)kappa with B(r)=(2*pi/a)A(r)^(-T).",
        "normalized_coordinate": "q=a*k_phys/(2*pi); therefore q=A(r)^(-T)kappa and kappa=A(r)^T q.",
        "local_band": "omega_n(k_phys,r)=omega_n(kappa=A(r)^T*a*k_phys/(2*pi), r).",
        "strain_gradient": "grad_r s is independent physical input; it is not a relabeling of q or k_phys.",
        "semiclassical_minimal": "dot(r)=grad_k epsilon_n - dot(k) cross Omega_kk, dot(k)=-grad_r epsilon_n for a scalar local-band model with no external force convention.",
        "phase_space_completion": "The general local theory requires the coupled symplectic equations containing Omega_kk, Omega_kr, Omega_rk, and possibly Omega_rr; these objects are not implemented.",
    }
    gates = {
        "minimum_displacement": "abs(Delta_r_perp) >= max(0.1*a, 3*delta_sample) before a live pilot can claim spatial observability.",
        "deformation_smoothness": "epsilon_ad=a/L_def <= 0.05 and a*max(abs(grad_r s)) <= 0.05; abrupt profiles are outside local-Bloch scope.",
        "band_isolation": "Every sampled local state must pass the accepted external-isolation gate and declared subspace continuity/overlap gates; no threshold relaxation.",
        "propagation": "Use a predeclared L_prop and require the entire trajectory to remain inside the local-Bloch region with margin epsilon_ad <= 0.05.",
        "convergence": "Repeat profile, spatial step, k step, and wavepacket integration tolerances prospectively; require stable signed transverse shift and stable uncertainty interval.",
        "uncertainty": "Report Delta_r_perp +/- U with U <= 0.5*abs(Delta_r_perp) and propagate qualification failures as non-observable, not zero-filled data.",
        "reference_scale": "For a=400 nm only, 0.1*a is 40 nm; this is a prospective scale reference, not a measured result.",
    }
    result = {
        "schema": "mephc-e10a-local-nonuniform-deformation-observable-contract-v1",
        "work_order_id": WORK_ORDER_ID,
        "base_sandbox_sha": BASE_SANDBOX_SHA,
        "main_sha": MAIN_SHA,
        "science_runtime_sha256": RUNTIME_SHA256,
        "d11_terminal_assessment_sha256": D11_ASSESSMENT_SHA256,
        "bound_artifact_hashes": hashes,
        "machine_contract_status": "PASS",
        "e8_provenance_status": "VERIFIED_BOUND_ARTIFACTS_AND_EXACT_RECORDED_OUTCOMES",
        "e9f_terminal_provenance_status": "VERIFIED_D11_TERMINAL_ASSESSMENT",
        "uniform_affine_status": "VALIDATED_FOR_BOUNDED_THREE_POINT_PILOT",
        "local_nonuniform_status": "NOT_YET_STARTED",
        "physical_k_normalized_k_contract_status": "EXPLICIT_TRANSFORM_CHAIN_DEFINED",
        "local_bloch_validity_status": "CONTRACT_DEFINED_NOT_LIVE_VALIDATED",
        "semiclassical_equation_classification": "MIXED_PHASE_SPACE_OBJECTS_REQUIRED",
        "weighted_berry_gradient_observable_role": "DESCRIPTOR_ONLY_NO_OBSERVABLE_MAPPING_ESTABLISHED",
        "current_framework_sufficient_for_observable": False,
        "required_missing_physical_objects": missing_objects,
        "required_missing_physical_objects_text": "; ".join(missing_objects),
        "observability_scale_status": "CONTROLLED_SCALE_NOT_NUMERICALLY_ESTABLISHED",
        "future_live_observability_gates_status": "PROSPECTIVE_GATES_DEFINED_NO_LIVE_AUTHORIZATION",
        "e9f_source_binding_lesson_applied": True,
        "e10a_next_step": "THEORY_OR_FRAMEWORK_EXTENSION_REQUIRED_BEFORE_LIVE_PILOT",
        "next_live_solver_authorization": False,
        "native_invocation_count": 0,
        "provider_request_count": 0,
        "native_solves": 0,
        "mpb_execution": False,
        "pipeline_health": "HEALTHY",
        "blocked_by_infrastructure": False,
        "scientific_work_must_stop": False,
        "next_scientific_state": "E10A_LOCAL_NONUNIFORM_DEFORMATION_OBSERVABLE_CONTRACT_COMPLETE_READY_FOR_SUPERVISOR_POLICY_DECISION",
        "return_to_supervisor": True,
        "terminal": "E10A_LOCAL_NONUNIFORM_DEFORMATION_OBSERVABLE_CONTRACT_COMPLETE",
    }
    contract = {
        "schema": "mephc-e10a-local-nonuniform-deformation-observable-contract-v1",
        "work_order_id": WORK_ORDER_ID,
        "source": {"base_sandbox_sha": BASE_SANDBOX_SHA, "main_sha": MAIN_SHA, "d11_terminal_assessment_sha256": D11_ASSESSMENT_SHA256, "bound_artifact_hashes": hashes},
        "established": {
            "e8a_weighted_berry_gradient_functional": "VALIDATED_AS_A_MATHEMATICAL_NUMERICAL_FUNCTIONAL",
            "e8b_uniform_affine_deformation": "VALIDATED_FOR_BOUNDED_THREE_POINT_PILOT",
            "e8b_weighted_berry_gradient_strain_response": "RESOLVED_BOUNDED_PILOT",
            "e8b_bcd_physical_observable": "NOT_CLAIMED",
            "e8b_dynamical_hall_shift": "NOT_DERIVED",
            "e8b_nonlinear_hall_coefficient": "NOT_DERIVED",
            "e8b_local_nonuniform_deformation": "NOT_YET_STARTED",
            "e8b_strain_derivative_convergence": "NOT_YET_ESTABLISHED",
            "e8b_strain_linearity": "NOT_YET_ESTABLISHED",
            "e8b_weight_dependence": "NOT_YET_CHARACTERIZED",
        },
        "coordinate_contract": equations,
        "observable_classification": {
            "A_omega_and_Omega_kk_only": "INSUFFICIENT",
            "B_omega_Omega_kk_and_physical_k_dot": "MINIMAL_SCALAR_MODEL_ONLY",
            "C_mixed_phase_space_Berry_objects": "REQUIRED_FOR_GENERAL_LOCAL_NONUNIFORM_CASE",
            "D_complete_Maxwell_wavepacket": "REQUIRED_IF_LOCAL_BAND_REDUCTION_IS_NOT_CONTROLLED",
            "selected": "THEORY_OR_FRAMEWORK_EXTENSION_REQUIRED_BEFORE_LIVE_PILOT",
        },
        "capability_matrix": capability_matrix,
        "observability_gates": gates,
        "policy": {"production_threshold_action": "RETAIN_UNCHANGED", "main_promotion_authorized": False, "live_solver_authorized": False},
        "result_summary": result,
    }
    feasibility = {
        "schema": "mephc-e10a-local-nonuniform-deformation-feasibility-v1",
        "work_order_id": WORK_ORDER_ID,
        "status": "THEORY_OR_FRAMEWORK_EXTENSION_REQUIRED_BEFORE_LIVE_PILOT",
        "observable_is_uniquely_defined": False,
        "current_framework_sufficient": False,
        "mixed_phase_space_object_required": True,
        "weighted_berry_gradient_role": result["weighted_berry_gradient_observable_role"],
        "controlled_scale_reference": "a=400 nm gives 0.1*a=40 nm only as a prospective reference; no measured shift is reported.",
        "local_bloch_parameter": "epsilon_ad=a/L_def",
        "local_bloch_limit": "epsilon_ad <= 0.05 and a*max(abs(grad_r s)) <= 0.05",
        "missing_objects": missing_objects,
        "future_gates": gates,
        "no_live_authorization": True,
        "terminal": "E10A_LOCAL_NONUNIFORM_DEFORMATION_OBSERVABLE_CONTRACT_COMPLETE",
    }
    return contract, feasibility


def main() -> int:
    try:
        contract, feasibility = build_documents()
        write_json(OUT_CONTRACT, contract)
        write_json(OUT_FEASIBILITY, feasibility)
        print("MEPHC_NATIVE_RESULT_JSON=" + json.dumps(contract["result_summary"], sort_keys=True, separators=(",", ":"), ensure_ascii=False))
        return 0
    except Exception as exc:
        failure = {"schema": "mephc-e10a-local-nonuniform-deformation-observable-contract-v1", "work_order_id": WORK_ORDER_ID, "state": "failed", "error_code": type(exc).__name__, "detail": str(exc)[:512], "native_invocation_count": 0, "provider_request_count": 0, "solver_executions": 0, "native_solves": 0, "mpb_execution": False, "terminal": "E10A_LOCAL_NONUNIFORM_DEFORMATION_OBSERVABLE_CONTRACT_FAIL_CLOSED"}
        print("MEPHC_NATIVE_RESULT_JSON=" + json.dumps(failure, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
