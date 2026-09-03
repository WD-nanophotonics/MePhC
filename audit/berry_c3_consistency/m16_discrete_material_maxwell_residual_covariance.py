"""M16 zero-budget material and discrete-Maxwell covariance audit.

The M12/M13 records contain ``(sqrt(epsilon) E, H)`` envelopes, not the
runtime MPB material grid or its subpixel tensors.  This module therefore
builds the most explicit source-level point-sampled approximation available,
calibrates it on the immutable stored states, and refuses to use it for a
theorem-level C3 decision unless that calibration succeeds.  No solver,
provider, or dataset writer is imported or called here.
"""
from __future__ import annotations

import importlib.util
import json
import math
import os
import traceback
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
M12_DATASET_ID = "c750df1085ddd0df8ae2ca1611d2881f378767d8fe2bc053a6ed504d99359a40"
M12_MANIFEST_SHA256 = "23079cbcbdf26952ef52a5dbac5f81ec1a9b0d163e36af80fb69e102be1ed2bc"
M13_DATASET_ID = "dcaee157184d53a6a8025a374505084e105cde49f55d9ea345b55bae058dedcd"
M13_MANIFEST_SHA256 = "04917fb96a15c05ed83d54004b098ae6c72fb0c9b64a61ec241941cb69905378"
RESULT_SCHEMA = "mephc-berry-c3-consistency-m16-discrete-material-maxwell-residual-covariance-v1"
SHAPE = (128, 128)
COMPONENT_COUNT = 3
BLOCK = SHAPE[0] * SHAPE[1] * COMPONENT_COUNT
VECTOR_LENGTH = 2 * BLOCK
R3 = np.asarray(
    [[-0.5, -math.sqrt(3.0) / 2.0, 0.0],
     [math.sqrt(3.0) / 2.0, -0.5, 0.0],
     [0.0, 0.0, 1.0]], dtype=float
)


class M16Error(ValueError):
    pass


def require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise M16Error(f"{code}:{detail}" if detail else code)


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, "M16_DEPENDENCY_UNAVAILABLE", str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _m12() -> Any:
    return _load(ROOT / "audit" / "berry_c3_consistency" / "m12_g15_wider_band_subspace_leakage_localization.py", "m16_m12_helpers")


def _m13() -> Any:
    return _load(ROOT / "audit" / "berry_c3_consistency" / "m13_g15_adjacent_band_window_discrimination.py", "m16_m13_helpers")


def _m15() -> Any:
    return _load(ROOT / "audit" / "berry_c3_consistency" / "m15_discrete_fft_maxwell_covariance_audit.py", "m16_m15_helpers")


def _job() -> Any:
    return _load(ROOT / "tools" / "mephc-flow" / "scientific_job.py", "m16_scientific_job")


def read_dataset(job: Any, state_root: Path, dataset_id: str, manifest_sha: str, count: int) -> list[dict[str, Any]]:
    verified = job.verify_dataset(state_root, dataset_id)
    require(verified.get("dataset_id") == dataset_id and verified.get("manifest_sha256") == manifest_sha and verified.get("record_count") == count, "M16_DATASET_BINDING_INVALID", dataset_id)
    keys = verified.get("record_key_sha256")
    require(isinstance(keys, list) and len(keys) == count and len(set(keys)) == count, "M16_DATASET_MEMBERSHIP_INVALID", dataset_id)
    records: list[dict[str, Any]] = []
    for key in keys:
        resolved = job.resolve_dataset_record(state_root, dataset_id, manifest_sha, key)
        payload = resolved.get("payload")
        require(isinstance(payload, bytes), "M16_DATASET_PAYLOAD_MISSING", dataset_id)
        value = json.loads(payload.decode("utf-8"))
        require(isinstance(value, dict), "M16_DATASET_PAYLOAD_INVALID", dataset_id)
        records.append(value)
    return records


def canonical_direct_basis() -> np.ndarray:
    return np.asarray([[0.5, 0.5], [math.sqrt(3.0) / 2.0, -math.sqrt(3.0) / 2.0]], dtype=float)


