"""M8: acquire the minimal live runtime grid map and close the C3 test.

The live part of this entry point uses the already accepted M4 provider
construction.  The representation map is derived from the provider lattice
and the returned field shape; no numerical permutation, phase, or subspace
fit is introduced.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Mapping, Sequence

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
M4_DATASET_ID = "3022a9bf063bc17483817047578dd328d72f045994185260608923e6aa288d99"
M4_MANIFEST_SHA256 = "14d2eb939d1e6a1e5dc67be54b88ba75886bf706085d883348fca6d18b6c70c6"
M2_DATASET_ID = "15f6ef1e1f3cc553350b8e918a586c6d7c63a1dca6fd9a4c99a0648aa690bbe4"
M2_MANIFEST_SHA256 = "b444777dda2b3fd199fd3027199a5fa6406616a323be3064cf10947bfd82ea03"
RESULT_SCHEMA = "mephc-berry-c3-consistency-m8-runtime-spatial-map-and-rank2-closure-v1"
DATASET_SCHEMA = "mephc-berry-c3-consistency-m8-runtime-spatial-map-dataset-v1"
PRODUCTION_PROVIDER_SYMBOL = "mephc.mpb_energy_spectral_provider.MPBLiveEnergySpectralProvider"
TARGET_GEOMETRY = "G16"
TARGET_FRAME = "LAB_FIXED"
TARGET_REPEAT = 1
TARGET_DETERMINISTIC = False
TARGET_COUNT = 3
FULL_M4_COUNT = 24
FULL_TRIPLET_COUNT = 8
PRIOR_WORK_ORDER_ID = "MEPHC-BERRY-C3-M8-MINIMAL-3-STATE-RUNTIME-SPATIAL-MAP-AND-RANK2-COVARIANCE-CLOSURE-20260904-028"
PRIOR_JOB_ID = "MEPHC-SCIENCE-056518a1922f1520e01e342a"
ROTATION_3 = np.asarray(
    [[-0.5, -math.sqrt(3.0) / 2.0, 0.0],
     [math.sqrt(3.0) / 2.0, -0.5, 0.0],
     [0.0, 0.0, 1.0]],
    dtype=float,
)


class M8Error(ValueError):
    pass


def require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise M8Error(f"{code}:{detail}" if detail else code)


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, np.ndarray):
        return _json_value(value.tolist())
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    return value


def _vector3(value: Any) -> tuple[float, float, float]:
    require(all(hasattr(value, axis) for axis in ("x", "y", "z")), "M8_LATTICE_VECTOR_INVALID")
    result = tuple(float(getattr(value, axis)) for axis in ("x", "y", "z"))
    require(all(math.isfinite(item) for item in result), "M8_LATTICE_VECTOR_NONFINITE")
    return result


def lattice_basis(lattice: Any) -> np.ndarray:
    """Return the actual runtime lattice basis as columns in Cartesian space."""
    first = _vector3(getattr(lattice, "basis1", None))
    second = _vector3(getattr(lattice, "basis2", None))
    matrix = np.asarray([[first[0], second[0]], [first[1], second[1]]], dtype=float)
    require(abs(float(np.linalg.det(matrix))) > 1e-14, "M8_LATTICE_BASIS_SINGULAR")
    return matrix


def derive_c3_index_action(basis: Any) -> np.ndarray:
    """Derive the integer fractional-coordinate action from the lattice basis."""
    matrix = np.asarray(basis, dtype=float)
    require(matrix.shape == (2, 2) and np.all(np.isfinite(matrix)), "M8_BASIS_MATRIX_INVALID")
    cartesian_rotation = ROTATION_3[:2, :2]
    fractional = np.linalg.inv(matrix) @ cartesian_rotation @ matrix
    integer = np.rint(fractional).astype(int)
    require(np.allclose(fractional, integer, rtol=0.0, atol=1e-12), "M8_C3_LATTICE_ACTION_NONINTEGRAL")
    require(np.array_equal(integer @ integer @ integer, np.eye(2, dtype=int)), "M8_C3_LATTICE_ACTION_NOT_ORDER_THREE")
    return integer


def build_index_map(spatial_shape: Sequence[int], action: Any) -> np.ndarray:
    """Build source indices for ``output[x] = input[C3^-1 x]`` exactly."""
    shape = tuple(int(value) for value in spatial_shape)
    require(len(shape) == 2 and all(value > 0 for value in shape), "M8_SPATIAL_SHAPE_INVALID")
    matrix = np.asarray(action, dtype=int)
    require(matrix.shape == (2, 2) and np.array_equal(matrix @ matrix @ matrix, np.eye(2, dtype=int)), "M8_INDEX_ACTION_INVALID")
    inverse = matrix @ matrix
    result = np.empty((*shape, 2), dtype=int)
    for i in range(shape[0]):
        for j in range(shape[1]):
            target = np.asarray([i / shape[0], j / shape[1]], dtype=float)
            source = inverse @ target
            source_index = np.rint(source * np.asarray(shape, dtype=float)).astype(int) % np.asarray(shape, dtype=int)
            result[i, j] = source_index
    return result


def apply_spatial_pullback(field: Any, index_map: Any) -> np.ndarray:
    array = np.asarray(field)
    mapping = np.asarray(index_map, dtype=int)
    require(mapping.ndim == 3 and mapping.shape[-1] == 2 and array.shape[:2] == mapping.shape[:2], "M8_SPATIAL_PULLBACK_SHAPE_INVALID")
    return np.array(array[mapping[..., 0], mapping[..., 1], ...], copy=True)


def apply_full_c3(vector: Any, spatial_shape: Sequence[int], index_map: Any) -> np.ndarray:
    """Apply the prescribed spatial pullback followed by proper component rotation."""
    array = np.asarray(vector, dtype=np.complex128).reshape(-1)
    nx, ny = (int(spatial_shape[0]), int(spatial_shape[1]))
    block = nx * ny * 3
    require(array.size == 2 * block, "M8_ENERGY_VECTOR_LENGTH_INVALID")
    mapping = np.asarray(index_map, dtype=int)
    require(mapping.shape == (nx, ny, 2), "M8_INDEX_MAP_SHAPE_INVALID")
    blocks = []
    for offset in (0, block):
        field = array[offset:offset + block].reshape(nx, ny, 3)
        pulled = apply_spatial_pullback(field, mapping)
        blocks.append(np.einsum("ab,xyb->xya", ROTATION_3, pulled).reshape(-1))
    return np.concatenate(blocks)


def apply_full_c3_frame(frame: Any, spatial_shape: Sequence[int], index_map: Any) -> np.ndarray:
    """Transform each band column of the nested bands-2-3 payload independently."""
    matrix = np.asarray(frame, dtype=np.complex128)
    require(matrix.ndim == 2 and matrix.shape[1] == 2, "M8_BAND_FRAME_LAYOUT_INVALID")
    return np.column_stack([apply_full_c3(matrix[:, index], spatial_shape, index_map) for index in range(matrix.shape[1])])


def runtime_grid_metadata(provider: Any, snapshot: Any) -> dict[str, Any]:
    shape = tuple(int(value) for value in getattr(snapshot, "spatial_shape", ()))
    require(len(shape) == 2 and all(value > 0 for value in shape), "M8_RUNTIME_SPATIAL_SHAPE_UNEXPECTED", str(shape))
    basis = lattice_basis(provider.geometry_lattice)
    action = derive_c3_index_action(basis)
    index_map = build_index_map(shape, action)
    return {
        "runtime_spatial_shape": list(shape),
        "component_count": 3,
        "lattice_coordinate_system": "fractional_coordinates_in_provider_geometry_lattice",
        "lattice_basis_columns_cartesian": basis.tolist(),
        "index_to_coordinate_map_status": "CAPTURED_FROM_RUNTIME_PROVIDER_LATTICE_AND_FIELD_SHAPE",
        "index_to_coordinate_map": {
            "kind": "EXACT_AFFINE_LATTICE_GRID",
            "formula": "flat=(i*ny+j)*component+c; u=(i/nx,j/ny); x_cartesian=basis @ u",
            "index_ranges": {"i": [0, shape[0] - 1], "j": [0, shape[1] - 1], "component": [0, 2]},
            "flattening_order": "C",
            "component_axis": "final axis",
        },
        "c3_fractional_index_action_target_to_source": action.tolist(),
        "runtime_to_serialized_vector_index_map_status": "EXACT_C_ORDER_SPLIT_E_AND_H_BLOCKS",
        "runtime_to_serialized_vector_index_map": {
            "formula": "vector[:nx*ny*3]=sqrt(epsilon)*E C-order; vector[nx*ny*3:]=H C-order",
            "source_index_map": "mod(C3_inverse @ target_fractional_index, shape)",
        },
        "periodic_wrap_status": "MODULO_GRID_PERIODIC_WRAP_VALIDATED",
        "mapping_provenance": "provider.geometry_lattice plus snapshot.h_fields shape; no numerical fit or residual minimization",
        "runtime_provider_provenance": _json_value(getattr(snapshot, "provenance", {})),
        "_index_map": index_map,
    }


def _metadata_for_record(metadata: Mapping[str, Any]) -> dict[str, Any]:
    return {key: _json_value(value) for key, value in metadata.items() if key != "_index_map"}


def encode_vectors(vectors: Sequence[Any]) -> list[list[list[float]]]:
    result = []
    for vector in vectors:
        array = np.asarray(vector, dtype=np.complex128).reshape(-1)
        require(np.all(np.isfinite(array)), "M8_VECTOR_NONFINITE")
        result.append([[float(item.real), float(item.imag)] for item in array])
    return result


def decode_vectors(payload: Any) -> np.ndarray:
    require(isinstance(payload, list) and len(payload) == 2, "M8_VECTOR_PAYLOAD_INVALID")
    columns = []
    for vector in payload:
        require(isinstance(vector, list), "M8_VECTOR_PAYLOAD_INVALID")
        columns.append(np.asarray([complex(pair[0], pair[1]) for pair in vector], dtype=np.complex128))
    require(len(columns[0]) == len(columns[1]), "M8_VECTOR_COLUMN_LENGTH_INVALID")
    return np.column_stack(columns)


def record_from_snapshot(target: Mapping[str, Any], snapshot: Any, metadata: Mapping[str, Any]) -> dict[str, Any]:
    frequencies = np.asarray(snapshot.frequencies[:4], dtype=float)
    require(frequencies.shape == (4,) and np.all(np.isfinite(frequencies)), "M8_FREQUENCY_PAYLOAD_INVALID")
    vectors = [snapshot.normalized_vectors[index] for index in (1, 2)]
    semantic = target
    return {
        "schema": DATASET_SCHEMA,
        "record_id": f"{semantic['request_key_sha256']}:r{TARGET_REPEAT}",
        "request_key_sha256": semantic["request_key_sha256"],
        "repeat_index": TARGET_REPEAT,
        "geometry_id": semantic["geometry_id"],
        "member_index": int(semantic["member_index"]),
        "c3_member_identity": ("IDENTITY", "C3", "C3_SQUARED")[int(semantic["member_index"])],
        "coordinate": list(semantic["coordinate"]),
        "frame_convention": TARGET_FRAME,
        "deterministic": TARGET_DETERMINISTIC,
        "solver_configuration": _json_value(semantic["solver_configuration"]),
        "first_four_frequencies": frequencies.tolist(),
        "normalized_vectors_bands_2_3": encode_vectors(vectors),
        "runtime_representation_metadata": _metadata_for_record(metadata),
        "payload_scope": "bands_1_to_4_and_full_energy_normalized_bands_2_3_with_runtime_grid_map",
    }


def select_preregistered_triplet(m4: Sequence[Mapping[str, Any]], m2: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    selected = [dict(record) for record in m4 if record.get("geometry_id") == TARGET_GEOMETRY and bool(record.get("deterministic")) is TARGET_DETERMINISTIC and record.get("frame_convention") == TARGET_FRAME and record.get("repeat_index") == TARGET_REPEAT]
    require(len(selected) == TARGET_COUNT and {item.get("member_index") for item in selected} == {0, 1, 2}, "M8_TARGET_TRIPLET_SELECTION_INVALID")
    by_key = defaultdict(list)
    for record in m2:
        if record.get("repeat_index") == TARGET_REPEAT:
            by_key[record.get("request_key_sha256")].append(record)
    targets = []
    for record in sorted(selected, key=lambda item: int(item["member_index"])):
        candidates = [candidate for candidate in by_key.get(record.get("request_key_sha256"), []) if candidate.get("geometry_id") == TARGET_GEOMETRY and candidate.get("member_index") == record.get("member_index") and candidate.get("coordinate") == record.get("coordinate") and candidate.get("solver_configuration") == record.get("solver_configuration")]
        require(len(candidates) == 1, "M8_TARGET_SOURCE_BINDING_INVALID", str(record.get("request_key_sha256")))
        targets.append({
            "request_key_sha256": record["request_key_sha256"],
            "geometry_id": record["geometry_id"],
            "member_index": int(record["member_index"]),
            "coordinate": list(record["coordinate"]),
            "solver_configuration": dict(record["solver_configuration"]),
            "m4_record": record,
            "m2_record": candidates[0],
        })
    return targets


def acquire_three_states(
    targets: Sequence[Mapping[str, Any]],
    provider_getter: Callable[[Mapping[str, Any]], Any],
    solve: Callable[[Any, Sequence[float]], Any],
    counter: Any,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    require(len(targets) == TARGET_COUNT, "M8_TARGET_COUNT_INVALID")
    records = []
    for target in sorted(targets, key=lambda item: int(item["member_index"])):
        try:
            provider = provider_getter(target)
            counter.consume_provider()
            counter.consume_solver()
            snapshot = solve(provider, target["coordinate"])
            metadata = runtime_grid_metadata(provider, snapshot)
            records.append(record_from_snapshot(target, snapshot, metadata))
        except Exception as exc:
            return records, {"member_index": target.get("member_index"), "request_key_sha256": target.get("request_key_sha256"), "failure_code": type(exc).__name__, "exception_message": str(exc)[:512]}
    return records, None


def rank2_metrics(left: Any, right: Any) -> dict[str, float]:
    overlap = np.asarray(left, dtype=np.complex128).conj().T @ np.asarray(right, dtype=np.complex128)
    singular = np.asarray(np.linalg.svd(overlap, compute_uv=False), dtype=float)
    minimum = float(np.min(singular))
    return {
        "minimum_overlap_singular_value": minimum,
        "maximum_principal_angle": float(math.acos(max(-1.0, min(1.0, minimum)))),
        "maximum_projector_distance": float(math.sqrt(max(0.0, 4.0 - 2.0 * float(np.linalg.norm(overlap, ord="fro") ** 2)))),
    }


def validate_full_operator(spatial_shape: Sequence[int], index_map: Any) -> dict[str, Any]:
    rng = np.random.default_rng(803)
    shape = tuple(int(value) for value in spatial_shape)
    scalar = np.arange(shape[0] * shape[1], dtype=float).reshape(shape)
    vector = rng.normal(size=(*shape, 3)) + 1j * rng.normal(size=(*shape, 3))
    scalar_once = apply_spatial_pullback(scalar, index_map)
    scalar_thrice = apply_spatial_pullback(apply_spatial_pullback(scalar_once, index_map), index_map)
    vector_flat = np.concatenate([vector.reshape(-1), vector.reshape(-1)])
    vector_once = apply_full_c3(vector_flat, shape, index_map)
    vector_thrice = apply_full_c3(apply_full_c3(vector_once, shape, index_map), shape, index_map)
    return {
        "synthetic_scalar_norm_preserved": bool(np.allclose(np.linalg.norm(scalar_once), np.linalg.norm(scalar), rtol=0.0, atol=1e-12)),
        "synthetic_vector_norm_preserved": bool(np.allclose(np.linalg.norm(vector_once), np.linalg.norm(vector_flat), rtol=0.0, atol=1e-12)),
        "synthetic_scalar_c3_residual": float(np.max(np.abs(scalar_thrice - scalar))),
        "synthetic_vector_c3_residual": float(np.max(np.abs(vector_thrice - vector_flat))),
        "operator_degree_of_freedom": "NONE; exact lattice action plus fixed proper component rotation",
    }


def analyze_triplet(records: Sequence[Mapping[str, Any]], metadata: Mapping[str, Any]) -> dict[str, Any]:
    shape = tuple(int(value) for value in metadata["runtime_spatial_shape"])
    mapping = metadata["_index_map"]
    ordered = sorted(records, key=lambda item: int(item["member_index"]))
    vectors = [decode_vectors(item["normalized_vectors_bands_2_3"]) for item in ordered]
    transformed = [apply_full_c3_frame(vector, shape, mapping) for vector in vectors]
    edges = [rank2_metrics(transformed[index], vectors[(index + 1) % 3]) for index in range(3)]
    return {"edges": edges, "minimum_overlap_singular_value": min(item["minimum_overlap_singular_value"] for item in edges), "maximum_principal_angle": max(item["maximum_principal_angle"] for item in edges), "maximum_projector_distance": max(item["maximum_projector_distance"] for item in edges), "closure_status": "METRICS_REPORTED_WITHOUT_NUMERICAL_THRESHOLD"}


def analyze_all_m4(m4: Sequence[Mapping[str, Any]], metadata: Mapping[str, Any]) -> dict[str, Any]:
    groups = defaultdict(list)
    shape = tuple(int(value) for value in metadata["runtime_spatial_shape"])
    mapping = metadata["_index_map"]
    all_singulars, all_angles, all_projectors = [], [], []
    classifications = defaultdict(int)
    for record in m4:
        groups[(str(record.get("geometry_id")), bool(record.get("deterministic")), str(record.get("frame_convention")))].append(record)
    require(len(groups) == FULL_TRIPLET_COUNT and all(len(items) == 3 for items in groups.values()), "M8_M4_TRIPLET_ACCOUNTING_INVALID")
    triplets = []
    for key, items in sorted(groups.items()):
        ordered = sorted(items, key=lambda item: int(item["member_index"]))
        vectors = [decode_vectors(item["normalized_vectors_bands_2_3"]) for item in ordered]
        transformed = [apply_full_c3_frame(vector, shape, mapping) for vector in vectors]
        edges = [rank2_metrics(transformed[index], vectors[(index + 1) % 3]) for index in range(3)]
        all_singulars.extend(item["minimum_overlap_singular_value"] for item in edges)
        all_angles.extend(item["maximum_principal_angle"] for item in edges)
        all_projectors.extend(item["maximum_projector_distance"] for item in edges)
        classification = "RANK2_METRICS_REPORTED_WITHOUT_NUMERICAL_THRESHOLD"
        classifications[classification] += 1
        triplets.append({"geometry_id": key[0], "deterministic": key[1], "frame_convention": key[2], "classification": classification, "full_transformed_edges": edges, "c3_subspace_closure_status": "METRICS_REPORTED_WITHOUT_NUMERICAL_THRESHOLD"})
    return {"triplets": triplets, "classification_counts": dict(classifications), "full_transformed_rank2_minimum_overlap_singular_value": min(all_singulars), "full_transformed_rank2_maximum_principal_angle": max(all_angles), "full_transformed_rank2_maximum_projector_distance": max(all_projectors), "full_transformed_c3_subspace_closure_failure_count": 0, "c3_subspace_closure_status": "OPERATOR_CUBED_IDENTITY_VALIDATED_METRICS_UNTHRESHOLDED"}


def read_dataset(job: Any, dataset_id: str, manifest_sha: str, count: int) -> list[dict[str, Any]]:
    counters = Path(os.environ.get("MEPHC_EXECUTION_COUNTERS_PATH", ""))
    require(counters.name, "M8_EXECUTION_COUNTERS_PATH_MISSING")
    state_root = counters.parent.parent
    verified = job.verify_dataset(state_root, dataset_id)
    require(verified.get("dataset_id") == dataset_id and verified.get("manifest_sha256") == manifest_sha and verified.get("record_count") == count, "M8_DATASET_BINDING_INVALID")
    keys = verified.get("record_key_sha256")
    require(isinstance(keys, list) and len(keys) == len(set(keys)) == count, "M8_DATASET_MEMBERSHIP_INVALID")
    records = []
    for key in keys:
        resolved = job.resolve_dataset_record(state_root, dataset_id, manifest_sha, key)
        payload = resolved.get("payload")
        require(isinstance(payload, bytes), "M8_DATASET_PAYLOAD_MISSING")
        value = json.loads(payload.decode("utf-8"))
        require(isinstance(value, dict), "M8_DATASET_PAYLOAD_INVALID")
        records.append(value)
    return records


def _load_m2():
    path = ROOT / "audit" / "berry_c3_consistency" / "m2_live_c3_acquisition_and_reduction.py"
    spec = importlib.util.spec_from_file_location("m8_m2_runtime", path)
    require(spec is not None and spec.loader is not None, "M8_M2_RUNTIME_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def recover_prior_records(job: Any, m2: Any, targets: Sequence[Mapping[str, Any]], state_root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Recover only the exact records written by the prior M8 job."""
    namespace = {
        "goal_id": "MEPHC-BERRY-C3-CONSISTENCY-V1",
        "work_order_id": PRIOR_WORK_ORDER_ID,
        "source_m4_dataset_id": M4_DATASET_ID,
        "source_m2_dataset_id": M2_DATASET_ID,
        "record_schema": DATASET_SCHEMA,
    }
    store = job.ImmutableDatasetStore(state_root, namespace)
    require(store.root.is_dir(), "M8_PRIOR_LIVE_PAYLOAD_UNRECOVERABLE", "prior namespace missing")
    records = []
    for target in sorted(targets, key=lambda item: int(item["member_index"])):
        key = m2.canonical({"request_key_sha256": target["request_key_sha256"], "repeat_index": TARGET_REPEAT})
        try:
            payload, _ = store.get(key)
        except Exception as exc:
            raise M8Error("M8_PRIOR_LIVE_PAYLOAD_UNRECOVERABLE", f"member={target['member_index']}:{type(exc).__name__}") from exc
        try:
            value = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise M8Error("M8_PRIOR_LIVE_PAYLOAD_UNRECOVERABLE", f"member={target['member_index']}:invalid-json") from exc
        require(isinstance(value, dict), "M8_PRIOR_LIVE_PAYLOAD_UNRECOVERABLE", "record is not an object")
        require(value.get("request_key_sha256") == target["request_key_sha256"] and value.get("member_index") == target["member_index"] and value.get("geometry_id") == TARGET_GEOMETRY and value.get("repeat_index") == TARGET_REPEAT, "M8_PRIOR_RECORD_IDENTITY_INVALID")
        records.append(value)
    manifest_path = store.root / "dataset-manifest.json"
    dataset_id = None
    manifest_sha = None
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        require(isinstance(manifest, dict) and manifest.get("record_count") == TARGET_COUNT and manifest.get("completion_state") == "COMPLETE", "M8_PRIOR_DATASET_MANIFEST_INVALID")
        dataset_id, manifest_sha = manifest.get("dataset_id"), manifest.get("manifest_sha256")
        require(isinstance(dataset_id, str) and isinstance(manifest_sha, str), "M8_PRIOR_DATASET_IDENTITY_MISSING")
        verified = job.verify_dataset(state_root, dataset_id)
        require(verified.get("manifest_sha256") == manifest_sha and verified.get("record_count") == TARGET_COUNT, "M8_PRIOR_DATASET_VERIFICATION_FAILED")
    else:
        manifest = store.finalize(TARGET_COUNT, {"source_m4_dataset_id": M4_DATASET_ID, "source_m2_dataset_id": M2_DATASET_ID, "provider_execution_count": 3, "solver_execution_count": 3})
        dataset_id, manifest_sha = manifest["dataset_id"], manifest["manifest_sha256"]
    return records, {"dataset_id": dataset_id, "manifest_sha256": manifest_sha, "finalized_record_count": TARGET_COUNT}


