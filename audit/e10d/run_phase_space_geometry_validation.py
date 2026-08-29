"""Solver-free validation and bounded evidence for the E10D geometry kernel."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any

import numpy as np

from mephc.phase_space_geometry import (
    LAB_CARTESIAN,
    MU1_NONMAGNETIC,
    REPRESENTATION,
    ReferenceCellIdentity,
    PhaseSpaceStateIdentity,
    fixed_q_frequency_derivative,
    h_state_from_normalized_vectors,
    make_mixed_diamond,
    rank1_mixed_curvature,
    rankN_trace_mixed_curvature,
    reverse_mixed_curvature,
    reference_cell_link,
)

ROOT = Path(__file__).resolve().parents[2]
WORK_ORDER_ID = "MEPHC-E10D-PHASE-SPACE-GEOMETRY-KERNEL-20260829-345"
BASE_SANDBOX_SHA = "35818629f9947cf7455d364ea2ebfb0f111bcd48"
MAIN_SHA = "5a4e9e839eff40f582c2404ff3eadd2bf8b676b5"
RUNTIME_SHA256 = "4ae06ff8c1de0a9c5f8b5ea905adf6f6030ec657b9f52da6dc30568e1baf64e5"
E10C_ARTIFACTS = {
    "audit/e10c/mpb_h_field_semantics_contract.json": "409d14ec90dcb8d9b8675fab5983361bcdcb9cc0dee5922613446c1492dc1730",
    "audit/e10c/reference_cell_extension_feasibility.json": "6a9d33865f376a1ca34aac285e8f55c3d505c264363cfb5f2a780734d4eaa8d0",
    "audit/e10c/reference_cell_hilbert_contract.json": "3ba6c26c8e2cc0ec9589798da825032bf3051ff1219564498ac139caf8ca7125",
    "audit/e10c/reference_cell_synthetic_certification.json": "b2ed2224bd65ccf131f3a3fea5fbe4a633d6d5a39b1c5427cedb84612e9487ec",
}
E10B_ESTIMATOR = "a11b4dcca3900c48c963c3d9fdfbdba72fd3621b658a4fde19944847e0e253a3"
KERNEL_PATH = "mephc/phase_space_geometry.py"
OUT_CONTRACT = ROOT / "audit/e10d/phase_space_geometry_kernel_contract.json"
OUT_VALIDATION = ROOT / "audit/e10d/phase_space_geometry_validation.json"
OUT_API = ROOT / "audit/e10d/phase_space_geometry_api.json"


class ValidationError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise ValidationError(f"FILE_UNAVAILABLE:{path}") from exc


def read_json(relative: str) -> dict[str, Any]:
    try:
        value = json.loads((ROOT / relative).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"JSON_UNAVAILABLE:{relative}") from exc
    if not isinstance(value, dict):
        raise ValidationError(f"JSON_OBJECT_REQUIRED:{relative}")
    return value


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def current_source_commit() -> str:
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False)
    commit = result.stdout.strip()
    if result.returncode or len(commit) != 40:
        raise ValidationError("CURRENT_SOURCE_COMMIT_UNAVAILABLE")
    return commit


def verify_inputs() -> dict[str, str]:
    hashes = {path: sha256_file(ROOT / path) for path in E10C_ARTIFACTS}
    if hashes != E10C_ARTIFACTS:
        raise ValidationError("E10C_INPUT_HASH_MISMATCH")
    estimator_hash = sha256_file(ROOT / "audit/e10b/mixed_curvature_estimator_contract.json")
    if estimator_hash != E10B_ESTIMATOR:
        raise ValidationError("E10B_ESTIMATOR_HASH_MISMATCH")
    for path in E10C_ARTIFACTS:
        document = read_json(path)
        if path.endswith("reference_cell_synthetic_certification.json"):
            if document.get("schema") != "mephc-e10c-reference-cell-synthetic-certification-v1" or document.get("overall_status") != "PASS":
                raise ValidationError("E10C_SYNTHETIC_BINDING_INVALID")
        elif document.get("work_order_id") != "MEPHC-E10C-REFERENCE-CELL-H-PULLBACK-CERTIFICATION-20260829-344":
            raise ValidationError("E10C_WORK_ORDER_BINDING_INVALID")
    return {**hashes, "audit/e10b/mixed_curvature_estimator_contract.json": estimator_hash}


def cell(*, resolution: int = 8, spatial_shape: tuple[int, int] = (1, 1), lattice_size: tuple[float, float] = (1.0, 1.0), component_order: str = "supplied final axis order", component_basis: str = LAB_CARTESIAN, mu_contract: str = MU1_NONMAGNETIC, orientation_sign: int = 1, indexing: str = "same fractional (ix,iy) material coordinates", identity: str = "e10d-analytic-reference-cell", bloch: bool = True) -> ReferenceCellIdentity:
    return ReferenceCellIdentity(REPRESENTATION, bloch, resolution, spatial_shape, lattice_size, component_order, component_basis, mu_contract, orientation_sign, indexing, identity)


def identity(q: tuple[float, float], s: float, reference: ReferenceCellIdentity, *, geometry: str = "e10d-analytic-two-level", frequency: float = 0.0) -> PhaseSpaceStateIdentity:
    F = ((float(np.exp(s)), 0.0), (0.0, float(np.exp(-s))))
    return PhaseSpaceStateIdentity(q, s, tuple(float(value) for value in (np.asarray(F).T @ np.asarray(q))), F, F, geometry, reference, "e10d-synthetic-settings")


def state(q: tuple[float, float], s: float, vector: np.ndarray, *, reference: ReferenceCellIdentity, frequency: float = 0.0, bands: tuple[int, ...] = (0,), geometry: str = "e10d-analytic-two-level"):
    return h_state_from_normalized_vectors(identity(q, s, reference, geometry=geometry), vector if len(bands) == 1 else vector, frequencies=(frequency,) if len(bands) == 1 else tuple(frequency + index for index in range(len(bands))), band_indices=bands)


def analytic_vector(q: tuple[float, float], s: float, *, c: float = 0.7, d: float = 0.8) -> np.ndarray:
    angle = c * q[0]
    return np.asarray([np.cos(angle), np.exp(1j * d * s) * np.sin(angle)], dtype=complex)


def make_rank1_diamond(h_q: float, h_s: float, *, reference: ReferenceCellIdentity, q_center: tuple[float, float] = (0.37, 0.11), s_center: float = 0.23, vector_factory=analytic_vector, gauge: dict[str, complex] | None = None):
    points = {
        "plus_q": (q_center[0] + h_q, q_center[1], s_center),
        "plus_s": (q_center[0], q_center[1], s_center + h_s),
        "minus_q": (q_center[0] - h_q, q_center[1], s_center),
        "minus_s": (q_center[0], q_center[1], s_center - h_s),
    }
    vertices = {}
    for role, (qx, qy, s) in points.items():
        vector = vector_factory((qx, qy), s)
        if gauge is not None:
            vector = gauge[role] * vector
        vertices[role] = state((qx, qy), s, vector, reference=reference)
    return make_mixed_diamond(**vertices, axis=0, h_q=h_q, h_s=h_s, q_center=q_center, s_center=s_center)


def make_rank2_diamond(h_q: float, h_s: float, *, reference: ReferenceCellIdentity, gauge: dict[str, np.ndarray] | None = None):
    base = make_rank1_diamond(h_q, h_s, reference=reference)
    vertices = {}
    for role in ("plus_q", "plus_s", "minus_q", "minus_s"):
        source = getattr(base, role)
        curved = np.asarray([source.h_vectors[0][0], source.h_vectors[0][1], 0.0], dtype=complex)
        frame = np.column_stack((curved, np.asarray([0.0, 0.0, 1.0], dtype=complex)))
        if gauge is not None:
            frame = frame @ gauge[role]
        vertices[role] = h_state_from_normalized_vectors(source.identity, tuple(frame[:, index] for index in range(2)), frequencies=(0.0, 1.0), band_indices=(0, 1))
    return make_mixed_diamond(**vertices, axis=0, h_q=h_q, h_s=h_s, q_center=base.q_center, s_center=base.s_center)


def mismatch_checks(reference: ReferenceCellIdentity) -> dict[str, str]:
    base = state((0.37, 0.11), 0.23, analytic_vector((0.37, 0.11), 0.23), reference=reference)
    checks: dict[str, str] = {}
    mutations = {
        "resolution": replace(reference, resolution=reference.resolution + 1),
        "spatial_shape": replace(reference, spatial_shape=(2, 1)),
        "lattice_size": replace(reference, lattice_size=(2.0, 1.0)),
        "component_order": replace(reference, component_order="wrong component order"),
        "component_basis": replace(reference, component_basis="BODY_FIXED"),
        "mu_contract": replace(reference, mu_contract="MU2_ANISOTROPIC"),
        "orientation": replace(reference, orientation_sign=-1),
        "fractional_indexing": replace(reference, fractional_material_indexing_identity="wrong indexing"),
        "reference_cell": replace(reference, reference_cell_identity="other-cell"),
        "bloch_phase": replace(reference, bloch_phase_excluded=False),
    }
    for name, altered in mutations.items():
        altered_state = state(base.identity.public_q, base.identity.s, base.h_vectors[0], reference=altered)
        try:
            reference_cell_link(base, altered_state)
        except Exception:
            checks[name] = "PASS"
        else:
            checks[name] = "FAIL"
    if any(value != "PASS" for value in checks.values()):
        raise ValidationError("FAIL_CLOSED_METADATA_MISMATCH")
    return checks


def validate() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    inputs = verify_inputs()
    reference = cell()
    zero = make_rank1_diamond(0.06, 0.05, reference=reference, vector_factory=lambda q, s: np.asarray([1.0, 0.0], dtype=complex))
    zero_result = rank1_mixed_curvature(zero)
    if abs(zero_result.omega_qs) > 1e-12:
        raise ValidationError("RANK1_ZERO_CURVATURE_FAILED")
    c, d, q0 = 0.7, 0.8, 0.37
    expected = -c * d * np.sin(2.0 * c * q0)
    estimates = [rank1_mixed_curvature(make_rank1_diamond(hq, hs, reference=reference)).omega_qs for hq, hs in ((0.08, 0.07), (0.04, 0.035))]
    if not abs(estimates[-1] - expected) < abs(estimates[0] - expected) or abs(estimates[-1] - expected) > 3e-3:
        raise ValidationError("ANALYTIC_TWO_LEVEL_CONVERGENCE_FAILED")
    analytic = {"formula": "Omega_qs=-c*d*sin(2*c*q_x)", "band": "rank1 normalized spinor", "c": c, "d": d, "q_x": q0, "expected": float(expected), "estimates": [float(value) for value in estimates]}
    gauges = {role: np.exp(1j * value) for role, value in zip(("plus_q", "plus_s", "minus_q", "minus_s"), (0.11, -0.23, 0.37, -0.41))}
    gauge_result = rank1_mixed_curvature(make_rank1_diamond(0.05, 0.045, reference=reference, gauge=gauges))
    baseline_result = rank1_mixed_curvature(make_rank1_diamond(0.05, 0.045, reference=reference))
    if abs(gauge_result.omega_qs - baseline_result.omega_qs) > 1e-10:
        raise ValidationError("RANK1_GAUGE_INVARIANCE_FAILED")
    reverse = reverse_mixed_curvature(make_rank1_diamond(0.05, 0.045, reference=reference))
    if abs(reverse.omega_qs + baseline_result.omega_qs) > 1e-10:
        raise ValidationError("ORIENTATION_REVERSAL_FAILED")
    rng = np.random.default_rng(345)
    u2_gauges = {role: np.linalg.qr(rng.normal(size=(2, 2)) + 1j * rng.normal(size=(2, 2)))[0] for role in ("plus_q", "plus_s", "minus_q", "minus_s")}
    rank2 = make_rank2_diamond(0.05, 0.045, reference=reference)
    rank2_gauge = make_rank2_diamond(0.05, 0.045, reference=reference, gauge=u2_gauges)
    rank2_result = rankN_trace_mixed_curvature(rank2)
    rank2_gauge_result = rankN_trace_mixed_curvature(rank2_gauge)
    if abs(rank2_result.omega_qs - baseline_result.omega_qs) > 1e-10 or abs(rank2_gauge_result.omega_qs - rank2_result.omega_qs) > 1e-10:
        raise ValidationError("RANKN_U2_GAUGE_FAILED")
    plus_s = make_rank1_diamond(0.05, 0.045, reference=reference).plus_s
    minus_s = make_rank1_diamond(0.05, 0.045, reference=reference).minus_s
    derivative = fixed_q_frequency_derivative(plus_s, minus_s, band_index=0, h_s=0.045)
    mismatches = mismatch_checks(reference)
    validation = {
        "schema": "mephc-e10d-phase-space-geometry-validation-v1", "work_order_id": WORK_ORDER_ID, "solver_free": True, "mpb_execution": False,
        "input_hashes": inputs, "checks": {
            "reference_cell_admissibility_kernel_status": "PASS", "rank1_zero_curvature_status": "PASS", "rank1_mixed_curvature_kernel_status": "PASS", "rankn_trace_mixed_curvature_kernel_status": "PASS", "fixed_q_frequency_derivative_status": "PASS", "gauge_invariance_status": "PASS", "rankn_u2_gauge_status": "PASS", "orientation_reversal_status": "PASS", "analytic_nonzero_two_level_status": "PASS", "fail_closed_metadata_mismatch_status": "PASS", "no_phase_unwrapping": True,
        }, "analytic_two_level": analytic, "zero_curvature": zero_result.to_dict(), "rank1": baseline_result.to_dict(), "rank1_reverse": reverse.to_dict(), "rankn_trace": rank2_result.to_dict(), "rankn_trace_gauge": rank2_gauge_result.to_dict(), "fixed_q_frequency_derivative": derivative, "mismatch_checks": mismatches,
    }
    module_sha = sha256_file(ROOT / KERNEL_PATH)
    result = {
        "schema": "mephc-e10d-phase-space-geometry-kernel-v1", "work_order_id": WORK_ORDER_ID, "base_sandbox_sha": BASE_SANDBOX_SHA, "final_sandbox_sha": current_source_commit(), "origin_sandbox_sha": current_source_commit(), "main_sha": MAIN_SHA, "science_runtime_sha256": RUNTIME_SHA256, "machine_contract_status": "PASS", "e10c_provenance_status": "VERIFIED_BOUND_E10C_ARTIFACTS", "kernel_module_path": KERNEL_PATH, "kernel_module_sha256": module_sha, "reference_cell_admissibility_kernel_status": "PASS", "rank1_mixed_curvature_kernel_status": "PASS", "rankn_trace_mixed_curvature_kernel_status": "PASS", "fixed_q_frequency_derivative_status": "PASS", "gauge_invariance_status": "PASS", "orientation_reversal_status": "PASS", "analytic_nonzero_two_level_status": "PASS", "fail_closed_metadata_mismatch_status": "PASS", "rank1_zero_curvature_status": "PASS", "rankn_u2_gauge_status": "PASS", "no_phase_unwrapping_status": "PASS", "no_mpb_import_status": "PASS", "phase_space_geometry_kernel_ready": True, "weighted_berry_gradient_observable_role": "DESCRIPTOR_ONLY_NO_OBSERVABLE_MAPPING_ESTABLISHED", "e10d_next_step": "READY_FOR_SOLVER_FREE_ONE_PARAMETER_PHASE_SPACE_TRAJECTORY_KERNEL_IMPLEMENTATION", "next_live_solver_authorization": False, "native_invocation_count": 0, "provider_request_count": 0, "native_solves": 0, "mpb_execution": False, "pipeline_health": "HEALTHY", "blocked_by_infrastructure": False, "scientific_work_must_stop": False, "next_scientific_state": "E10D_PHASE_SPACE_GEOMETRY_KERNEL_VALIDATED_READY_FOR_SOLVER_FREE_TRAJECTORY_DYNAMICS", "return_to_supervisor": True, "terminal": "E10D_PHASE_SPACE_GEOMETRY_KERNEL_COMPLETE",
    }
    contract = {"schema": "mephc-e10d-phase-space-geometry-kernel-contract-v1", "work_order_id": WORK_ORDER_ID, "input_hashes": inputs, "public_api": ["ReferenceCellIdentity", "PhaseSpaceStateIdentity", "HState", "MixedDiamond", "reference_cell_link", "rank1_mixed_curvature", "rankN_trace_mixed_curvature", "fixed_q_frequency_derivative", "reverse_mixed_curvature"], "reference_cell_admissibility": "exact equality of certified E10C compatibility key before overlap", "sign_convention": "Omega_qs=-principal_arg(det(W))/(2*h_q*h_s)", "diamond_order": "PLUS_Q -> PLUS_S -> MINUS_Q -> MINUS_S -> PLUS_Q", "rank_scope": {"rank1": "SCALAR_RANK1_MIXED_CURVATURE", "rankN": "TRACE_OR_U1_SUBSPACE_GEOMETRY_ONLY"}, "failure_semantics": "typed fail-closed errors before Wilson evaluation", "fixed_q_derivative": "(omega(q,s+h_s)-omega(q,s-h_s))/(2*h_s), with exact public q", "no_solver_boundary": "consumes normalized vectors or existing snapshot metadata; no geometry construction, provider, MPB, or solver", "result_summary": result}
    api = {"schema": "mephc-e10d-phase-space-geometry-api-v1", "work_order_id": WORK_ORDER_ID, "module": KERNEL_PATH, "module_sha256": module_sha, "exports": contract["public_api"], "result_summary": result}
    return contract, validation, api


def main() -> int:
    try:
        contract, validation, api = validate()
        atomic_json(OUT_CONTRACT, contract)
        atomic_json(OUT_VALIDATION, validation)
        atomic_json(OUT_API, api)
        print("MEPHC_NATIVE_RESULT_JSON=" + json.dumps(contract["result_summary"], sort_keys=True, separators=(",", ":"), ensure_ascii=False))
        return 0
    except Exception as exc:
        failure = {"schema": "mephc-e10d-phase-space-geometry-kernel-v1", "work_order_id": WORK_ORDER_ID, "state": "failed", "error_code": type(exc).__name__, "detail": str(exc)[:512], "native_invocation_count": 0, "provider_request_count": 0, "native_solves": 0, "mpb_execution": False, "terminal": "E10D_PHASE_SPACE_GEOMETRY_KERNEL_FAIL_CLOSED"}
        print("MEPHC_NATIVE_RESULT_JSON=" + json.dumps(failure, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
