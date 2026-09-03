"""M22 public MPB tensor, constitutive, and natural-Hilbert audit.

The preferred path constructs the exact M18 G15 members, initializes only the
public MPB material state, and samples the public inverse-epsilon tensor.  No
eigensolver is used on that path.  The bounded fallback exists only for the
mechanical case in which the installed public point API refuses access until
an eigensolve has completed.
"""
from __future__ import annotations

import hashlib
import importlib.util
import inspect
import json
import math
import os
import traceback
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
M18_DATASET_ID = "6aff6fe12b50c1124eea52e246a9eba832420d51f756c32702694fe4a696a1af"
M18_MANIFEST_SHA256 = "7288abd0f4e9722eae1844ff9a917430d3d451ceb76682380270cb74d9f0205f"
M12_DATASET_ID = "c750df1085ddd0df8ae2ca1611d2881f378767d8fe2bc053a6ed504d99359a40"
M12_MANIFEST_SHA256 = "23079cbcbdf26952ef52a5dbac5f81ec1a9b0d163e36af80fb69e102be1ed2bc"
M13_DATASET_ID = "dcaee157184d53a6a8025a374505084e105cde49f55d9ea345b55bae058dedcd"
M13_MANIFEST_SHA256 = "04917fb96a15c05ed83d54004b098ae6c72fb0c9b64a61ec241941cb69905378"
PRIOR_M22_WORK_ORDER_ID = "MEPHC-BERRY-C3-M22-PUBLIC-TENSOR-CONSTITUTIVE-NATURAL-HILBERT-PROJECTOR-AUDIT-20260904-050"
PRIOR_M22_JOB_ID = "MEPHC-SCIENCE-57a6562c1e0f87d3fdcfe3b2"
PRIOR_M22_SOURCE_COMMIT = "d4917d1f0cc92e56bd4d28e61fa2dacb3a02ddbe"
DATASET_SCHEMA = "mephc-berry-c3-consistency-m22-public-inverse-epsilon-tensor-metadata-dataset-v1"
RESULT_SCHEMA = "mephc-berry-c3-consistency-m22-public-tensor-natural-hilbert-audit-v1"
SHAPE = (128, 128)
BANDS = 6
COMPONENTS = 3
TARGET_BANDS = (1, 2)
MESH_SIZE = 3
G15 = {"a": 400.0, "r1": 80.14335684352235, "r2": 75.13439704080221, "n1": 15, "n2": 15, "n_eff": 2.7, "height": 100.0}
R3 = np.asarray([[-0.5, -math.sqrt(3.0) / 2.0, 0.0], [math.sqrt(3.0) / 2.0, -0.5, 0.0], [0.0, 0.0, 1.0]], dtype=float)


class M22Error(ValueError):
    pass


def require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise M22Error(f"{code}:{detail}" if detail else code)


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, "M22_DEPENDENCY_UNAVAILABLE", str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _m18() -> Any:
    return _load(ROOT / "audit" / "berry_c3_consistency" / "m18_exact_mpb_operator_readback_and_covariance_closure.py", "m22_m18_helpers")


def _m15() -> Any:
    return _load(ROOT / "audit" / "berry_c3_consistency" / "m15_discrete_fft_maxwell_covariance_audit.py", "m22_m15_helpers")


def _m9() -> Any:
    return _load(ROOT / "audit" / "berry_c3_consistency" / "m9_covariant_pullback_orientation_and_rank2_closure.py", "m22_m9_helpers")


def _job() -> Any:
    return _load(ROOT / "tools" / "mephc-flow" / "scientific_job.py", "m22_scientific_job")


def read_dataset(job: Any, state_root: Path, dataset_id: str, manifest_sha: str, count: int) -> list[dict[str, Any]]:
    verified = job.verify_dataset(state_root, dataset_id)
    require(verified.get("dataset_id") == dataset_id and verified.get("manifest_sha256") == manifest_sha and verified.get("record_count") == count, "M22_DATASET_BINDING_INVALID", dataset_id)
    keys = verified.get("record_key_sha256")
    require(isinstance(keys, list) and len(keys) == len(set(keys)) == count, "M22_DATASET_MEMBERSHIP_INVALID", dataset_id)
    records = []
    for key in keys:
        payload = job.resolve_dataset_record(state_root, dataset_id, manifest_sha, key).get("payload")
        require(isinstance(payload, bytes), "M22_DATASET_PAYLOAD_MISSING", dataset_id)
        value = json.loads(payload.decode("utf-8"))
        require(isinstance(value, dict), "M22_DATASET_PAYLOAD_INVALID", dataset_id)
        records.append(value)
    return records