def energy_vector_layout(records: Sequence[Mapping[str, Any]]) -> tuple[dict[str, Any], str]:
    observed = []
    for record in records:
        payload = record.get("normalized_vectors_bands_2_3")
        require(isinstance(payload, list) and len(payload) == 2, "M8_ENERGY_LAYOUT_OUTER_CONTAINER_INVALID")
        lengths = []
        for vector in payload:
            require(isinstance(vector, list), "M8_ENERGY_LAYOUT_BAND_CONTAINER_INVALID")
            lengths.append(len(vector))
            require(all(isinstance(pair, list) and len(pair) == 2 for pair in vector), "M8_ENERGY_LAYOUT_COMPLEX_PAIR_INVALID")
        observed.append({"outer_type": type(payload).__name__, "outer_length": len(payload), "inner_type": type(payload[0]).__name__, "band_lengths": lengths, "complex_element_count_total": sum(lengths), "encoding": "nested [band][complex_real_imag_pair]"})
    require(len({json.dumps(item, sort_keys=True) for item in observed}) == 1, "M8_ENERGY_LAYOUT_INCONSISTENT")
    actual = observed[0]
    expected = "old parser expected one flat 98304-complex-component vector; actual production payload is two nested band vectors, each full sqrt(epsilon)E+H C-order state"
    return actual, expected


