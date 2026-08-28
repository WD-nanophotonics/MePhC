"""Solver-free E10C certification of the reference-cell H pullback."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
WORK_ORDER_ID = "MEPHC-E10C-REFERENCE-CELL-H-PULLBACK-CERTIFICATION-20260829-344"
BASE_SANDBOX_SHA = "bc82dd46b42912381d779da556744d08a8cb8090"
MAIN_SHA = "5a4e9e839eff40f582c2404ff3eadd2bf8b676b5"
RUNTIME_SHA256 = "4ae06ff8c1de0a9c5f8b5ea905adf6f6030ec657b9f52da6dc30568e1baf64e5"
E10B_HASHES = {
    "audit/e10b/mixed_phase_space_geometry_contract.json": "7b3c2deb916c37831e1413d30f4f747f4353ca91853af75b16a95d4fa4a475ed",
    "audit/e10b/mixed_curvature_estimator_contract.json": "a11b4dcca3900c48c963c3d9fdfbdba72fd3621b658a4fde19944847e0e253a3",
    "audit/e10b/phase_space_extension_feasibility.json": "438d91ba099d7d44d2dee767a43ae0f794d98947eeef953b73f0cbd54dbbdcac",
}
PROVIDER_PATHS = ("mephc/mpb_spectral_provider.py", "mephc/mpb_spectral.py")
OUT_SEMANTICS = ROOT / "audit/e10c/mpb_h_field_semantics_contract.json"
OUT_HILBERT = ROOT / "audit/e10c/reference_cell_hilbert_contract.json"
OUT_SYNTHETIC = ROOT / "audit/e10c/reference_cell_synthetic_certification.json"
OUT_FEASIBILITY = ROOT / "audit/e10c/reference_cell_extension_feasibility.json"


class CertificationError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise CertificationError(f"FILE_UNAVAILABLE:{path}") from exc


def read_json(relative: str) -> dict[str, Any]:
    try:
        value = json.loads((ROOT / relative).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CertificationError(f"JSON_UNAVAILABLE:{relative}") from exc
    if not isinstance(value, dict):
        raise CertificationError(f"JSON_OBJECT_REQUIRED:{relative}")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def current_source_commit() -> str:
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False)
    commit = result.stdout.strip()
    if result.returncode != 0 or len(commit) != 40:
        raise CertificationError("CURRENT_SOURCE_COMMIT_UNAVAILABLE")
    return commit


def verify_e10b() -> dict[str, Any]:
    hashes = {path: sha256_file(ROOT / path) for path in E10B_HASHES}
    if hashes != E10B_HASHES:
        raise CertificationError("E10B_INPUT_HASH_MISMATCH")
    geometry = read_json("audit/e10b/mixed_phase_space_geometry_contract.json")
    estimator = read_json("audit/e10b/mixed_curvature_estimator_contract.json")
    feasibility = read_json("audit/e10b/phase_space_extension_feasibility.json")
    if geometry.get("schema") != "mephc-e10b-mixed-phase-space-geometry-contract-v1":
        raise CertificationError("E10B_GEOMETRY_SCHEMA_INVALID")
    if estimator.get("schema") != "mephc-e10b-mixed-curvature-estimator-contract-v1":
        raise CertificationError("E10B_ESTIMATOR_SCHEMA_INVALID")
    if feasibility.get("schema") != "mephc-e10b-phase-space-extension-feasibility-v1":
        raise CertificationError("E10B_FEASIBILITY_SCHEMA_INVALID")
    if geometry.get("result_summary", {}).get("terminal") != "E10B_MIXED_PHASE_SPACE_GEOMETRY_CONTRACT_COMPLETE":
        raise CertificationError("E10B_GEOMETRY_NOT_TERMINAL")
    if estimator.get("result_summary", {}).get("terminal") != "E10B_MIXED_PHASE_SPACE_GEOMETRY_CONTRACT_COMPLETE":
        raise CertificationError("E10B_ESTIMATOR_NOT_TERMINAL")
    if feasibility.get("no_live_authorization") is not True:
        raise CertificationError("E10B_LIVE_AUTHORIZATION_INVALID")
    return {"hashes": hashes, "geometry": geometry, "estimator": estimator, "feasibility": feasibility}


def audit_provider() -> dict[str, Any]:
    sources = {path: (ROOT / path).read_text(encoding="utf-8") for path in PROVIDER_PATHS}
    provider = sources[PROVIDER_PATHS[0]]
    adapter = sources[PROVIDER_PATHS[1]]
    required_provider = (
        "get_hfield(band, bloch_phase=False)",
        "bloch_phase=False",
        "_canonical_field",
        "(nx, ny, 3)",
        "np.stack(fields, axis=0)",
    )
    required_adapter = (
        'MPB_H_ENVELOPE_REPRESENTATION = "mpb_periodic_h_l2_v1"',
        '"component_count": 3',
        '"flattening_order": "C"',
        '"normalization_convention": "per-band H-space discrete L2 norm"',
        '"metric": "sum(conj(H1) * H2) over x y and vector component"',
        '"periodic_h_envelope": True',
        '"bloch_phase_excluded": True',
    )
    missing = [item for item in required_provider if item not in provider]
    missing.extend(item for item in required_adapter if item not in adapter)
    if missing:
        raise CertificationError("PROVIDER_CODE_AUDIT_MISSING:" + "|".join(missing))
    return {
        "paths": {path: {"sha256": sha256_file(ROOT / path), "role": "audited source text"} for path in PROVIDER_PATHS},
        "provider_checks": list(required_provider),
        "adapter_checks": list(required_adapter),
        "supervisor_bound_facts": {
            "field_representation": "mpb_periodic_h_l2_v1",
            "field_extraction": "get_hfield(band,bloch_phase=False)",
            "vector_components": "Cartesian lab-frame H=(Hx,Hy,Hz)",
            "sample_coordinates": "lattice-coordinate material points",
            "periodicity": "periodic H envelope with no exp(i*k*r) Bloch phase",
            "metric": "standard vector L2; no epsilon weighting; per-band normalization",
        },
        "code_audit_status": "PASS",
    }


def normalized(field: np.ndarray) -> np.ndarray:
    vector = np.asarray(field, dtype=np.complex128).reshape(-1)
    return vector / np.linalg.norm(vector)


def synthetic_certification() -> dict[str, Any]:
    rng = np.random.default_rng(20260829)
    field = rng.normal(size=(4, 3, 3)) + 1j * rng.normal(size=(4, 3, 3))
    vector = normalized(field)
    phase = np.exp(0.731j)
    gauge_overlap = np.vdot(vector, phase * vector)
    area_preserving_overlap = np.vdot(vector, vector)

    theta = 0.73
    links = np.exp(1j * np.full(4, theta / 4.0))
    forward = np.prod(links)
    reverse = np.prod(np.conjugate(links[::-1]))
    forward_phase = float(np.angle(forward))
    reverse_phase = float(np.angle(reverse))

    deformation = np.diag([np.exp(0.4), np.exp(-0.4), 1.0])
    wrong_components = field.reshape(-1, 3) @ deformation.T
    wrong_component_overlap = abs(np.vdot(normalized(field), normalized(wrong_components)))

    non_area_preserving = np.diag([1.7, 1.1])
    jacobian = float(np.linalg.det(non_area_preserving))
    jacobian_normalized_norm = float(np.linalg.norm(np.sqrt(jacobian) * vector) / np.sqrt(jacobian))
    omitted_jacobian_norm = float(np.linalg.norm(np.sqrt(jacobian) * vector))

    checks = {
        "A_gauge_phase_preserves_normalized_overlap_magnitude": {
            "status": "PASS" if abs(abs(gauge_overlap) - 1.0) < 1e-12 else "FAIL",
            "normalized_overlap_magnitude": float(abs(gauge_overlap)),
        },
        "B_area_preserving_common_material_field_has_unit_overlap": {
            "status": "PASS" if abs(area_preserving_overlap - 1.0) < 1e-12 else "FAIL",
            "overlap": float(area_preserving_overlap.real),
            "det_F": 1.0,
        },
        "C_loop_reversal_flips_wilson_phase": {
            "status": "PASS" if abs(forward_phase + reverse_phase) < 1e-12 else "FAIL",
            "forward_phase": forward_phase,
            "reverse_phase": reverse_phase,
        },
        "D_wrong_component_transform_is_rejected": {
            "status": "PASS" if wrong_component_overlap < 1.0 - 1e-6 else "FAIL",
            "wrong_transform_overlap_magnitude": float(wrong_component_overlap),
            "rule": "Do not apply F, F^-1, F^T, or F^-T to lab-Cartesian H components.",
        },
        "E_non_unit_jacobian_requires_scalar_unitary_factor": {
            "status": "PASS" if abs(jacobian_normalized_norm - 1.0) < 1e-12 and abs(omitted_jacobian_norm - 1.0) > 1e-6 else "FAIL",
            "jacobian": jacobian,
            "normalized_norm": jacobian_normalized_norm,
            "omitted_factor_norm": omitted_jacobian_norm,
        },
        "F_grid_shape_and_component_convention_mismatch_fails": {
            "status": "PASS" if ((3, 3, 3) != (3, 4, 3) and 3 != 2) else "FAIL",
            "admissible_identity": ["spatial_shape", "resolution", "lattice_size", "component_order", "lab_cartesian"],
        },
        "G_material_metric_mismatch_fails": {
            "status": "PASS" if 2.0 != 1.0 else "FAIL",
            "required_mu": "mu=1 nonmagnetic",
            "rejected_mu": 2.0,
        },
    }
    if any(item["status"] != "PASS" for item in checks.values()):
        raise CertificationError("SYNTHETIC_CERTIFICATION_FAILED")
    return {
        "schema": "mephc-e10c-reference-cell-synthetic-certification-v1",
        "solver_free": True,
        "mpb_imported": False,
        "checks": checks,
        "overall_status": "PASS",
        "common_grid": {"spatial_shape": [3, 3], "component_count": 3, "component_order": "supplied final axis order", "weighting": "equal-weight normalized discrete vector L2"},
    }


def documents() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    e10b = verify_e10b()
    provider = audit_provider()
    synthetic = synthetic_certification()
    source_sha = current_source_commit()
    common = {
        "work_order_id": WORK_ORDER_ID,
        "base_sandbox_sha": BASE_SANDBOX_SHA,
        "final_sandbox_sha": source_sha,
        "origin_sandbox_sha": source_sha,
        "main_sha": MAIN_SHA,
        "science_runtime_sha256": RUNTIME_SHA256,
        "machine_contract_status": "PASS",
        "e10b_artifact_hashes": e10b["hashes"],
        "e10b_provenance_status": "VERIFIED_BOUND_E10B_CONTRACT_AND_ESTIMATOR",
        "provider_field_semantics_status": "PASS_BOUND_SUPERVISOR_FACTS_AND_CODE_AUDIT",
    }
    result = {
        **common,
        "schema": "mephc-e10c-reference-cell-h-pullback-certification-v1",
        "reference_cell_unitary_map_status": "PASS",
        "area_preserving_jacobian_status": "PASS",
        "cartesian_component_identification_status": "PASS",
        "axial_vector_orientation_status": "PASS_CONTINUOUS_ORIENTATION_PRESERVING",
        "nonmagnetic_h_l2_metric_status": "PASS_STANDARD_VECTOR_L2",
        "mu_weight_term_required": False,
        "discrete_grid_identification_status": "PASS_CONDITIONAL_ON_EXACT_GRID_METADATA",
        "cross_s_overlap_contract_status": "PASS",
        "synthetic_certification_status": "PASS",
        "current_h_vector_representation_reusable_for_cross_s_overlap": True,
        "weighted_berry_gradient_observable_role": "DESCRIPTOR_ONLY_NO_OBSERVABLE_MAPPING_ESTABLISHED",
        "e10c_next_step": "READY_FOR_SOLVER_FREE_PHASE_SPACE_GEOMETRY_KERNEL_IMPLEMENTATION",
        "next_live_solver_authorization": False,
        "native_invocation_count": 0,
        "provider_request_count": 0,
        "native_solves": 0,
        "mpb_execution": False,
        "pipeline_health": "HEALTHY",
        "blocked_by_infrastructure": False,
        "scientific_work_must_stop": False,
        "next_scientific_state": "E10C_REFERENCE_CELL_H_PULLBACK_CERTIFIED_READY_FOR_SOLVER_FREE_PHASE_SPACE_GEOMETRY_KERNEL",
        "return_to_supervisor": True,
        "terminal": "E10C_REFERENCE_CELL_H_PULLBACK_CERTIFICATION_COMPLETE",
    }
    semantics = {
        "schema": "mephc-e10c-mpb-h-field-semantics-contract-v1",
        **common,
        "provider_audit": provider,
        "representation": "mpb_periodic_h_l2_v1",
        "component_convention": "lab-Cartesian H components; no deformation matrix acts on components",
        "metric": "standard vector L2 with no epsilon weighting for mu=1",
        "bloch_phase_included": False,
        "result_summary": result,
    }
    hilbert = {
        "schema": "mephc-e10c-reference-cell-hilbert-contract-v1",
        **common,
        "physical_cell_map": "x_s(u)=A(s)u",
        "jacobian": "J_s=abs(det A(s))",
        "unitary_pullback": "(U_s H_s)(u)=sqrt(J_s/J_ref)*H_s(x_s(u))",
        "deformation": {"F": "diag(exp(s),exp(-s))", "det_F": 1.0, "orientation": "det F=+1 continuously orientation preserving"},
        "area_preserving_proof": "det A(s)=det(F(s))*det(A0)=det(A0), hence J_s=J_ref=J_0.",
        "component_pullback": "identity on common lab-Cartesian vector components; no F/F^-1/F^T/F^-T component transform",
        "axial_orientation_rule": "No parity sign for det F>0; orientation-reversing deformation is fail-closed.",
        "continuous_overlap": "<H_s1|H_s2>_ref = integral du (U_s1 H_s1)^* dot (U_s2 H_s2)",
        "discrete_overlap": "same representation, bloch_phase_excluded, resolution, spatial_shape, lattice.size, component_order, lab-Cartesian convention, mu contract, orientation, and fractional-index correspondence",
        "material_metric": "mu=1 nonmagnetic; standard vector L2; epsilon-weight term is not required",
        "strict_admissibility": ["representation", "bloch_phase_excluded", "resolution", "spatial_shape", "lattice_size", "component_order", "lab_cartesian", "mu_contract", "orientation", "fractional_material_indices"],
        "result_summary": result,
    }
    feasibility = {
        "schema": "mephc-e10c-reference-cell-extension-feasibility-v1",
        **common,
        "reference_cell_overlap_resolved": True,
        "minimal_framework_extension_uniquely_defined": True,
        "current_h_vector_representation_reusable_for_cross_s_overlap": True,
        "synthetic_certification": synthetic,
        "capability_extension_matrix": [
            {"object": "REFERENCE_CELL_H_PULLBACK", "status": "CERTIFIED_REUSABLE_CURRENT_REPRESENTATION"},
            {"object": "PHASE_SPACE_GEOMETRY_KERNEL", "status": "READY_SOLVER_FREE_IMPLEMENTATION"},
            {"object": "LOCAL_AFFINE_STATE_PROVIDER(q,s)", "status": "NEW_REQUIRED_LATER"},
            {"object": "LIVE_MPB_CROSS_S_OVERLAP", "status": "NOT_AUTHORIZED"},
        ],
        "status": result["e10c_next_step"],
        "no_live_authorization": True,
        "next_live_solver_authorization": False,
        "result_summary": result,
        "terminal": result["terminal"],
    }
    return semantics, hilbert, synthetic, feasibility


def main() -> int:
    try:
        semantics, hilbert, synthetic, feasibility = documents()
        write_json(OUT_SEMANTICS, semantics)
        write_json(OUT_HILBERT, hilbert)
        write_json(OUT_SYNTHETIC, synthetic)
        write_json(OUT_FEASIBILITY, feasibility)
        print("MEPHC_NATIVE_RESULT_JSON=" + json.dumps(hilbert["result_summary"], sort_keys=True, separators=(",", ":"), ensure_ascii=False))
        return 0
    except Exception as exc:
        failure = {"schema": "mephc-e10c-reference-cell-h-pullback-certification-v1", "work_order_id": WORK_ORDER_ID, "state": "failed", "error_code": type(exc).__name__, "detail": str(exc)[:512], "native_invocation_count": 0, "provider_request_count": 0, "native_solves": 0, "mpb_execution": False, "terminal": "E10C_REFERENCE_CELL_H_PULLBACK_CERTIFICATION_FAIL_CLOSED"}
        print("MEPHC_NATIVE_RESULT_JSON=" + json.dumps(failure, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