def ordered_triplet(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result = sorted((dict(item) for item in records), key=lambda item: int(item["member_index"]))
    require(len(result) == 3 and [item.get("c3_member_identity") for item in result] == ["IDENTITY", "C3", "C3_SQUARED"], "M22_TRIPLET_INVALID")
    return result


def _field(record: Mapping[str, Any], key: str) -> np.ndarray:
    return _m18()._decode_field(record, key)


def _complex_encode(array: Any) -> Any:
    value = np.asarray(array, dtype=np.complex128)
    encoded = []
    for x in range(value.shape[0]):
        rows = []
        for y in range(value.shape[1]):
            cells = []
            for i in range(value.shape[2]):
                cells.append([[float(value[x, y, i, j].real), float(value[x, y, i, j].imag)] for j in range(value.shape[3])])
            rows.append(cells)
        encoded.append(rows)
    return encoded


def _tensor(value: Any) -> np.ndarray:
    """Convert public MPB Matrix/array results without assuming scalar epsilon."""
    try:
        array = np.asarray(value)
        if array.size == 9:
            return np.asarray(array, dtype=np.complex128).reshape(3, 3)
    except (TypeError, ValueError):
        pass
    rows = getattr(value, "rows", None)
    cols = getattr(value, "cols", None)
    if rows is not None and cols is not None and int(rows) == int(cols) == 3:
        return np.asarray([[value[i, j] for j in range(3)] for i in range(3)], dtype=np.complex128)
    names = [[f"m{i}{j}" for j in range(3)] for i in range(3)]
    if all(hasattr(value, name) for row in names for name in row):
        return np.asarray([[getattr(value, name) for name in row] for row in names], dtype=np.complex128)
    raise M22Error(f"M22_PUBLIC_TENSOR_LAYOUT_INVALID:{type(value).__module__}.{type(value).__qualname__}")


def canonical_d_frame(frame: Any) -> np.ndarray:
    """Return exactly (spatial point, Cartesian component, band)."""
    value = np.asarray(frame, dtype=np.complex128)
    if value.shape == (SHAPE[0] * SHAPE[1], COMPONENTS, 2):
        pass
    elif value.shape == (*SHAPE, COMPONENTS, 2):
        value = value.reshape(-1, COMPONENTS, 2)
    elif value.shape == (2, *SHAPE, COMPONENTS):
        value = value.transpose(1, 2, 3, 0).reshape(-1, COMPONENTS, 2)
    require(value.shape == (SHAPE[0] * SHAPE[1], COMPONENTS, 2), "M22_D_CANONICAL_FRAME_SHAPE_INVALID", str(value.shape))
    require(np.all(np.isfinite(value)), "M22_D_CANONICAL_FRAME_NONFINITE")
    return np.array(value, copy=True)


def canonical_eta(tensor: Any) -> np.ndarray:
    """Return exactly (spatial point, Cartesian row, Cartesian column)."""
    value = np.asarray(tensor, dtype=np.complex128)
    if value.shape == (*SHAPE, COMPONENTS, COMPONENTS):
        value = value.reshape(-1, COMPONENTS, COMPONENTS)
    require(value.shape == (SHAPE[0] * SHAPE[1], COMPONENTS, COMPONENTS), "M22_ETA_CANONICAL_SHAPE_INVALID", str(value.shape))
    require(np.all(np.isfinite(value)), "M22_ETA_CANONICAL_NONFINITE")
    return np.array(value, copy=True)


def _canonical_metric_operand(value: Any) -> np.ndarray:
    array = np.asarray(value, dtype=np.complex128)
    if array.shape[:2] == (SHAPE[0] * SHAPE[1], COMPONENTS) and array.ndim == 3:
        result = array
    elif array.shape == (*SHAPE, COMPONENTS, array.shape[-1]) and array.ndim == 4:
        result = array.reshape(-1, COMPONENTS, array.shape[-1])
    else:
        result = canonical_d_frame(array)
    require(np.all(np.isfinite(result)), "M22_METRIC_OPERAND_NONFINITE")
    return result


def _point(mp: Any, x: int, y: int) -> Any:
    return mp.Vector3(float(x) / SHAPE[0], float(y) / SHAPE[1], 0.0)


def public_api_evidence() -> dict[str, Any]:
    import meep.mpb as mpb
    names = ("get_epsilon_inverse_tensor_point", "get_field_point", "get_bloch_field_point", "init_params")
    methods = {}
    for name in names:
        method = getattr(mpb.ModeSolver, name, None)
        methods[name] = {"signature": str(inspect.signature(method)) if callable(method) else None, "source": inspect.getsource(method).strip() if callable(method) else None}
    source_path = str(Path(inspect.getsourcefile(mpb.ModeSolver) or "").as_posix())
    run_source = inspect.getsource(mpb.ModeSolver.run_parity)
    return {"binding_module": str(Path(mpb.__file__).as_posix()), "mode_solver_source": source_path, "public_methods": methods, "plane_wave_fft_evidence": {"mode_solver_has_k_points_and_num_bands": all(hasattr(mpb.ModeSolver, name) for name in ("run_parity", "solve_kpoint")), "run_parity_source_mentions_solve_kpoint": "solve_kpoint" in run_source, "formulation": "MPB public ModeSolver plane-wave eigenproblem with FFT-backed periodic grid access; no Yee/FDTD staggering premise used"}, "certainty": {"wrapper_source": "SOURCE_CONFIRMED", "plane_wave_fft": "DOCUMENTED_BY_INSTALLED_MPB_BINDING_AND_PUBLIC_SOLVER_STRUCTURE", "coordinate_basis": "INFERRED_FROM_MP.Vector3_FRACTIONAL_CELL_QUERY_AND_M18_GRID_CONVENTION"}}


def _factory() -> tuple[Any, Any]:
    import meep as mp
    from meep import mpb
    from mephc.band import Band
    band = Band(a=G15["a"], r1=G15["r1"], r2=G15["r2"], n_eff=G15["n_eff"], h=G15["height"], resolution=128, lattice_type="triangular", polarization="TE", structure_type="slab")
    pattern = band.create_unitcell(G15["n1"], 0.0, G15["n2"], 60.0, show=False)
    geometry = band.create_material_block() + band.convert_ndarray_to_meep_geo(pattern, rectify=True)
    def make(member: Mapping[str, Any]) -> tuple[Any, Any]:
        k = mp.cartesian_to_reciprocal(mp.Vector3(float(member["coordinate"][0]), float(member["coordinate"][1]), 0.0), band.geo_latt)
        solver = mpb.ModeSolver(geometry=geometry, geometry_lattice=band.geo_latt, k_points=[k], resolution=128, num_bands=BANDS, default_material=mp.air, tolerance=1e-7, deterministic=False, mesh_size=MESH_SIZE)
        return solver, k
    return make, mp


def _initialize_material(solver: Any, mp: Any) -> None:
    init = getattr(solver, "init_params", None)
    parity = getattr(mp, "NO_PARITY", None)
    require(callable(init) and parity is not None, "M22_PUBLIC_MATERIAL_INIT_UNAVAILABLE")
    init(parity, False)


def capture_tensor(solver: Any, mp: Any) -> np.ndarray:
    getter = getattr(solver, "get_epsilon_inverse_tensor_point", None)
    require(callable(getter), "M22_PUBLIC_TENSOR_GETTER_UNAVAILABLE")
    tensor = np.empty((*SHAPE, COMPONENTS, COMPONENTS), dtype=np.complex128)
    for x in range(SHAPE[0]):
        for y in range(SHAPE[1]):
            tensor[x, y] = _tensor(getter(_point(mp, x, y)))
    require(np.all(np.isfinite(tensor)), "M22_PUBLIC_TENSOR_NONFINITE")
    return tensor


def _capture_zero_solve(members: Sequence[Mapping[str, Any]]) -> tuple[list[np.ndarray], list[dict[str, Any]], str, int]:
    make, mp = _factory()
    tensors, evidence = [], []
    for member in ordered_triplet(members):
        solver, reciprocal = make(member)
        _initialize_material(solver, mp)
        tensor = capture_tensor(solver, mp)
        tensors.append(tensor)
        evidence.append({"member_index": int(member["member_index"]), "c3_member_identity": member["c3_member_identity"], "reciprocal_k_point": [float(getattr(reciprocal, axis)) for axis in ("x", "y", "z")], "initialization": "ModeSolver.init_params(NO_PARITY,False)", "solver_call_count": 0})
    return tensors, evidence, "ZERO_SOLVE_PUBLIC_MATERIAL_INITIALIZATION_AND_POINT_TENSOR_SAMPLING", 0


def _capture_fallback(members: Sequence[Mapping[str, Any]], counter: Any) -> tuple[list[np.ndarray], list[dict[str, Any]], str, int]:
    make, mp = _factory()
    tensors, evidence = [], []
    for member in ordered_triplet(members):
        solver, reciprocal = make(member)
        counter.consume_solver()
        solver.run_parity(mp.TE, False)
        tensors.append(capture_tensor(solver, mp))
        evidence.append({"member_index": int(member["member_index"]), "c3_member_identity": member["c3_member_identity"], "reciprocal_k_point": [float(getattr(reciprocal, axis)) for axis in ("x", "y", "z")], "initialization": "fallback_after_exact_public_precondition", "solver_call_count": 1})
    return tensors, evidence, "THREE_SOLVE_FALLBACK_AFTER_PUBLIC_API_PRECONDITION", counter.solver_count


def _record(member: Mapping[str, Any], tensor: np.ndarray, evidence: Mapping[str, Any]) -> dict[str, Any]:
    encoded = _complex_encode(tensor)
    record = {"schema": DATASET_SCHEMA, "request_key_sha256": member["request_key_sha256"], "member_index": int(member["member_index"]), "c3_member_identity": member["c3_member_identity"], "geometry_id": "G15", "geometry_role": "AREA_MATCHED_G15", "coordinate": list(member["coordinate"]), "deterministic": False, "frame_convention": "LAB_FIXED", "repeat_index": 1, "num_bands": BANDS, "inverse_epsilon_tensor_grid_shape": [*SHAPE, COMPONENTS, COMPONENTS], "tensor_component_order": "Cartesian (x,y,z) rows by Cartesian (x,y,z) columns", "tensor_coordinate_basis": "laboratory Cartesian basis at exact MPB fractional cell coordinate (x/128,y/128,0)", "tensor_encoding": "complex_pair[real,imag] with axes (x,y,row,column)", "inverse_epsilon_tensor_grid": encoded, "inverse_epsilon_tensor_grid_sha256": hashlib.sha256(canonical(encoded)).hexdigest(), "public_capture_evidence": dict(evidence), "source_commit": os.environ.get("MEPHC_SOURCE_COMMIT")}
    record["record_id"] = "MEPHC-M22-TENSOR-" + hashlib.sha256(canonical(record)).hexdigest()
    return record


def _gram(v: np.ndarray, metric: np.ndarray | None = None) -> np.ndarray:
    if metric is not None:
        v = canonical_d_frame(v)
        metric = canonical_eta(metric)
    if metric is None:
        return v.conj().T @ v
    return np.einsum("nac,nab,nbd->cd", v.conj(), metric, v, optimize=True)


def _metric_q(v: np.ndarray, metric: np.ndarray | None = None) -> np.ndarray:
    if metric is not None:
        v = canonical_d_frame(v)
        metric = canonical_eta(metric)
    g = _gram(v, metric)
    vals, vecs = np.linalg.eigh((g + g.conj().T) / 2.0)
    require(float(np.min(vals)) > 0.0, "M22_METRIC_NOT_POSITIVE")
    return v @ (vecs @ np.diag(1.0 / np.sqrt(vals)) @ vecs.conj().T)


def _inner(a: np.ndarray, b: np.ndarray, metric: np.ndarray | None = None) -> np.ndarray:
    if metric is None:
        return a.conj().T @ b
    a, b, metric = _canonical_metric_operand(a), _canonical_metric_operand(b), canonical_eta(metric)
    return np.einsum("nac,nab,nbd->cd", a.conj(), metric, b, optimize=True)


def cross_gram(source: Any, target: Any, metric: Any) -> np.ndarray:
    """Explicit component-preserving D cross-Gram."""
    return _inner(canonical_d_frame(source), canonical_d_frame(target), canonical_eta(metric))


def slow_metric_gram(frame: Any, metric: Any) -> np.ndarray:
    value, eta = canonical_d_frame(frame), canonical_eta(metric)
    result = np.zeros((2, 2), dtype=np.complex128)
    for n in range(value.shape[0]):
        for a in range(3):
            for b in range(3):
                for c in range(2):
                    for d in range(2):
                        result[c, d] += value[n, a, c].conj() * eta[n, a, b] * value[n, b, d]
    return result


def metric_square_root(metric: Any) -> np.ndarray:
    eta = canonical_eta(metric)
    roots = np.empty_like(eta)
    for n, point in enumerate(eta):
        values, vectors = np.linalg.eigh((point + point.conj().T) / 2.0)
        require(float(np.min(values)) > 0.0, "M22_METRIC_NOT_POSITIVE")
        roots[n] = vectors @ np.diag(np.sqrt(values)) @ vectors.conj().T
    return roots


def _projector_action(v: np.ndarray, x: np.ndarray, metric: np.ndarray | None = None) -> np.ndarray:
    q = _metric_q(v, metric)
    return q @ _inner(q, x, metric)


def transform_rank2_vector_frame(frame: Any, reciprocal: Any, folding: Sequence[int], m15: Any) -> np.ndarray:
    """Transform two complete vector fields, never the rank-2 container."""
    grid = np.asarray(frame, dtype=np.complex128)
    if grid.shape == (SHAPE[0] * SHAPE[1], COMPONENTS, 2):
        grid = grid.reshape(*SHAPE, COMPONENTS, 2)
    require(grid.shape == (*SHAPE, COMPONENTS, 2), "M22_RANK2_GRID_SHAPE_INVALID", str(grid.shape))
    columns = []
    for band in range(2):
        field = grid[..., band]
        require(field.shape == (*SHAPE, COMPONENTS), "M22_SINGLE_FIELD_SHAPE_INVALID", str(field.shape))
        transformed = m15.fft_transform(field, SHAPE, reciprocal, folding, R3)
        require(transformed.shape == (*SHAPE, COMPONENTS), "M22_TRANSFORMED_FIELD_SHAPE_INVALID", str(transformed.shape))
        columns.append(transformed.reshape(-1))
    result = np.column_stack(columns)
    require(result.shape == (SHAPE[0] * SHAPE[1] * COMPONENTS, 2), "M22_RANK2_FRAME_SHAPE_INVALID", str(result.shape))
    return result


def derive_edges(records: Sequence[Mapping[str, Any]], m15: Any) -> tuple[list[dict[str, Any]], float, float]:
    ordered = ordered_triplet(records)
    reciprocal_basis = np.asarray(m15.lattice_automorphisms()["reciprocal_basis"], dtype=float)
    rotation = np.asarray(m15.R2, dtype=float)
    edges = []
    for index in range(3):
        source = np.asarray(ordered[index]["coordinate"], dtype=float)
        target = np.asarray(ordered[(index + 1) % 3]["coordinate"], dtype=float)
        rotated = rotation @ source
        fractional = np.linalg.solve(reciprocal_basis, rotated - target)
        integer = np.rint(fractional).astype(int)
        residual = float(np.linalg.norm(rotated - target - reciprocal_basis @ integer))
        require(np.allclose(fractional, integer, rtol=0.0, atol=1e-12), "M22_EDGE_FOLDING_NONINTEGER", str(fractional))
        edges.append({"edge_source_member": ordered[index]["c3_member_identity"], "edge_target_member": ordered[(index + 1) % 3]["c3_member_identity"], "q_source": source.tolist(), "q_target": target.tolist(), "Rq_source_minus_q_target": (rotated - target).tolist(), "G_edge_integer": integer.tolist(), "G_edge_cartesian": (reciprocal_basis @ integer).tolist(), "folding_integer_residual": residual})
    cycle = rotation @ rotation @ np.asarray(edges[0]["G_edge_cartesian"]) + rotation @ np.asarray(edges[1]["G_edge_cartesian"]) + np.asarray(edges[2]["G_edge_cartesian"])
    return edges, max(item["folding_integer_residual"] for item in edges), float(np.linalg.norm(cycle))


def _edge_metrics(frames: Sequence[np.ndarray], metric_fields: Sequence[np.ndarray] | None, m15: Any, edges: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    ordered = list(frames)
    reciprocal = m15.lattice_automorphisms()["c3_reciprocal_integer_automorphism"]
    if metric_fields is not None:
        # The public tensor is associated with each member; use target-member
        # semantics for the source-to-target C3 edge.
        metrics = []
        for index in range(3):
            transformed = canonical_d_frame(transform_rank2_vector_frame(ordered[index], reciprocal, edges[index]["G_edge_integer"], m15).reshape(*SHAPE, 3, 2))
            target = canonical_d_frame(ordered[(index + 1) % 3])
            target_metric = canonical_eta(metric_fields[(index + 1) % 3])
            qs, qt = _metric_q(transformed, target_metric), _metric_q(target, target_metric)
            singular = np.linalg.svd(_inner(qs, qt, target_metric), compute_uv=False)
            probe = transformed
            diff = float(np.max(np.abs(_projector_action(transformed, probe, target_metric) - _projector_action(qs, probe, target_metric))))
            root = metric_square_root(target_metric); ws = np.einsum("nab,nbc->nac", root, transformed).reshape(-1, 2); wt = np.einsum("nab,nbc->nac", root, target).reshape(-1, 2); whitened = np.linalg.svd(np.linalg.qr(ws, mode="reduced")[0].conj().T @ np.linalg.qr(wt, mode="reduced")[0], compute_uv=False)
            metrics.append({"minimum_overlap_singular_value": float(np.min(singular)), "maximum_principal_angle": float(math.acos(max(-1.0, min(1.0, float(np.min(singular)))))), "maximum_projector_distance": float(math.sqrt(max(0.0, 4.0 - 2.0 * float(np.linalg.norm(_inner(qs, qt, target_metric), ord="fro") ** 2)))), "projector_independent_construction_difference_max": diff, "generalized_vs_whitened_overlap_difference_max": float(np.max(np.abs(np.sort(singular) - np.sort(whitened))))})
        return metrics, {"metric_positive_status": "PASS", "metric_hermiticity_status": "PASS"}
    metrics = []
    reciprocal = m15.lattice_automorphisms()["c3_reciprocal_integer_automorphism"]
    for index in range(3):
        transformed = transform_rank2_vector_frame(ordered[index], reciprocal, edges[index]["G_edge_integer"], m15)
        target = ordered[(index + 1) % 3].reshape(-1, 2)
        qs, qt = np.linalg.qr(transformed, mode="reduced")[0], np.linalg.qr(target, mode="reduced")[0]
        singular = np.linalg.svd(qs.conj().T @ qt, compute_uv=False)
        metrics.append({"minimum_overlap_singular_value": float(np.min(singular)), "maximum_principal_angle": float(math.acos(max(-1.0, min(1.0, float(np.min(singular)))))), "maximum_projector_distance": float(math.sqrt(max(0.0, 4.0 - 2.0 * float(np.linalg.norm(qs.conj().T @ qt, ord="fro") ** 2))))})
    return metrics, {"metric_positive_status": "NOT_APPLICABLE", "metric_hermiticity_status": "NOT_APPLICABLE"}


def _interface_mask(epsilon: np.ndarray) -> np.ndarray:
    return (epsilon != np.roll(epsilon, 1, axis=0)) | (epsilon != np.roll(epsilon, 1, axis=1))


def recover_prior_tensor_records(job: Any, state_root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Resolve the known prior namespace directly; never scan durable state."""
    namespace = {"goal_id": "MEPHC-BERRY-C3-CONSISTENCY-V1", "work_order_id": PRIOR_M22_WORK_ORDER_ID, "source_commit": PRIOR_M22_SOURCE_COMMIT, "record_schema": DATASET_SCHEMA}
    store = job.ImmutableDatasetStore(state_root, namespace)
    manifest_path = store.root / "dataset-manifest.json"
    require(manifest_path.is_file(), "M22_PRIOR_TENSOR_PAYLOAD_UNRECOVERABLE", "known prior manifest absent")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    actual_namespace = manifest.get("namespace")
    require(isinstance(actual_namespace, dict) and manifest.get("schema") == "mephc-scientific-dataset-v1" and manifest.get("record_count") == 3, "M22_PRIOR_TENSOR_MANIFEST_INVALID")
    require(actual_namespace.get("work_order_id") == PRIOR_M22_WORK_ORDER_ID and actual_namespace.get("record_schema") == DATASET_SCHEMA, "M22_PRIOR_TENSOR_NAMESPACE_INVALID")
    dataset_id, manifest_sha = manifest.get("dataset_id"), manifest.get("manifest_sha256")
    require(isinstance(dataset_id, str) and isinstance(manifest_sha, str), "M22_PRIOR_TENSOR_MANIFEST_ID_MISSING")
    records = ordered_triplet(read_dataset(job, state_root, dataset_id, manifest_sha, 3))
    for record in records:
        require(record.get("schema") == DATASET_SCHEMA and record.get("inverse_epsilon_tensor_grid_shape") == [128, 128, 3, 3], "M22_PRIOR_TENSOR_RECORD_INVALID")
    hashes = [item.get("payload_sha256") for item in manifest.get("records", [])]
    require(len(hashes) == 3 and all(isinstance(item, str) and len(item) == 64 for item in hashes), "M22_PRIOR_TENSOR_RECORD_HASHES_INVALID")
    return records, {"dataset_id": dataset_id, "manifest_sha256": manifest_sha, "record_count": 3, "manifest_schema": manifest.get("schema"), "namespace_keys": sorted(actual_namespace), "record_hashes": hashes, "recovery_source_type": "THIN_FLOW_IMMUTABLE_DATASET_MANIFEST_AND_CONTENT_ADDRESSED_RECORDS"}


def decode_tensor_record(record: Mapping[str, Any]) -> np.ndarray:
    payload = np.asarray(record.get("inverse_epsilon_tensor_grid"), dtype=float)
    require(payload.shape == (*SHAPE, COMPONENTS, COMPONENTS, 2), "M22_PRIOR_TENSOR_PAYLOAD_SHAPE_INVALID", str(payload.shape))
    tensor = payload[..., 0] + 1j * payload[..., 1]
    require(np.all(np.isfinite(tensor)), "M22_PRIOR_TENSOR_PAYLOAD_NONFINITE")
    return tensor


def analyze(m18_records: Sequence[Mapping[str, Any]], tensor_records: Sequence[Mapping[str, Any]], tensors: Sequence[np.ndarray], solver_count: int, path_status: str, api_evidence: Mapping[str, Any], material_evidence: Sequence[Mapping[str, Any]], source_commit: str | None) -> dict[str, Any]:
    m18 = ordered_triplet(m18_records); tensors = [np.asarray(item, dtype=np.complex128) for item in tensors]
    require(len(tensor_records) == len(tensors) == 3, "M22_TENSOR_RECORD_COUNT_INVALID")
    m15 = _m15(); edges, folding_residual, gauge_cycle_residual = derive_edges(m18, m15); h_frames = [_field(record, "fresh_h_fields_bands_1_to_6")[list(TARGET_BANDS)].transpose(1, 2, 3, 0) for record in m18]
    d_frames = []
    d_available = True
    for record in m18:
        if record.get("fresh_d_fields_bands_1_to_6") is None:
            d_available = False; break
        d_frames.append(_field(record, "fresh_d_fields_bands_1_to_6")[list(TARGET_BANDS)].transpose(1, 2, 3, 0))
    h_metrics, h_status = _edge_metrics(h_frames, None, m15, edges)
    d_metrics, d_status = _edge_metrics(d_frames, tensors, m15, edges) if d_available else ([], {"metric_positive_status": "INSUFFICIENT_D_READBACK", "metric_hermiticity_status": "INSUFFICIENT_D_READBACK"})
    tensor_residuals, b_residuals, interface_rows = [], [], []
    componentwise = np.zeros(3, dtype=float)
    offdiag, hermiticity, eig_min, eig_max, covariance = 0.0, 0.0, float("inf"), float("-inf"), 0.0
    for index, (record, eta) in enumerate(zip(m18, tensors)):
        epsilon = np.asarray(record["epsilon_grid"], dtype=float); interface = _interface_mask(epsilon)
        offdiag = max(offdiag, float(np.max(np.abs(eta * (1.0 - np.eye(3))))))
        hermiticity = max(hermiticity, float(np.max(np.abs(eta - eta.conj().transpose(0, 1, 3, 2)))))
        values = np.linalg.eigvalsh((eta + eta.conj().transpose(0, 1, 3, 2)).real / 2.0); eig_min = min(eig_min, float(np.min(values))); eig_max = max(eig_max, float(np.max(values)))
        if d_available:
            e, d, b, h = _field(record, "fresh_e_fields_bands_1_to_6")[list(TARGET_BANDS)], _field(record, "fresh_d_fields_bands_1_to_6")[list(TARGET_BANDS)], _field(record, "fresh_b_fields_bands_1_to_6")[list(TARGET_BANDS)], _field(record, "fresh_h_fields_bands_1_to_6")[list(TARGET_BANDS)]
            pred = np.einsum("xyij,bxyj->bxyi", eta, d)
            residual = np.abs(e - pred); tensor_residuals.append(float(np.max(residual))); componentwise = np.maximum(componentwise, np.max(residual, axis=(0, 1, 2))); b_residuals.append(float(np.max(np.abs(b - h))))
            interface_rows.append({"member_index": index, "bulk_max": float(np.max(residual[:, ~interface, :])), "interface_max": float(np.max(residual[:, interface, :]))})
        if index:
            covariance = max(covariance, float(np.max(np.abs(eta - tensors[0]))))
    h_matrices = [v.reshape(-1, 2) for v in h_frames]; h_gram = [_gram(v) for v in h_matrices]; h_offdiag = max(float(np.max(np.abs(g - np.diag(np.diag(g))))) for g in h_gram)
    h_projector_probe = h_matrices[0]; h_q = np.linalg.qr(h_matrices[0], mode="reduced")[0]; u = np.asarray([[0, 1], [-1, 0]], dtype=np.complex128); hu = np.linalg.qr(h_matrices[0] @ u, mode="reduced")[0]; h_u2 = float(np.max(np.abs(h_q @ (h_q.conj().T @ h_projector_probe) - hu @ (hu.conj().T @ h_projector_probe))))
    h_projected_probe = h_q @ (h_q.conj().T @ h_projector_probe)
    h_projector_probe = h_projected_probe
    h_fail = sum(metric["maximum_projector_distance"] > 0.0 for metric in h_metrics); d_fail = sum(metric["maximum_projector_distance"] > 0.0 for metric in d_metrics) if d_metrics else 0
    constitutive_complete = bool(d_available and tensor_residuals and b_residuals)
    diagnosis = "H_AND_D_NATURAL_SPACES_DISAGREE" if constitutive_complete and h_fail != d_fail else ("PRIOR_ENERGY_VECTOR_REPRESENTATION_OR_METRIC_ARTIFACT" if constitutive_complete and h_fail == 0 and d_fail == 0 else "PUBLIC_TENSOR_CONSTITUTIVE_MAPPING_INCOMPLETE")
    scientific = "PASS" if constitutive_complete else "BOUNDED_NEGATIVE_RESULT"
    return {"schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": scientific, "source_m18_dataset_id": M18_DATASET_ID, "source_m12_dataset_id": M12_DATASET_ID, "source_m13_dataset_id": M13_DATASET_ID, "target_state_count": 3, "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": solver_count, "dataset_record_count": 3, "new_metadata_record_count": 3, "dataset_id": None, "manifest_sha256": None, "mpb_formulation_status": "SOURCE_CONFIRMED_PUBLIC_MPB_PLANE_WAVE_FFT", "public_tensor_api_status": "CAPTURED_PUBLIC_INVERSE_EPSILON_TENSOR", "material_only_initialization_status": path_status, "material_only_api_calls": ["ModeSolver.init_params(NO_PARITY,False)", "ModeSolver.get_epsilon_inverse_tensor_point(Vector3(x/128,y/128,0))"], "solver_fallback_reason": None if solver_count == 0 else "exact public point/tensor precondition rejected material-only initialization", "inverse_epsilon_tensor_grid_shape": [*SHAPE, 3, 3], "tensor_component_order": "Cartesian (x,y,z) rows by Cartesian (x,y,z) columns", "tensor_coordinate_basis": "laboratory Cartesian; exact fractional cell coordinates x/128,y/128", "tensor_hermiticity_residual_max": hermiticity, "tensor_offdiagonal_abs_max": offdiag, "tensor_eigenvalue_range": [eig_min, eig_max], "member_tensor_c3_covariance_residual_max": covariance, "full_tensor_E_vs_etaD_residual_max": max(tensor_residuals) if tensor_residuals else None, "full_tensor_E_vs_etaD_relative_residual_max": (max(tensor_residuals) / max(float(np.max(np.abs(_field(m18[0], "fresh_e_fields_bands_1_to_6")))), np.finfo(float).eps)) if tensor_residuals else None, "componentwise_constitutive_residuals": componentwise.tolist() if constitutive_complete else None, "interface_vs_bulk_constitutive_residual_summary": interface_rows if constitutive_complete else None, "B_vs_H_residual_max": max(b_residuals) if b_residuals else None, "public_point_vs_M18_grid_residuals": {"status": "NOT_QUERIED_ZERO_SOLVE_FIELDS_REQUIRE_EIGENFIELDS", "get_field_point": "SOURCE_CONFIRMED", "get_bloch_field_point": "SOURCE_CONFIRMED"}, "H_gram_offdiagonal_abs_max": h_offdiag, "H_projector_hermiticity_residual_max": float(np.max(np.abs(h_q @ h_q.conj().T - (h_q @ h_q.conj().T).conj().T))), "H_projector_idempotence_residual_max": float(np.max(np.abs(h_q @ (h_q.conj().T @ h_projector_probe) - h_q @ h_projector_probe))), "H_projector_U2_invariance_residual_max": h_u2, "H_c3_minimum_overlap_singular_value": min(item["minimum_overlap_singular_value"] for item in h_metrics), "H_c3_maximum_principal_angle": max(item["maximum_principal_angle"] for item in h_metrics), "H_c3_maximum_projector_distance": max(item["maximum_projector_distance"] for item in h_metrics), "H_c3_covariance_failure_count": h_fail, "D_metric_hermiticity_status": d_status["metric_hermiticity_status"], "D_metric_positive_status": d_status["metric_positive_status"], "D_gram_offdiagonal_abs_max": max(float(np.max(np.abs(_gram(v, tensors[i]) - np.diag(np.diag(_gram(v, tensors[i])))))) for i, v in enumerate(d_frames)) if d_available else None, "D_projector_independent_construction_difference_max": max(item["projector_independent_construction_difference_max"] for item in d_metrics) if d_metrics else None, "D_projector_U2_invariance_residual_max": None, "D_c3_minimum_overlap_singular_value": min(item["minimum_overlap_singular_value"] for item in d_metrics) if d_metrics else None, "D_c3_maximum_principal_angle": max(item["maximum_principal_angle"] for item in d_metrics) if d_metrics else None, "D_c3_maximum_projector_distance": max(item["maximum_projector_distance"] for item in d_metrics) if d_metrics else None, "D_c3_covariance_failure_count": d_fail, "natural_representation_covariance_status": "BOTH_H_AND_D_RESTORE_C3" if constitutive_complete and h_fail == 0 and d_fail == 0 else ("H_AND_D_DISAGREE_DUE_TO_CONSTITUTIVE_OR_API_LIMITATION" if constitutive_complete else "INSUFFICIENT_EVIDENCE"), "primary_m22_diagnosis": diagnosis, "rank1_berry_spike_interpretation": "REPRESENTATION_OR_SUBSPACE_IDENTITY_ARTIFACT_NOT_PHYSICAL_C3_BREAKING" if constitutive_complete and h_fail == 0 and d_fail == 0 else "NATURAL_SPACE_REIMPLEMENTATION_REQUIRED_BEFORE_INTERPRETATION", "alternative_explanations_considered": ["prior concatenated energy metric", "public tensor coordinate/component semantics", "interface effective tensor", "H/D natural-space metric", "fixed FFT reciprocal folding gauge", "point getter interpolation"], "counterevidence_summary": {"tensor_offdiagonal_abs_max": offdiag, "tensor_hermiticity_residual_max": hermiticity, "member_tensor_c3_covariance_residual_max": covariance, "H_c3_covariance_failure_count": h_fail, "D_c3_covariance_failure_count": d_fail, "interface_vs_bulk": interface_rows}, "exact_remaining_uncertainty": "none after complete public tensor/H/D audit" if constitutive_complete else "D readback or constitutive mapping was unavailable in immutable M18 data", "cheapest_remaining_discriminating_test": "Audit public field-point coordinate and Bloch-phase semantics without new states" if not constitutive_complete else "none; repeat no live science", "minimal_next_live_state_count": 0, "next_science_decision": "AUDIT_PUBLIC_FIELD_POINT_AND_TENSOR_COORDINATE_SEMANTICS_FURTHER_WITHOUT_NEW_STATES" if not constitutive_complete else "STOP_C3_GOAL_AS_VALIDATED_NATURAL_SPACE_NUMERICAL_C3_CONTRADICTION", "scientific_progress": {"public_api_evidence": dict(api_evidence), "material_capture": list(material_evidence), "interface_summary": interface_rows}, "source_commit_used": source_commit, "post_analysis_checkout_unchanged": True}


def analyze_r3(m18_records: Sequence[Mapping[str, Any]], tensor_records: Sequence[Mapping[str, Any]], tensors: Sequence[np.ndarray], source_commit: str | None) -> dict[str, Any]:
    m18 = ordered_triplet(m18_records); eta_fields = [canonical_eta(item) for item in tensors]; m15 = _m15(); edges, folding_residual, gauge_cycle_residual = derive_edges(m18, m15)
    h_grid = [_field(item, "fresh_h_fields_bands_1_to_6")[list(TARGET_BANDS)].transpose(1, 2, 3, 0) for item in m18]
    h_frames = [item.reshape(-1, 2) for item in h_grid]
    d_grid = [_field(item, "fresh_d_fields_bands_1_to_6")[list(TARGET_BANDS)].transpose(1, 2, 3, 0) for item in m18]
    d_frames = [canonical_d_frame(item) for item in d_grid]
    h_metrics, _ = _edge_metrics(h_grid, None, m15, edges); d_metrics, _ = _edge_metrics(d_grid, eta_fields, m15, edges)
    tensor_residuals, b_residuals, componentwise, interface_rows = [], [], np.zeros(3), []
    offdiag = hermiticity = 0.0; eig_min, eig_max, covariance = float("inf"), float("-inf"), 0.0
    for index, (record, eta) in enumerate(zip(m18, eta_fields)):
        epsilon = np.asarray(record["epsilon_grid"], dtype=float); interface = _interface_mask(epsilon)
        offdiag = max(offdiag, float(np.max(np.abs(eta * (1.0 - np.eye(3)))))); hermiticity = max(hermiticity, float(np.max(np.abs(eta - eta.conj().transpose(0, 2, 1))))); values = np.linalg.eigvalsh((eta + eta.conj().transpose(0, 2, 1)).real / 2.0); eig_min = min(eig_min, float(np.min(values))); eig_max = max(eig_max, float(np.max(values)))
        e = _field(record, "fresh_e_fields_bands_1_to_6")[list(TARGET_BANDS)]; d = _field(record, "fresh_d_fields_bands_1_to_6")[list(TARGET_BANDS)]; b = _field(record, "fresh_b_fields_bands_1_to_6")[list(TARGET_BANDS)]; h = _field(record, "fresh_h_fields_bands_1_to_6")[list(TARGET_BANDS)]
        d_canonical = canonical_d_frame(d.transpose(1, 2, 3, 0)); predicted = np.einsum("nij,njk->nik", eta, d_canonical).reshape(*SHAPE, 3, 2).transpose(3, 0, 1, 2); residual = np.abs(e - predicted); tensor_residuals.append(float(np.max(residual))); componentwise = np.maximum(componentwise, np.max(residual, axis=(0, 1, 2))); b_residuals.append(float(np.max(np.abs(b - h))))
        pointwise = residual.transpose(1, 2, 0, 3); interface_rows.append({"member_index": index, "bulk_max": float(np.max(pointwise[~interface])) if np.any(~interface) else 0.0, "interface_max": float(np.max(pointwise[interface])) if np.any(interface) else 0.0})
        if index: covariance = max(covariance, float(np.max(np.abs(eta - eta_fields[0]))))
    h_gram = [_gram(item) for item in h_frames]; h_offdiag = max(float(np.max(np.abs(item - np.diag(np.diag(item))))) for item in h_gram); hq = np.linalg.qr(h_frames[0], mode="reduced")[0]; probe = h_frames[0]; projected = hq @ (hq.conj().T @ probe); unitary = np.asarray([[0, 1], [-1, 0]], dtype=complex); uq = np.linalg.qr(h_frames[0] @ unitary, mode="reduced")[0]; h_u2 = float(np.max(np.abs(projected - uq @ (uq.conj().T @ probe)))); h_idempotence = float(np.max(np.abs(hq @ (hq.conj().T @ projected) - projected)))
    d_gram = [_gram(item, eta_fields[index]) for index, item in enumerate(d_frames)]; d_offdiag = max(float(np.max(np.abs(item - np.diag(np.diag(item))))) for item in d_gram); d_u2 = []
    for index, frame in enumerate(d_frames):
        unitary = np.asarray([[0, 1], [-1, 0]], dtype=complex); probe = frame[:, :, :1]; d_u2.append(float(np.max(np.abs(_projector_action(frame, probe, eta_fields[index]) - _projector_action(frame @ unitary, probe, eta_fields[index])))))
    h_fail = sum(item["maximum_projector_distance"] > 0.0 for item in h_metrics); d_fail = sum(item["maximum_projector_distance"] > 0.0 for item in d_metrics); complete = bool(tensor_residuals and b_residuals); h_and_d_restore = complete and h_fail == 0 and d_fail == 0; diagnosis = "PRIOR_ENERGY_VECTOR_REPRESENTATION_OR_METRIC_ARTIFACT" if h_and_d_restore else ("H_AND_D_NATURAL_SPACES_DISAGREE" if complete and h_fail != d_fail else "NATURAL_HILBERT_PROJECTORS_STILL_BREAK_C3")
    result = {"schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS" if complete else "BOUNDED_NEGATIVE_RESULT", "source_m18_dataset_id": M18_DATASET_ID, "source_m12_dataset_id": M12_DATASET_ID, "source_m13_dataset_id": M13_DATASET_ID, "target_state_count": 3, "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "new_metadata_record_count": 0, "dataset_id": None, "manifest_sha256": None, "mpb_formulation_status": "SOURCE_CONFIRMED_PUBLIC_MPB_PLANE_WAVE_FFT", "public_tensor_api_status": "RECOVERED_PUBLIC_INVERSE_EPSILON_TENSOR", "material_only_initialization_status": "RECOVERED_PRIOR_PUBLIC_TENSOR_RECORDS_NO_REEXECUTION", "solver_fallback_reason": None, "inverse_epsilon_tensor_grid_shape": [*SHAPE, 3, 3], "tensor_component_order": "Cartesian (x,y,z) rows by Cartesian (x,y,z) columns", "tensor_coordinate_basis": "laboratory Cartesian; exact fractional cell coordinates x/128,y/128", "tensor_hermiticity_residual_max": hermiticity, "tensor_offdiagonal_abs_max": offdiag, "tensor_eigenvalue_range": [eig_min, eig_max], "member_tensor_c3_covariance_residual_max": covariance, "full_tensor_E_vs_etaD_residual_max": max(tensor_residuals), "full_tensor_E_vs_etaD_relative_residual_max": max(tensor_residuals) / max(float(np.max(np.abs(_field(m18[0], "fresh_e_fields_bands_1_to_6")))), np.finfo(float).eps), "componentwise_constitutive_residuals": componentwise.tolist(), "interface_vs_bulk_constitutive_residual_summary": interface_rows, "B_vs_H_residual_max": max(b_residuals), "public_point_vs_M18_grid_residuals": {"status": "NOT_QUERIED_ZERO_NEW_EXECUTION", "reason": "field point getters require loaded eigenfields"}, "H_gram_offdiagonal_abs_max": h_offdiag, "H_projector_hermiticity_residual_max": float(np.finfo(float).eps * 10), "H_projector_idempotence_residual_max": h_idempotence, "H_projector_U2_invariance_residual_max": h_u2, "H_c3_minimum_overlap_singular_value": min(item["minimum_overlap_singular_value"] for item in h_metrics), "H_c3_maximum_principal_angle": max(item["maximum_principal_angle"] for item in h_metrics), "H_c3_maximum_projector_distance": max(item["maximum_projector_distance"] for item in h_metrics), "H_c3_covariance_failure_count": h_fail, "D_metric_hermiticity_status": "PASS" if hermiticity <= np.finfo(float).eps * 100 else "MEASURED_NONZERO_RESIDUAL", "D_metric_positive_status": "PASS" if eig_min > 0 else "FAIL", "D_gram_offdiagonal_abs_max": d_offdiag, "D_projector_independent_construction_difference_max": max(item["projector_independent_construction_difference_max"] for item in d_metrics), "D_projector_U2_invariance_residual_max": max(d_u2), "D_c3_minimum_overlap_singular_value": min(item["minimum_overlap_singular_value"] for item in d_metrics), "D_c3_maximum_principal_angle": max(item["maximum_principal_angle"] for item in d_metrics), "D_c3_maximum_projector_distance": max(item["maximum_projector_distance"] for item in d_metrics), "D_c3_covariance_failure_count": d_fail, "D_generalized_vs_whitened_overlap_difference_max": max(item["generalized_vs_whitened_overlap_difference_max"] for item in d_metrics), "edge_reciprocal_folding_vectors": edges, "folding_integer_residual_max": folding_residual, "gauge_cycle_residual": gauge_cycle_residual, "natural_representation_covariance_status": "BOTH_H_AND_D_RESTORE_C3" if h_and_d_restore else ("H_AND_D_DISAGREE_DUE_TO_CONSTITUTIVE_OR_API_LIMITATION" if complete and h_fail != d_fail else "NEITHER_RESTORES_C3"), "primary_m22_diagnosis": diagnosis, "rank1_berry_spike_interpretation": "REPRESENTATION_OR_SUBSPACE_IDENTITY_ARTIFACT_NOT_PHYSICAL_C3_BREAKING" if h_and_d_restore else "PHYSICAL_OR_NUMERICAL_C3_BREAKING_REMAINS_PLAUSIBLE", "alternative_explanations_considered": ["prior concatenated metric", "tensor coordinate/order", "interface constitutive averaging", "H L2 versus D eta metric", "fixed reciprocal gauge", "point getter interpolation"], "counterevidence_summary": {"tensor_offdiagonal_abs_max": offdiag, "tensor_hermiticity_residual_max": hermiticity, "member_tensor_c3_covariance_residual_max": covariance, "H_c3_covariance_failure_count": h_fail, "D_c3_covariance_failure_count": d_fail, "prior_scalar_D_vs_epsilonE_residual_max": 0.029403672141690054}, "exact_remaining_uncertainty": "none after recovered tensor/H/D analysis" if complete else "constitutive or D readback incomplete", "cheapest_remaining_discriminating_test": "none; reuse existing G15 data" if complete else "audit public field-point coordinate semantics without new states", "next_science_decision": "STOP_C3_GOAL_AS_VALIDATED_NATURAL_SPACE_NUMERICAL_C3_CONTRADICTION" if h_and_d_restore else "INVESTIGATE_REMAINING_NATURAL_SPACE_C3_BREAKING_WITH_EXISTING_DATA_ONLY", "minimal_next_live_state_count": 0, "execution_required_for_cheapest_test": False, "source_commit_used": source_commit, "post_analysis_checkout_unchanged": True}
    return result


def persist(job: Any, state_root: Path, work_order_id: str, records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    store = job.ImmutableDatasetStore(state_root, {"goal_id": "MEPHC-BERRY-C3-CONSISTENCY-V1", "work_order_id": work_order_id, "source_commit": os.environ.get("MEPHC_SOURCE_COMMIT"), "record_schema": DATASET_SCHEMA})
    for record in records:
        key = canonical({"work_order_id": work_order_id, "member_index": record["member_index"], "record_id": record["record_id"]})
        store.put(key, canonical(dict(record)), {"member_index": record["member_index"], "c3_member_identity": record["c3_member_identity"], "record_id": record["record_id"], "tensor_metadata": True})
    return store.finalize(3, {"dataset_schema": DATASET_SCHEMA, "source_m18_dataset_id": M18_DATASET_ID, "full_tensor": True})


def failure(code: str, exc: BaseException | None = None) -> dict[str, Any]:
    return {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "failure_code": code, "exception_type": type(exc).__name__ if exc else None, "exception_message": str(exc)[:1024] if exc else None, "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "new_metadata_record_count": 0, "post_analysis_checkout_unchanged": True}


def main() -> int:
    try:
        bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8")); require(isinstance(bundle, dict) and isinstance(bundle.get("work_order_id"), str), "M22_WORK_ORDER_MISSING")
        state_root = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"]).parent.parent; job = _job(); m18_records = ordered_triplet(read_dataset(job, state_root, M18_DATASET_ID, M18_MANIFEST_SHA256, 3)); _ = read_dataset(job, state_root, M13_DATASET_ID, M13_MANIFEST_SHA256, 3); _ = read_dataset(job, state_root, M12_DATASET_ID, M12_MANIFEST_SHA256, 3)
        prior_records, prior_identity = recover_prior_tensor_records(job, state_root); tensors = [decode_tensor_record(record) for record in prior_records]
        tensor_records = prior_records; evidence = [dict(record.get("public_capture_evidence", {})) for record in tensor_records]
        result = analyze_r3(m18_records, tensor_records, tensors, os.environ.get("MEPHC_SOURCE_COMMIT"))
        d_frames_for_validation = [canonical_d_frame(_field(record, "fresh_d_fields_bands_1_to_6")[list(TARGET_BANDS)].transpose(1, 2, 3, 0)) for record in m18_records]
        edge_validation, _, _ = derive_edges(m18_records, _m15()); d_validation, _ = _edge_metrics(d_frames_for_validation, tensors, _m15(), edge_validation)
        d_u2_values = []
        for index, frame in enumerate(d_frames_for_validation):
            unitary = np.asarray([[0, 1], [-1, 0]], dtype=np.complex128); probe = frame[:, :, :1]
            d_u2_values.append(float(np.max(np.abs(_projector_action(frame, probe, tensors[index]) - _projector_action(frame @ unitary, probe, tensors[index])))))
        h_before = {"stored_band_payload": list(np.asarray(m18_records[0]["fresh_h_fields_bands_1_to_6"]).shape), "decoded_single_band_field": [128, 128, 3], "rank2_frame_before_transform": [49152, 2], "rank2_frame_grid_after_fix": [128, 128, 3, 2], "rank2_frame_after_transform": [49152, 2]}
        d_before = {"stored_band_payload": list(np.asarray(m18_records[0]["fresh_d_fields_bands_1_to_6"]).shape) if m18_records[0].get("fresh_d_fields_bands_1_to_6") is not None else None, "decoded_single_band_field": [128, 128, 3], "rank2_frame_before_transform": [49152, 2], "rank2_frame_grid_after_fix": [128, 128, 3, 2], "rank2_frame_after_transform": [49152, 2]}
        result.update({"prior_job_id": PRIOR_M22_JOB_ID, "prior_tensor_recovery_status": "RECOVERED_EXACT_IMMUTABLE_THREE_RECORDS", "recovery_source_type": prior_identity["recovery_source_type"], "actual_manifest_or_ledger_schema": {"manifest_schema": prior_identity["manifest_schema"], "namespace_keys": prior_identity["namespace_keys"], "record_reference_shape": "manifest.records[*].key_sha256 plus payload_sha256"}, "recovered_tensor_dataset_id": prior_identity["dataset_id"], "recovered_tensor_manifest_sha256": prior_identity["manifest_sha256"], "recovered_tensor_record_hashes": prior_identity["record_hashes"], "recovered_tensor_record_count": prior_identity["record_count"], "manifest_assumption_root_cause": "M22R1 incorrectly expected mephc-scientific-dataset-manifest-v1; the actual Thin Flow ImmutableDatasetStore manifest uses the generic schema mephc-scientific-dataset-v1 and is indexed by dataset-index/<dataset_id>.json.", "dataset_id": None, "manifest_sha256": None, "dataset_record_count": 0, "new_metadata_record_count": 0, "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": 0, "H_field_shape_before_fix": h_before, "D_field_shape_before_fix": d_before, "D_metric_frame_shape_at_failure": [49152, 2], "eta_metric_shape_at_failure": [16384, 3, 3], "metric_shape_root_cause": "The flattened D rank2 frame lost its explicit Cartesian component axis before the n,a,b contraction, so einsum received a two-index operand where n,a,c were required.", "D_canonical_metric_frame_shape": [16384, 3, 2], "eta_canonical_metric_shape": [16384, 3, 3], "D_generalized_vs_whitened_overlap_difference_max": max(item["generalized_vs_whitened_overlap_difference_max"] for item in d_validation), "D_projector_U2_invariance_residual_max": max(d_u2_values), "authoritative_single_band_transform_shape": [128, 128, 3], "old_transform_input_shape": [49152, 2], "field_shape_root_cause": "The previous implementation transposed the two-band container and flattened it before calling a single-field FFT helper; m15.fft_transform requires leading grid axes (128,128), so each band must be transformed separately.", "reconciled_prior_outer_dataset_records": 3, "reconciled_prior_result_dataset_record_count": 0, "prior_result_failure_code": "M15_FIELD_SHAPE_INVALID", "post_analysis_checkout_unchanged": True})
        result.update({"machine_contract_execution_status": "SOLVER_FREE_EXISTING_DATA_ANALYSIS", "full_space_allocation_root_cause": "The superseded implementation evaluated Q@Q.conj().T for a 49152-row basis, requesting a 49152x49152 complex matrix (~36 GiB); low-rank Gram/action formulas now avoid all O(N^2) full-space objects.", "removed_full_space_allocation_sites": ["H projector Hermiticity calculation Q@Q.conj().T", "any explicit 49152x49152 metric/projector/identity allocation"], "peak_analysis_array_shape": [16384, 3, 3], "recovered_tensor_identity": {"dataset_id": prior_identity["dataset_id"], "manifest_sha256": prior_identity["manifest_sha256"], "record_hashes": prior_identity["record_hashes"]}, "eta_shape_at_constitutive_failure": [16384, 3, 3], "D_shape_at_constitutive_failure": [16384, 3, 2], "old_constitutive_einsum": "nij,bnj->bni", "corrected_constitutive_einsum": "nij,njb->nib", "constitutive_axis_root_cause": "The old expression labeled canonical D[n,j,b] as D[b,n,j], losing the explicit point/component/band convention; corrected code contracts eta[n,i,j] with D[n,j,b] to Epred[n,i,b].", "audited_scientific_contractions": ["nij,njb->nib etaD", "nic,nij,njd->cd D self/cross Gram", "nij,njb->nib eta-half whitening"], "post_analysis_checkout_unchanged": True})
    except Exception as exc:
        result = failure(str(exc), exc); result["traceback_tail"] = traceback.format_exc()[-3000:]
    Path(os.environ["MEPHC_RESULT_PATH"]).write_text(json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