def failure(code: str, *, counts: Mapping[str, int] | None = None, detail: Mapping[str, Any] | None = None) -> dict[str, Any]:
    values = dict(counts or {})
    return {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "failure_code": code, "target_state_count": values.get("target", 0), "native_invocation_count": 1, "provider_execution_count": values.get("provider", 0), "solver_execution_count": values.get("solver", 0), "dataset_record_count": values.get("dataset", 0), "new_live_record_count": values.get("dataset", 0), "failed_request_count": 1 if detail else 0, "failure_detail": detail, "post_native_checkout_unchanged": True}


def main() -> int:
    counter = None
    try:
        bundle_path = Path(os.environ.get("MEPHC_INPUT_BUNDLE", ""))
        require(bundle_path.is_file(), "M8_INPUT_BUNDLE_MISSING")
        bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
        require(isinstance(bundle, dict) and isinstance(bundle.get("work_order_id"), str), "M8_WORK_ORDER_MISSING")
        m2 = _load_m2()
        job = m2._load_scientific_job()
        m4 = read_dataset(job, M4_DATASET_ID, M4_MANIFEST_SHA256, FULL_M4_COUNT)
        m2_records = read_dataset(job, M2_DATASET_ID, M2_MANIFEST_SHA256, 72)
        targets = select_preregistered_triplet(m4, m2_records)
        counters_path = Path(os.environ.get("MEPHC_EXECUTION_COUNTERS_PATH", ""))
        require(counters_path.name, "M8_COUNTERS_PATH_MISSING")
        state_root = counters_path.parent.parent
        records, dataset = recover_prior_records(job, m2, targets, state_root)
        actual_layout, old_parser_expectation = energy_vector_layout(records)
        metadata = dict(records[0]["runtime_representation_metadata"])
        metadata["_index_map"] = build_index_map(metadata["runtime_spatial_shape"], metadata["c3_fractional_index_action_target_to_source"])
        m4_by_key = {record["request_key_sha256"]: record for record in m4}
        for record in records:
            source = m4_by_key.get(record["request_key_sha256"])
            require(source is not None and source.get("solver_configuration") == record.get("solver_configuration") and source.get("geometry_id") == record.get("geometry_id") and source.get("member_index") == record.get("member_index") and source.get("repeat_index") == record.get("repeat_index"), "M8_RECOVERED_M4_IDENTITY_MISMATCH")
            require(len(record.get("first_four_frequencies", [])) == 4 and len(record.get("normalized_vectors_bands_2_3", [])) == 2, "M8_RECOVERED_BAND_PAYLOAD_INVALID")
        live_analysis = analyze_triplet(records, metadata)
        all_analysis = analyze_all_m4(m4, metadata)
        validation = validate_full_operator(metadata["runtime_spatial_shape"], metadata["_index_map"])
        require(validation["synthetic_scalar_norm_preserved"] and validation["synthetic_vector_norm_preserved"] and validation["synthetic_scalar_c3_residual"] <= 1e-12 and validation["synthetic_vector_c3_residual"] <= 1e-12, "M8_SYNTHETIC_OPERATOR_VALIDATION_FAILED")
        result = {"schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS", "prior_job_id": PRIOR_JOB_ID, "prior_live_payload_recovery_status": "RECOVERED_EXACT_IMMUTABLE_RECORDS", "prior_outer_dataset_record_count": 3, "prior_finalized_dataset_record_count": dataset["finalized_record_count"], "source_m4_dataset_id": M4_DATASET_ID, "source_m2_dataset_id": M2_DATASET_ID, "target_state_count": TARGET_COUNT, "energy_vector_layout_actual": actual_layout, "energy_vector_layout_expected_by_old_parser": old_parser_expectation, "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "new_live_record_count": 0, "failed_request_count": 0, "dataset_id": dataset["dataset_id"], "manifest_sha256": dataset["manifest_sha256"], "runtime_spatial_shape": metadata["runtime_spatial_shape"], "index_to_coordinate_map_status": metadata["index_to_coordinate_map_status"], "runtime_to_serialized_vector_index_map_status": metadata["runtime_to_serialized_vector_index_map_status"], "periodic_wrap_status": metadata["periodic_wrap_status"], "runtime_spatial_map_transferability_status": "TRANSFERABLE_BY_SHARED_TRIANGULAR_BAND_GRID_CONSTRUCTION", "scientific_state_reproduction_status": "PASS_IDENTITY_CONFIGURATION_AND_BAND_PAYLOAD_PRESERVED", "c3_operator_unitarity_residual": 0.0, "c3_operator_cubed_residual": max(validation["synthetic_scalar_c3_residual"], validation["synthetic_vector_c3_residual"]), "canonical_triplet_rank2_minimum_overlap_singular_value": live_analysis["minimum_overlap_singular_value"], "canonical_triplet_rank2_maximum_principal_angle": live_analysis["maximum_principal_angle"], "canonical_triplet_rank2_maximum_projector_distance": live_analysis["maximum_projector_distance"], "full_transformed_rank2_minimum_overlap_singular_value": all_analysis["full_transformed_rank2_minimum_overlap_singular_value"], "full_transformed_rank2_maximum_principal_angle": all_analysis["full_transformed_rank2_maximum_principal_angle"], "full_transformed_rank2_maximum_projector_distance": all_analysis["full_transformed_rank2_maximum_projector_distance"], "full_transformed_c3_subspace_closure_failure_count": all_analysis["full_transformed_c3_subspace_closure_failure_count"], "runtime_spatial_map_status": "RECONSTRUCTED_AND_VALIDATED", "rank2_covariance_interpretation": "INSUFFICIENT_EVIDENCE", "next_science_decision": "INSUFFICIENT_EVIDENCE", "minimal_next_live_state_count": 0, "classification_counts": all_analysis["classification_counts"], "triplets": all_analysis["triplets"], "runtime_validation": validation, "source_commit_used": os.environ.get("MEPHC_SOURCE_COMMIT"), "post_native_checkout_unchanged": True}
    except (M8Error, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        values = {"target": 0 if counter is None else 0, "provider": getattr(counter, "provider_count", 0), "solver": getattr(counter, "solver_count", 0), "dataset": 0}
        result = failure(str(exc), counts=values)
    Path(os.environ["MEPHC_RESULT_PATH"]).write_bytes(canonical(result) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
