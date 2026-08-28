"""Solver-free E10B mixed phase-space Berry geometry contract."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
WORK_ORDER_ID = "MEPHC-E10B-MIXED-PHASE-SPACE-GEOMETRY-CONTRACT-20260829-343"
BASE_SANDBOX_SHA = "8fb300ffc361872f8f46b50ec1bf96310cbc57dd"
MAIN_SHA = "5a4e9e839eff40f582c2404ff3eadd2bf8b676b5"
RUNTIME_SHA256 = "4ae06ff8c1de0a9c5f8b5ea905adf6f6030ec657b9f52da6dc30568e1baf64e5"
E10A_CONTRACT_SHA256 = "f8b8cc197ac5034f8e31b50bbd2157dbaf37642c28cc625df28304b7eab64ffc"
E10A_FEASIBILITY_SHA256 = "fece715f1dd4ca9e6eb6fcc11d0b4950189f31f24c3faa2d5ef51d20933cb7a0"

E10A_PATHS = (
    "audit/e10a/local_nonuniform_deformation_observable_contract.json",
    "audit/e10a/local_nonuniform_deformation_feasibility.json",
    "audit/e10a/local_nonuniform_deformation_observable_contract.py",
)
OUT_REFERENCE = ROOT / "audit/e10b/deformed_wavepacket_reference_contract.json"
OUT_GEOMETRY = ROOT / "audit/e10b/mixed_phase_space_geometry_contract.json"
OUT_ESTIMATOR = ROOT / "audit/e10b/mixed_curvature_estimator_contract.json"
OUT_FEASIBILITY = ROOT / "audit/e10b/phase_space_extension_feasibility.json"


class GeometryContractError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise GeometryContractError(f"FILE_UNAVAILABLE:{path}") from exc


def read_json(relative: str) -> dict[str, Any]:
    try:
        value = json.loads((ROOT / relative).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GeometryContractError(f"JSON_UNAVAILABLE:{relative}") from exc
    if not isinstance(value, dict):
        raise GeometryContractError(f"JSON_OBJECT_REQUIRED:{relative}")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def verify_e10a() -> dict[str, str]:
    hashes = {relative: sha256_file(ROOT / relative) for relative in E10A_PATHS}
    if hashes[E10A_PATHS[0]] != E10A_CONTRACT_SHA256 or hashes[E10A_PATHS[1]] != E10A_FEASIBILITY_SHA256:
        raise GeometryContractError("E10A_INPUT_HASH_MISMATCH")
    contract = read_json(E10A_PATHS[0])
    feasibility = read_json(E10A_PATHS[1])
    if contract.get("schema") != "mephc-e10a-local-nonuniform-deformation-observable-contract-v1" or feasibility.get("schema") != "mephc-e10a-local-nonuniform-deformation-feasibility-v1":
        raise GeometryContractError("E10A_INPUT_SCHEMA_INVALID")
    if contract.get("result_summary", {}).get("current_framework_sufficient_for_observable") is not False or feasibility.get("no_live_authorization") is not True:
        raise GeometryContractError("E10A_INPUT_POLICY_INVALID")
    return hashes


def documents() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    e10a_hashes = verify_e10a()
    common = {
        "work_order_id": WORK_ORDER_ID,
        "base_sandbox_sha": BASE_SANDBOX_SHA,
        "main_sha": MAIN_SHA,
        "science_runtime_sha256": RUNTIME_SHA256,
        "e10a_artifact_hashes": e10a_hashes,
        "e10a_provenance_status": "VERIFIED_BOUND_E10A_CONTRACT_AND_FEASIBILITY",
    }
    references = {
        "source_basis": "SOURCE_DERIVED_FROM_BOUND_EXTERNAL_THEORY; repository stores identities and contract, not the papers themselves",
        "theory_1": {"authors": "Kei Sawada, Shuichi Murakami, Naoto Nagaosa", "title": "Dynamical Diffraction Theory for Wave Packet Propagation in Deformed Crystals", "journal": "Phys. Rev. Lett. 96, 154802 (2006)", "arxiv": "cond-mat/0602001", "role": "deformed-crystal wavepacket trajectory and deformation-induced shift"},
        "theory_2": {"authors": "Masaru Onoda, Shuichi Murakami, Naoto Nagaosa", "title": "Geometrical Aspects in Optical Wavepacket Dynamics", "journal": "Phys. Rev. E 74, 066610 (2006)", "arxiv": "physics/0606178", "role": "semiclassical optical wavepacket Berry geometry and optical Hall framework"},
        "project_implementation_status": "REFERENCE_BOUND_CONTRACT_ONLY; no external paper text is copied into the repository",
        "equation_source_status": "SUPERVISOR_BOUND_EQUATIONS_RECORDED_AND_DERIVED_FOR_ONE_PARAMETER_FAMILY",
    }
    geometry = {
        **common,
        "schema": "mephc-e10b-mixed-phase-space-geometry-contract-v1",
        "canonical_coordinates": {"public_physical_q": "q=(a/(2*pi))*k_phys", "deformation_parameter": "s", "local_direct_lattice": "A(s)=F(s)A0", "F": "diag(exp(s),exp(-s))", "local_mpb_fractional_coordinate": "kappa(s,q)=A(s)^T q"},
        "fixed_q_chain_rule": {
            "statement": "(d/ds)|q = (partial/dpartial s)|kappa + [(partial kappa/partial s)|q] dot grad_kappa",
            "partial_kappa_fixed_q": "(partial kappa/partial s)|q=(partial_s A(s))^T q",
            "fixed_kappa_warning": "A derivative at fixed kappa is not a fixed-physical-momentum derivative under deformation.",
            "local_profile": "grad_r omega_n=[partial_s omega_n|q] grad_r s, plus only convention-required physical-coordinate terms",
        },
        "local_states": {"rank1": "|u_n(q;s)> is the periodic Maxwell eigenstate at geometry s and kappa(s,q)", "rankN": "Q_N(q;s) is the isolated rank-N subspace at the same derived kappa", "required_request_identity": ["geometry_identity", "s_identity", "physical_q_identity", "derived_local_kappa_identity", "representation_identity", "solver_configuration"]},
        "phase_space_objects": ["A_qx", "A_qy", "A_s", "Omega_qx_qy", "Omega_qx_s", "Omega_qy_s"],
        "mixed_conversion": {"Omega_qi_rj": "Omega_qi_s * partial_rj s", "Omega_ki_s": "(a/(2*pi))*Omega_qi_s", "Omega_ki_rj": "(a/(2*pi))*Omega_qi_s*partial_rj s", "units": {"Omega_qi_s": "dimensionless", "Omega_ki_s": "length", "Omega_qi_rj": "dimensionless_per_length", "Omega_ki_rj": "dimensionless"}},
        "rr_vanishing_proof": "For one scalar s, Omega_ss=-Omega_ss by antisymmetry, hence 2*Omega_ss=0 and Omega_ss=0; therefore Omega_rr_ij=Omega_ss*(partial_ri s)*(partial_rj s)=0.",
    }
    estimator = {
        **common,
        "schema": "mephc-e10b-mixed-curvature-estimator-contract-v1",
        "rank1_estimator": {"plane": "(q_i,s)", "PLUS_Q": "(q+h_q e_i,s)", "PLUS_S": "(q,s+h_s)", "MINUS_Q": "(q-h_q e_i,s)", "MINUS_S": "(q,s-h_s)", "ccw_loop": "PLUS_Q -> PLUS_S -> MINUS_Q -> MINUS_S -> PLUS_Q", "signed_area_qs": "2*h_q*h_s", "formula": "Omega_{q_i s}=-ARG_WILSON_PHASE/SIGNED_AREA_QS", "phase_rule": "principal arg(det(W)); no phase unwrapping or posthoc sign choice"},
        "rankN_estimator": {"transport": "accepted non-Abelian overlap/SVD polar transport", "wilson": "determinant phase only for trace/U(1) subspace curvature", "scope": "RANKN_DETERMINANT_WILSON_ROLE=TRACE_OR_U1_SUBSPACE_GEOMETRY_ONLY"},
        "gauge_and_orientation": ["gauge-phase invariance", "U(N) gauge invariance", "loop orientation sign reversal", "forward/reverse consistency", "independent h_q and h_s refinement"],
        "trajectory_scope": {"RANK1_ISOLATED_BAND_TRAJECTORY": "SCALAR_CURVATURE_FORMALISM", "RANKN_DEGENERATE_SUBSPACE_GENERAL_TRAJECTORY": "REQUIRES_MATRIX_VALUED_NONABELIAN_CURVATURE_PLUS_INTERNAL_STATE_EVOLUTION", "first_pilot": "prefer a safely isolated rank1 band"},
        "reference_cell_pullback": {"required_status": "UNRESOLVED_REQUIRES_MPBFIELD_COMPONENT_AND_REFERENCE_CELL_PULLBACK_CERTIFICATION", "common_material_coordinate": "u in a common reference cell; x(s,u)=A(s)u", "inner_product": "integral over reference cell of pulled-back lab-field H_L^* dot H_R with material/metric factor", "area_preserving_fact": "det F(s)=1 preserves cell area but does not prove component or material-metric equivalence", "forbidden_assumption": "Do not assume MPB field-array component conventions or reuse mpb_energy_eh_v1 merely because E8B used it", "required_transform": "certify the exact H-component pullback T_H(s,u) and any Jacobian/material metric term before cross-s overlaps"},
    }
    equations = {
        "reference_equations": {"dot_k": "dot(k)=-partial_r omega+Omega_rk dot(k)+Omega_rr dot(r)", "dot_r": "dot(r)=partial_k omega-Omega_kk dot(k)-Omega_kr dot(r)", "static_profile": "time-curvature terms absent"},
        "one_parameter_substitution": {"Omega_kr": "Omega_ks tensor grad_r s", "Omega_rk": "-transpose(Omega_kr)", "Omega_rr": "0 by scalar antisymmetry"},
        "exact_linear_system": {"matrix": "[(I-Omega_rk), -Omega_rr; Omega_kk, (I+Omega_kr)] [dot_k;dot_r]=[-partial_r omega;partial_k omega]", "validity": "requires declared phase-space conventions and invertible coupled matrix"},
        "first_order_grad_s": {"ordinary_group_velocity": "v_g=partial_k omega", "force_refraction": "dot_k=-[partial_s omega|q] grad_r s+O(|grad s|^2)", "momentum_anomalous_velocity": "+Omega_kk [partial_s omega|q grad_r s]", "mixed_deformation_velocity": "-Omega_kr v_g=-[Omega_ks tensor grad_r s]v_g", "retained_order": "both curvature terms are first order in grad_r s and neither may be discarded solely because the gradient is small"},
        "affine_limit": "The validated uniform affine E8B pilot has grad_r s=0, so Omega_kr and the deformation-force term are parametrically absent there; this does not establish their absence for local nonuniform deformation.",
    }
    extension = [
        {"object": "LOCAL_AFFINE_STATE_PROVIDER(q,s)", "status": "NEW_REQUIRED"},
        {"object": "FIXED_Q_TO_LOCAL_KAPPA_TRANSFORM", "status": "REUSABLE_WITH_CERTIFICATION"},
        {"object": "REFERENCE_CELL_H_PULLBACK", "status": "NEW_REQUIRED"},
        {"object": "PARTIAL_S_OMEGA_AT_FIXED_Q", "status": "NEW_REQUIRED"},
        {"object": "MIXED_OMEGA_QS_RANK1", "status": "NEW_REQUIRED"},
        {"object": "TRACE_MIXED_OMEGA_QS_RANKN", "status": "NEW_REQUIRED"},
        {"object": "LOCAL_PROFILE_S_OF_R_AND_GRAD_S", "status": "NEW_REQUIRED"},
        {"object": "PHASE_SPACE_TRAJECTORY_LINEAR_SOLVER", "status": "NEW_REQUIRED"},
        {"object": "LOCAL_BLOCH_VALIDITY_MONITOR", "status": "NEW_REQUIRED"},
        {"object": "TRAJECTORY_TO_TRANSVERSE_SHIFT_OBSERVABLE", "status": "NEW_REQUIRED"},
        {"object": "UNCERTAINTY_PROPAGATION", "status": "NEW_REQUIRED"},
    ]
    result = {
        **common,
        "schema": "mephc-e10b-mixed-phase-space-geometry-contract-v1",
        "reference_theory_contract_status": "SOURCE_DERIVED_FROM_BOUND_EXTERNAL_THEORY",
        "canonical_phase_space_coordinates": "PUBLIC_PHYSICAL_Q_AND_DEFORMATION_PARAMETER_S",
        "fixed_q_derivative_contract_status": "COMPLETE_WITH_KAPPA_CHAIN_RULE",
        "mixed_qs_curvature_contract_status": "COMPLETE_ONE_PARAMETER_PULLBACK",
        "mixed_wilson_estimator_status": "DEFINED_GAUGE_INVARIANT_SIGNED_DIAMOND",
        "rank1_trajectory_scope_status": "SCALAR_CURVATURE_FORMALISM",
        "rankn_trajectory_scope_status": "MATRIX_VALUED_NONABELIAN_CURVATURE_PLUS_INTERNAL_STATE_REQUIRED",
        "reference_cell_pullback_status": "UNRESOLVED_REQUIRES_CERTIFICATION",
        "h_space_variable_geometry_inner_product_status": "UNRESOLVED_REQUIRES_MATERIAL_METRIC_AND_COMPONENT_PULLBACK",
        "semiclassical_one_parameter_reduction_status": "CONTROLLED_EQUATION_SET_DERIVED",
        "weighted_berry_gradient_observable_role": "DESCRIPTOR_ONLY_NO_OBSERVABLE_MAPPING_ESTABLISHED",
        "minimal_capability_extension_status": "UNIQUELY_DEFINED_BUT_NOT_IMPLEMENTED",
        "e10b_next_step": "REFERENCE_CELL_OR_INNER_PRODUCT_CONTRACT_UNRESOLVED",
        "next_live_solver_authorization": False,
        "native_invocation_count": 0,
        "provider_request_count": 0,
        "native_solves": 0,
        "mpb_execution": False,
        "pipeline_health": "HEALTHY",
        "blocked_by_infrastructure": False,
        "scientific_work_must_stop": False,
        "next_scientific_state": "E10B_MIXED_PHASE_SPACE_GEOMETRY_CONTRACT_COMPLETE_READY_FOR_REFERENCE_CELL_INNER_PRODUCT_CONTRACT",
        "return_to_supervisor": True,
        "terminal": "E10B_MIXED_PHASE_SPACE_GEOMETRY_CONTRACT_COMPLETE",
    }
    reference_doc = {"schema": "mephc-e10b-deformed-wavepacket-reference-contract-v1", **common, "references": references, "reference_equations": equations["reference_equations"], "source_derivation_boundary": "The equations are recorded from the supervisor-bound theory identities; external papers are not represented as repository-local evidence."}
    geometry_doc = {**geometry, "reference_equations": equations, "result_summary": result}
    estimator_doc = {**estimator, "result_summary": result}
    feasibility = {"schema": "mephc-e10b-phase-space-extension-feasibility-v1", **common, "status": result["e10b_next_step"], "minimal_framework_extension_uniquely_defined": True, "reference_cell_overlap_resolved": False, "mixed_curvature_estimator_defined": True, "synthetic_validation_requirements": estimator["gauge_and_orientation"] + ["zero mixed curvature for a separable parameter-independent state", "known nonzero analytic two-level q-s model", "no phase unwrapping"], "capability_extension_matrix": extension, "no_live_authorization": True, "next_live_solver_authorization": False, "terminal": result["terminal"]}
    result["capability_extension_matrix"] = extension
    return reference_doc, geometry_doc, estimator_doc, feasibility


def main() -> int:
    try:
        reference, geometry, estimator, feasibility = documents()
        write_json(OUT_REFERENCE, reference)
        write_json(OUT_GEOMETRY, geometry)
        write_json(OUT_ESTIMATOR, estimator)
        write_json(OUT_FEASIBILITY, feasibility)
        print("MEPHC_NATIVE_RESULT_JSON=" + json.dumps(geometry["result_summary"], sort_keys=True, separators=(",", ":"), ensure_ascii=False))
        return 0
    except Exception as exc:
        failure = {"schema": "mephc-e10b-mixed-phase-space-geometry-contract-v1", "work_order_id": WORK_ORDER_ID, "state": "failed", "error_code": type(exc).__name__, "detail": str(exc)[:512], "native_invocation_count": 0, "provider_request_count": 0, "solver_executions": 0, "native_solves": 0, "mpb_execution": False, "terminal": "E10B_MIXED_PHASE_SPACE_GEOMETRY_CONTRACT_FAIL_CLOSED"}
        print("MEPHC_NATIVE_RESULT_JSON=" + json.dumps(failure, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