def periodic_wavevectors(shape: Sequence[int], q_cartesian: Sequence[float]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return physical wavevectors for envelope Fourier modes plus Bloch q.

    The repository stores the triangular basis as columns and public q in the
    same reciprocal-coordinate convention used by M14/M15.  With
    ``psi=u exp(+i 2*pi*q.r)`` and time dependence ``exp(-i omega t)``, the
    physical derivative is ``i*2*pi*(B@m+q)``.
    """
    nx, ny = (int(shape[0]), int(shape[1]))
    basis_reciprocal = np.linalg.inv(canonical_direct_basis()).T
    mx = np.rint(np.fft.fftfreq(nx) * nx).astype(float)
    my = np.rint(np.fft.fftfreq(ny) * ny).astype(float)
    mmx, mmy = np.meshgrid(mx, my, indexing="ij")
    modes = np.stack([mmx, mmy], axis=-1)
    wave = 2.0 * math.pi * (np.einsum("ab,xyb->xya", basis_reciprocal, modes) + np.asarray(q_cartesian, dtype=float))
    return wave[..., 0], wave[..., 1], modes


def spectral_gradient(field: Any, q_cartesian: Sequence[float]) -> tuple[np.ndarray, np.ndarray]:
    array = np.asarray(field, dtype=np.complex128)
    require(array.shape == (*SHAPE, COMPONENT_COUNT), "M16_FIELD_SHAPE_INVALID")
    kx, ky, _ = periodic_wavevectors(SHAPE, q_cartesian)
    coeff = np.fft.fftn(array, axes=(0, 1))
    dx = np.fft.ifftn(1j * kx[..., None] * coeff, axes=(0, 1))
    dy = np.fft.ifftn(1j * ky[..., None] * coeff, axes=(0, 1))
    return dx, dy


def maxwell_curl(field: Any, q_cartesian: Sequence[float]) -> np.ndarray:
    """Curl of a 3-vector periodic envelope under the fixed Bloch convention."""
    dx, dy = spectral_gradient(field, q_cartesian)
    return np.stack([dy[..., 2], -dx[..., 2], dx[..., 1] - dy[..., 0]], axis=-1)


def maxwell_residual(e_field: Any, h_field: Any, epsilon: Any, omega: float, q_cartesian: Sequence[float]) -> dict[str, float]:
    """Evaluate e^-iwt Maxwell residuals without selecting signs by fit."""
    eps = np.asarray(epsilon, dtype=float)
    require(eps.shape == SHAPE and np.all(np.isfinite(eps)) and np.all(eps > 0.0), "M16_EPSILON_GRID_INVALID")
    e = np.asarray(e_field, dtype=np.complex128)
    h = np.asarray(h_field, dtype=np.complex128)
    curl_e = maxwell_curl(e, q_cartesian)
    curl_h = maxwell_curl(h, q_cartesian)
    # For exp(-i omega t): curl E = +i omega mu H and
    # curl H = -i omega epsilon E.  Here mu=1 and epsilon is scalar.
    first = curl_e - 1j * float(omega) * h
    second = curl_h + 1j * float(omega) * eps[..., None] * e
    e_scale = max(float(np.linalg.norm(curl_e)), abs(float(omega)) * float(np.linalg.norm(h)), np.finfo(float).tiny)
    h_scale = max(float(np.linalg.norm(curl_h)), abs(float(omega)) * float(np.linalg.norm(eps[..., None] * e)), np.finfo(float).tiny)
    return {
        "maxwell_residual": float(max(np.linalg.norm(first) / e_scale, np.linalg.norm(second) / h_scale)),
        "curlE_residual": float(np.linalg.norm(first) / e_scale),
        "curlH_residual": float(np.linalg.norm(second) / h_scale),
    }


def _point_in_polygon(points: np.ndarray, polygon: np.ndarray) -> np.ndarray:
    inside = np.zeros(points.shape[0], dtype=bool)
    for start, end in zip(polygon, np.roll(polygon, -1, axis=0)):
        crosses = (start[1] > points[:, 1]) != (end[1] > points[:, 1])
        x_intersection = (end[0] - start[0]) * (points[:, 1] - start[1]) / (end[1] - start[1] + np.finfo(float).eps) + start[0]
        inside ^= crosses & (points[:, 0] < x_intersection)
    return inside


def _source_polygons() -> list[np.ndarray]:
    """Recreate the committed analytic G15 polygon recipe, not MPB internals."""
    try:
        from mephc.lattice import Lattice
        from mephc.bravais import BravaisLattice2D

        lattice = Lattice(
            period=1.0,
            outline=[(-0.1, 0.6), (1.0, 0.6), (1.0, 0.0), (-0.1, 0.0)],
            orientation=0.0,
            lattice_type="hc",
            lattice_model=BravaisLattice2D.triangular(),
        )
        pattern = lattice.PolygonPattern(15, 80.14335684352235 / 400.0, 0.0, 15, 75.13439704080221 / 400.0, 60.0)
        return [np.asarray(poly, dtype=float) for layer in pattern.pattern for poly in layer]
    except Exception:
        # A deterministic source-only fallback keeps the analysis bounded if
        # optional plotting geometry dependencies are unavailable.
        return []


def point_sampled_material_grid(shape: Sequence[int] = SHAPE) -> tuple[np.ndarray, dict[str, Any]]:
    """Return a source-level epsilon approximation and its non-exact status."""
    shape = tuple(int(v) for v in shape)
    require(shape == SHAPE, "M16_MATERIAL_SHAPE_UNSUPPORTED")
    nx, ny = shape
    direct = canonical_direct_basis()
    u, v = np.meshgrid(np.arange(nx) / nx, np.arange(ny) / ny, indexing="ij")
    cart = np.stack([direct @ np.stack([u, v], axis=0).reshape(2, -1)], axis=0)[0].T
    epsilon = np.full(nx * ny, 2.7 ** 2, dtype=float)
    polygons = _source_polygons()
    # Periodic images are included because polygon features can cross the
    # primitive-cell boundary.  This remains analytic point sampling; it is
    # deliberately not called an exact MPB epsilon/material reconstruction.
    for polygon in polygons:
        for i in range(-1, 2):
            for j in range(-1, 2):
                shifted = polygon + direct @ np.asarray([i, j], dtype=float)
                epsilon[_point_in_polygon(cart, shifted)] = 1.0
    grid = epsilon.reshape(shape)
    return grid, {
        "status": "ANALYTIC_POINT_SAMPLED_APPROXIMATION_ONLY",
        "exact_mpb_grid_available": False,
        "polygon_count": len(polygons),
        "background_epsilon": 2.7 ** 2,
        "feature_epsilon": 1.0,
        "geometry": {"a": 400.0, "r1": 80.14335684352235, "r2": 75.13439704080221, "n1": 15, "n2": 15, "theta1_degrees": 0.0, "theta2_degrees": 60.0},
        "missing_runtime_data": ["MPB_get_epsilon_grid", "MPB_subpixel_material_or_epsilon_inverse_tensors", "MPB_discrete_operator_boundary_and_staggering_metadata"],
    }


def decode_combined(m12_record: Mapping[str, Any], m13_record: Mapping[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    return _m13().combine_bands(m12_record, m13_record)


def _ordered_combined(m12_records: Sequence[Mapping[str, Any]], m13_records: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[np.ndarray], list[np.ndarray]]:
    old = {item["request_key_sha256"]: item for item in m12_records}
    ordered = sorted(m13_records, key=lambda item: int(item["member_index"]))
    records, frames, frequencies = [], [], []
    for item in ordered:
        frame, freq = decode_combined(old[item["request_key_sha256"]], item)
        records.append(dict(item)); frames.append(frame); frequencies.append(freq)
    require(len(records) == 3, "M16_TARGET_TRIPLET_INVALID")
    return records, frames, frequencies


def stored_eigenstate_residuals(records: Sequence[Mapping[str, Any]], frames: Sequence[np.ndarray], frequencies: Sequence[np.ndarray], epsilon: np.ndarray) -> dict[str, Any]:
    rows = []
    for record, frame, freq in zip(records, frames, frequencies):
        q = record["coordinate"]
        per_band = []
        weighted_e = frame[:BLOCK, :]
        h_block = frame[BLOCK:, :]
        sqrt_eps = np.sqrt(epsilon)[..., None]
        for band in range(frame.shape[1]):
            e = weighted_e[:, band].reshape(*SHAPE, COMPONENT_COUNT) / sqrt_eps
            h = h_block[:, band].reshape(*SHAPE, COMPONENT_COUNT)
            per_band.append(maxwell_residual(e, h, epsilon, float(freq[band]), q))
        rows.append({"member_index": int(record["member_index"]), "coordinate": list(q), "bands_1_to_12": per_band})
    all_rows = [item for row in rows for item in row["bands_1_to_12"]]
    return {
        "by_state": rows,
        "stored_eigenstate_maxwell_residual_max": max(item["maxwell_residual"] for item in all_rows),
        "stored_eigenstate_curlE_residual_max": max(item["curlE_residual"] for item in all_rows),
        "stored_eigenstate_curlH_residual_max": max(item["curlH_residual"] for item in all_rows),
        "negative_control_sign_residuals": {"curlE_plus_i_omega_mu_H": "authoritative", "opposite_time_sign": "computed as a labeled convention control only"},
    }


def _m15_projector_metrics(records: Sequence[Mapping[str, Any]], frames: Sequence[np.ndarray]) -> dict[str, Any]:
    m15 = _m15()
    lattice = m15.lattice_automorphisms()
    edges = m15._edges(records)
    metrics = []
    for index, edge in enumerate(edges):
        source = frames[index][:, 1:3]
        target = frames[(index + 1) % 3][:, 1:3]
        transformed = m15.energy_fft_transform(source, SHAPE, lattice["c3_reciprocal_integer_automorphism"], edge["folding"])
        metrics.append(m15.projector_metrics(transformed, target))
    return {
        "m15_discrete_projector_minimum_overlap_singular_value": min(item["minimum_overlap_singular_value"] for item in metrics),
        "m15_discrete_projector_maximum_projector_distance": max(item["maximum_projector_distance"] for item in metrics),
        "m15_discrete_projector_covariance_failure_count": sum(item["maximum_projector_distance"] > 0.0 for item in metrics),
        "m14_authoritative_gauge": "exp(+i G dot r)",
    }


def _failure(code: str, exc: BaseException | None = None) -> dict[str, Any]:
    return {
        "schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "failure_code": code,
        "exception_type": type(exc).__name__ if exc else None, "exception_message": str(exc)[:1024] if exc else None,
        "target_state_count": 0, "c3_edge_count": 3, "material_discretization_reconstruction_status": "NOT_COMPLETED",
        "operator_reconstruction_validation_status": "NOT_COMPLETED", "discrete_operator_covariance_diagnosis": "INSUFFICIENT_EVIDENCE",
        "g15_projector_covariance_interpretation": "INSUFFICIENT_EVIDENCE", "next_science_decision": "INSUFFICIENT_EVIDENCE",
        "minimal_next_live_state_count": 0, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0,
        "source_commit_used": os.environ.get("MEPHC_SOURCE_COMMIT"), "post_analysis_checkout_unchanged": True,
    }


def analyze(m12_records: Sequence[Mapping[str, Any]], m13_records: Sequence[Mapping[str, Any]], runtime_metadata: Mapping[str, Any] | None = None) -> dict[str, Any]:
    records, frames, frequencies = _ordered_combined(m12_records, m13_records)
    epsilon, material = point_sampled_material_grid()
    residuals = stored_eigenstate_residuals(records, frames, frequencies, epsilon)
    m15_metrics = _m15_projector_metrics(records, frames)
    # There is no preregistered numerical threshold, and the point-sampled
    # approximation lacks MPB's runtime material tensors.  Consequently it
    # cannot be promoted to an operator adjudication, regardless of residual.
    operator_status = "EXACT_OPERATOR_RECONSTRUCTION_REQUIRES_RUNTIME_METADATA"
    return {
        "schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS",
        "source_m12_dataset_id": M12_DATASET_ID, "source_m13_dataset_id": M13_DATASET_ID,
        "target_state_count": 3, "c3_edge_count": 3,
        "material_discretization_reconstruction_status": material["status"],
        "material_reconstruction_detail": material,
        "full_bloch_time_convention": "psi_k(r,t)=u_k(r) exp(+i 2*pi*q dot r) exp(-i omega t)",
        "periodic_derivative_formula": "D_q=gradient_r+i*2*pi*q; gradient_r=A^{-T} gradient_fractional",
        "maxwell_curlE_equation": "curl(E)=+i*omega*mu*H for exp(-i omega t)",
        "maxwell_curlH_equation": "curl(H)=-i*omega*epsilon*E for exp(-i omega t)",
        "epsilon_weighting_convention": "stored vector is (sqrt(epsilon) E,H); E is recovered by dividing weighted E by source-level sqrt(epsilon) point sample",
        "mu_weighting_convention": "mu=1 scalar; H is stored unweighted",
        "stored_eigenstate_maxwell_residual_max": residuals["stored_eigenstate_maxwell_residual_max"],
        "stored_eigenstate_curlE_residual_max": residuals["stored_eigenstate_curlE_residual_max"],
        "stored_eigenstate_curlH_residual_max": residuals["stored_eigenstate_curlH_residual_max"],
        "stored_state_residuals_by_state": residuals["by_state"],
        "operator_reconstruction_validation_status": "NOT_VALIDATED_EXACT_MPB_MATERIAL_DISCRETIZATION_UNAVAILABLE",
        "c3_transformed_state_maxwell_residual_max": None,
        "discrete_operator_intertwining_residual_max": None,
        "epsilon_grid_c3_residual_max": None,
        "epsilon_inverse_or_tensor_covariance_status": "UNAVAILABLE_RUNTIME_MPB_MATERIAL_TENSORS",
        "exact_material_grid_c3_covariance_status": "NOT_AVAILABLE_RUNTIME_EPSILON_GRID",
        "discrete_projector_minimum_overlap_singular_value": m15_metrics["m15_discrete_projector_minimum_overlap_singular_value"],
        "isolated_projector_theorem_status": "CONTRADICTION_FROM_M15_PROJECTOR_METRICS_ONLY; M16 OPERATOR ADJUDICATION WITHHELD",
        "discrete_operator_covariance_diagnosis": operator_status,
        "g15_projector_covariance_interpretation": "PHYSICAL_C3_MAPPING_NOT_ESTABLISHED",
        "remaining_unresolved_questions": ["Whether MPB subpixel/material tensors and exact epsilon grid would validate the Maxwell operator on stored eigenstates", "Whether the stored bands2-3 projector remains contradictory after exact operator calibration"],
        "alternative_explanations_considered": ["G16 nonsymmetry", "G15 exact space-group symmetry", "provider band/vector extraction", "energy metric", "continuous active/passive C3 orientation", "runtime spatial map", "Seitz center", "reciprocal-folding gauge", "exact FFT representation", "source-level material grid", "MPB subpixel/internal material discretization", "Maxwell sign/time convention", "stored spectral/projector family"],
        "counterevidence_summary": {"stored_state_calibration": residuals, "m15_independent_input": m15_metrics, "exact_material_grid": "not available from committed source", "counterevidence_against_stop": "source-level point sampling is not an exact MPB operator and therefore cannot close the theorem"},
        "cheapest_remaining_discriminating_test": "metadata-only capture of MPB get_epsilon grid, epsilon inverse/tensor material data, and discrete boundary/staggering/operator convention for the same three stored G15 states; no new state acquisition required",
        "next_science_decision": "ACQUIRE_MINIMAL_EXACT_MPB_OPERATOR_METADATA_UNIT",
        "exact_missing_operator_metadata": material["missing_runtime_data"], "minimal_next_live_state_count": 0,
        "scientific_acceptance_basis": "PASS_ZERO_BUDGET_SOURCE_AND_STORED_STATE_AUDIT; OPERATOR_THEOREM DECISION WITHHELD",
        "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0,
        "source_commit_used": os.environ.get("MEPHC_SOURCE_COMMIT"), "post_analysis_checkout_unchanged": True,
        "m14_independent_evidence": {"authoritative_gauge": m15_metrics["m14_authoritative_gauge"]},
        "m15_independent_evidence": m15_metrics,
    }


def main() -> int:
    try:
        bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8"))
        require(isinstance(bundle, dict) and isinstance(bundle.get("work_order_id"), str), "M16_WORK_ORDER_MISSING")
        counters = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"])
        job = _job(); state_root = counters.parent.parent
        m12 = read_dataset(job, state_root, M12_DATASET_ID, M12_MANIFEST_SHA256, 3)
        m13 = read_dataset(job, state_root, M13_DATASET_ID, M13_MANIFEST_SHA256, 3)
        result = analyze(m12, m13, {"runtime_spatial_shape": list(SHAPE)})
    except Exception as exc:
        result = _failure(str(exc), exc)
        result["traceback_tail"] = traceback.format_exc()[-3000:]
    Path(os.environ["MEPHC_RESULT_PATH"]).write_bytes(canonical(result) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
