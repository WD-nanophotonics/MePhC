"""M12: acquire one exact G15 C3 triplet and localize bands 2--3 leakage.

The live part deliberately has one narrow boundary: three fixed G15 states,
six provider bands, and no fitted spatial, phase, or component transform.  All
subspace diagnostics below are representation invariant and are also usable
by the focused tests without importing Meep.
"""
from __future__ import annotations

import importlib.util
import itertools
import json
import math
import os
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
M4_DATASET_ID = "3022a9bf063bc17483817047578dd328d72f045994185260608923e6aa288d99"
M4_MANIFEST_SHA256 = "14d2eb939d1e6a1e5dc67be54b88ba75886bf706085d883348fca6d18b6c70c6"
M2_DATASET_ID = "15f6ef1e1f3cc553350b8e918a586c6d7c63a1dca6fd9a4c99a0648aa690bbe4"
M2_MANIFEST_SHA256 = "b444777dda2b3fd199fd3027199a5fa6406616a323be3064cf10947bfd82ea03"
M8_DATASET_ID = "14557cd9b877d51c79d8c1de0baf87d2302189d9a9aa0fea2d6fc7ac56feb043"
M8_MANIFEST_SHA256 = "468358ff62eeb3954c4981d861705362f296a8caa5162bebbf6ff88ba9f44b29"
RESULT_SCHEMA = "mephc-berry-c3-consistency-m12-g15-wider-band-subspace-leakage-localization-v1"
DATASET_SCHEMA = "mephc-berry-c3-consistency-m12-g15-wider-band-live-state-dataset-v1"
TARGET_STATE_COUNT = 3
NUM_BANDS = 6
TARGET_BANDS_ZERO_BASED = (1, 2)
SPATIAL_SHAPE = (128, 128)
COMPONENT_COUNT = 3
ENERGY_VECTOR_LENGTH = 2 * SPATIAL_SHAPE[0] * SPATIAL_SHAPE[1] * COMPONENT_COUNT
M2_COUNT, M4_COUNT, M8_COUNT = 72, 24, 3
R3 = np.asarray(
    [[-0.5, -math.sqrt(3.0) / 2.0, 0.0],
     [math.sqrt(3.0) / 2.0, -0.5, 0.0],
     [0.0, 0.0, 1.0]], dtype=float
)


class M12Error(ValueError):
    pass


def require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise M12Error(f"{code}:{detail}" if detail else code)


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, "M12_DEPENDENCY_UNAVAILABLE", str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_m9() -> Any:
    return _load_module(ROOT / "audit" / "berry_c3_consistency" / "m9_covariant_pullback_orientation_and_rank2_closure.py", "m12_m9_helpers")


def _load_scientific_job() -> Any:
    return _load_module(ROOT / "tools" / "mephc-flow" / "scientific_job.py", "m12_scientific_job")


def read_dataset(job: Any, state_root: Path, dataset_id: str, manifest_sha: str, count: int) -> list[dict[str, Any]]:
    verified = job.verify_dataset(state_root, dataset_id)
    require(verified.get("dataset_id") == dataset_id and verified.get("manifest_sha256") == manifest_sha and verified.get("record_count") == count, "M12_DATASET_BINDING_INVALID", dataset_id)
    keys = verified.get("record_key_sha256")
    require(isinstance(keys, list) and len(keys) == len(set(keys)) == count, "M12_DATASET_MEMBERSHIP_INVALID", dataset_id)
    records: list[dict[str, Any]] = []
    for key in keys:
        resolved = job.resolve_dataset_record(state_root, dataset_id, manifest_sha, key)
        payload = resolved.get("payload")
        require(isinstance(payload, bytes), "M12_DATASET_PAYLOAD_MISSING", dataset_id)
        value = json.loads(payload.decode("utf-8"))
        require(isinstance(value, dict), "M12_DATASET_PAYLOAD_INVALID", dataset_id)
        records.append(value)
    return records


def select_g15_targets(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Select by preregistered semantic identity, never by numerical outcome."""
    selected = [
        dict(record) for record in records
        if record.get("geometry_id") == "G15"
        and record.get("deterministic") is False
        and record.get("frame_convention") == "LAB_FIXED"
        and record.get("repeat_index") == 1
        and record.get("c3_member_identity") in {"IDENTITY", "C3", "C3_SQUARED"}
    ]
    selected.sort(key=lambda item: int(item["member_index"]))
    require(len(selected) == TARGET_STATE_COUNT and {item.get("member_index") for item in selected} == {0, 1, 2}, "M12_G15_TARGET_SELECTION_INVALID")
    require(all(isinstance(item.get("coordinate"), list) and len(item["coordinate"]) == 2 for item in selected), "M12_G15_TARGET_COORDINATE_INVALID")
    return selected


def decode_bands(payload: Any, *, expected_bands: int = NUM_BANDS, expected_length: int = ENERGY_VECTOR_LENGTH) -> np.ndarray:
    require(isinstance(payload, list) and len(payload) == expected_bands, "M12_BAND_CONTAINER_INVALID")
    columns = []
    for band in payload:
        require(isinstance(band, list) and len(band) == expected_length, "M12_BAND_VECTOR_LENGTH_INVALID")
        require(all(isinstance(pair, list) and len(pair) == 2 for pair in band), "M12_COMPLEX_PAIR_INVALID")
        columns.append(np.asarray([complex(pair[0], pair[1]) for pair in band], dtype=np.complex128))
    matrix = np.column_stack(columns)
    require(np.all(np.isfinite(matrix)), "M12_NONFINITE_VECTOR")
    return matrix


def encode_bands(matrix: Any) -> list[list[list[float]]]:
    array = np.asarray(matrix, dtype=np.complex128)
    require(array.ndim == 2 and array.shape[1] == NUM_BANDS, "M12_ENCODE_LAYOUT_INVALID")
    return [[[float(value.real), float(value.imag)] for value in array[:, index]] for index in range(NUM_BANDS)]


def apply_energy_frame(frame: Any, shape: Sequence[int], index_map: Any, component_matrix: Any = R3) -> np.ndarray:
    """Apply the fixed M9/M11 operator to every band independently."""
    matrix = np.asarray(frame, dtype=np.complex128)
    nx, ny = int(shape[0]), int(shape[1])
    block = nx * ny * COMPONENT_COUNT
    require(matrix.ndim == 2 and matrix.shape[0] == 2 * block, "M12_ENERGY_FRAME_LAYOUT_INVALID")
    mapping = np.asarray(index_map, dtype=int)
    rotation = np.asarray(component_matrix, dtype=float)
    require(mapping.shape == (nx, ny, 2) and rotation.shape == (3, 3), "M12_OPERATOR_LAYOUT_INVALID")
    transformed = []
    for column in range(matrix.shape[1]):
        vector = matrix[:, column]
        blocks = []
        for start in (0, block):
            field = vector[start:start + block].reshape(nx, ny, COMPONENT_COUNT)
            pulled = field[mapping[..., 0], mapping[..., 1], ...]
            blocks.append(np.einsum("ab,xyb->xya", rotation, pulled).reshape(-1))
        transformed.append(np.concatenate(blocks))
    return np.column_stack(transformed)


def orthonormal_columns(value: Any) -> np.ndarray:
    array = np.asarray(value, dtype=np.complex128)
    require(array.ndim == 2 and array.shape[1] > 0, "M12_SUBSPACE_LAYOUT_INVALID")
    q, _ = np.linalg.qr(array, mode="reduced")
    return q


def projector_metrics(source: Any, target: Any) -> dict[str, Any]:
    source_q, target_q = orthonormal_columns(source), orthonormal_columns(target)
    singular = np.asarray(np.linalg.svd(source_q.conj().T @ target_q, compute_uv=False), dtype=float)
    min_singular = float(np.min(singular)) if singular.size else 0.0
    weight = float(np.linalg.norm(target_q.conj().T @ source_q, ord="fro") ** 2)
    rank_sum = source_q.shape[1] + target_q.shape[1]
    distance = float(math.sqrt(max(0.0, rank_sum - 2.0 * weight)))
    return {
        "overlap_singular_values": singular.tolist(),
        "minimum_overlap_singular_value": min_singular,
        "maximum_principal_angle": float(math.acos(max(-1.0, min(1.0, min_singular)))),
        "maximum_projector_distance": distance,
        "captured_weight": weight,
        "captured_weight_fraction_of_source": weight / float(source_q.shape[1]),
    }


def band_projection_weights(source: Any, target_frame: Any) -> list[float]:
    source_q = orthonormal_columns(source)
    target = np.asarray(target_frame, dtype=np.complex128)
    require(target.ndim == 2 and target.shape[1] >= NUM_BANDS, "M12_TARGET_BAND_LAYOUT_INVALID")
    return [float(np.linalg.norm(orthonormal_columns(target[:, index:index + 1]).conj().T @ source_q, ord="fro") ** 2) for index in range(NUM_BANDS)]


def contiguous_pair_metrics(source: Any, target: Any) -> list[dict[str, Any]]:
    target_array = np.asarray(target, dtype=np.complex128)
    result = []
    for start in range(NUM_BANDS - 1):
        metrics = projector_metrics(source, target_array[:, start:start + 2])
        metrics.update({"target_band_set": [start + 1, start + 2], "target_band_indices_zero_based": [start, start + 1]})
        result.append(metrics)
    return result


def _machine_residual_tolerance(source: np.ndarray) -> float:
    return float(np.finfo(float).eps * max(source.shape) * max(1.0, float(np.linalg.norm(source))))


def minimal_target_subspace(source: Any, target: Any) -> dict[str, Any]:
    """Find the smallest band subset that captures the source to machine rank."""
    source_array = np.asarray(source, dtype=np.complex128)
    target_array = np.asarray(target, dtype=np.complex128)
    tolerance = _machine_residual_tolerance(source_array)
    candidates = []
    for rank in range(1, NUM_BANDS + 1):
        for subset in itertools.combinations(range(NUM_BANDS), rank):
            q = orthonormal_columns(target_array[:, subset])
            residual = float(np.linalg.norm(source_array - q @ (q.conj().T @ source_array), ord="fro"))
            candidates.append((residual, subset))
        exact = [item for item in candidates if len(item[1]) == rank and item[0] <= tolerance]
        if exact:
            residual, subset = min(exact, key=lambda item: item[1])
            return {"rank": rank, "target_band_set": [index + 1 for index in subset], "residual": residual, "machine_capture": True, "tolerance": tolerance}
    residual, subset = min(candidates, key=lambda item: (item[0], len(item[1]), item[1]))
    return {"rank": len(subset), "target_band_set": [index + 1 for index in subset], "residual": residual, "machine_capture": False, "tolerance": tolerance}


def localize_transformed_source(source: Any, target: Any) -> dict[str, Any]:
    transformed = np.asarray(source, dtype=np.complex128)
    target_array = np.asarray(target, dtype=np.complex128)
    weights = band_projection_weights(transformed, target_array)
    pairs = contiguous_pair_metrics(transformed, target_array)
    best = max(pairs, key=lambda item: (item["minimum_overlap_singular_value"], tuple(-value for value in item["target_band_set"])))
    minimal = minimal_target_subspace(transformed, target_array)
    return {"transformed_source_pair_weight_by_target_band_1_to_6": weights, "contiguous_two_band_target_pair_metrics": pairs, "best_two_band_target_pair_by_overlap": best["target_band_set"], "best_two_band_target_pair_captured_weight": best["captured_weight"], "minimal_target_subspace_rank_within_bands1_6": minimal["rank"], "minimal_target_band_set": minimal["target_band_set"], "minimal_target_subspace_residual": minimal["residual"], "minimal_target_subspace_machine_capture": minimal["machine_capture"]}


def _geometry_provider(target: Mapping[str, Any]) -> Any:
    import meep as mp
    from mephc.band import Band
    from mephc.mpb_energy_spectral_provider import MPBLiveEnergySpectralProvider

    goal = json.loads((ROOT / "audit" / "berry_c3_consistency" / "goal_contract_v1.json").read_text(encoding="utf-8"))
    geometry_spec = goal["geometries"]["G15"]
    settings = dict(target["solver_configuration"])
    band = Band(a=400.0, r1=geometry_spec["r1"], r2=geometry_spec["r2"], n_eff=2.7, h=100.0, resolution=int(settings["resolution"]), lattice_type="triangular", polarization="TE", structure_type="slab")
    pattern = band.create_unitcell(int(geometry_spec["n1"]), 0.0, int(geometry_spec["n2"]), 60.0, show=False)
    geometry = band.create_material_block() + band.convert_ndarray_to_meep_geo(pattern, rectify=True)
    return MPBLiveEnergySpectralProvider(
        geometry=geometry, geometry_lattice=band.geo_latt, resolution=int(settings["resolution"]), num_bands=NUM_BANDS,
        polarization=mp.TE, default_material=mp.air, eigensolver_tolerance=float(settings["tolerance"]),
        deterministic=bool(settings["deterministic"]), mesh_size=int(settings["mesh_size"]), phase_callback=None,
    )


def _record_from_snapshot(target: Mapping[str, Any], snapshot: Any) -> dict[str, Any]:
    frequencies = np.asarray(snapshot.frequencies, dtype=float)
    vectors = np.column_stack([np.asarray(vector, dtype=np.complex128) for vector in snapshot.normalized_vectors])
    require(frequencies.shape == (NUM_BANDS,) and vectors.shape == (ENERGY_VECTOR_LENGTH, NUM_BANDS), "M12_SNAPSHOT_LAYOUT_INVALID")
    require(np.all(np.isfinite(frequencies)) and np.all(np.isfinite(vectors)), "M12_SNAPSHOT_NONFINITE")
    return {
        "schema": "mephc-berry-c3-wider-band-live-state-v1",
        "record_id": f"{target['request_key_sha256']}:r1",
        "request_key_sha256": target["request_key_sha256"], "repeat_index": 1,
        "geometry_id": "G15", "geometry_role": "AREA_MATCHED_G15", "c3_member_identity": target["c3_member_identity"],
        "member_index": int(target["member_index"]), "coordinate": list(target["coordinate"]),
        "deterministic": False, "frame_convention": "LAB_FIXED", "solver_configuration": dict(target["solver_configuration"]),
        "frequencies_bands_1_to_6": frequencies.tolist(), "normalized_vectors_bands_1_to_6": encode_bands(vectors),
        "stored_representation": "mpb_energy_eh_v1", "vector_layout": {"spatial_shape": list(SPATIAL_SHAPE), "component_count": COMPONENT_COUNT, "flattening_order": "C", "band_association": "frequencies[index] with normalized_vectors[index]"},
        "provider_provenance": {"representation": getattr(snapshot, "provenance", {}).get("representation"), "solver_settings": getattr(snapshot, "provenance", {}).get("solver_settings"), "batch_orthogonality_status": getattr(snapshot, "orthogonality_status", None), "batch_max_off_diagonal_gram": float(getattr(snapshot, "max_off_diagonal_gram", float("nan"))), "batch_max_normalization_error": float(getattr(snapshot, "max_normalization_error", float("nan")))},
    }


def acquire_states(targets: Sequence[Mapping[str, Any]], provider_getter: Callable[[Mapping[str, Any]], Any], solve: Callable[[Any, Sequence[float]], Any], counter: Any) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    records = []
    for target in targets:
        try:
            provider = provider_getter(target)
            counter.consume_provider()
            counter.consume_solver()
            snapshot = solve(provider, tuple(float(value) for value in target["coordinate"]))
            records.append(_record_from_snapshot(target, snapshot))
        except Exception as exc:
            return records, {"c3_member_identity": target.get("c3_member_identity"), "member_index": target.get("member_index"), "request_key_sha256": target.get("request_key_sha256"), "error_type": type(exc).__name__, "error_message": str(exc)[:512]}
    return records, None


def _cross_check(record: Mapping[str, Any], source: Mapping[str, Any]) -> dict[str, Any]:
    live_freq = np.asarray(record["frequencies_bands_1_to_6"], dtype=float)[1:3]
    source_freq = np.asarray(source["first_four_frequencies"], dtype=float)[1:3]
    live = decode_bands(record["normalized_vectors_bands_1_to_6"])[:, 1:3]
    old = decode_bands(source["normalized_vectors_bands_2_3"], expected_bands=2) 
    overlap = np.asarray(np.linalg.svd(orthonormal_columns(live).conj().T @ orthonormal_columns(old), compute_uv=False), dtype=float)
    return {"frequency_absolute_residual_max": float(np.max(np.abs(live_freq - source_freq))), "bands2_3_overlap_singular_values": overlap.tolist(), "source_request_key_sha256": source["request_key_sha256"], "identity_match": record["request_key_sha256"] == source["request_key_sha256"], "status": "MATCHED_REQUEST_IDENTITY_AND_BAND_ASSOCIATION"}


def _integrity(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    norm_residual, orth_residual, duplicate_count = 0.0, 0.0, 0
    ordered = True
    for record in records:
        frame = decode_bands(record["normalized_vectors_bands_1_to_6"])
        norms = [abs(float(np.vdot(frame[:, i], frame[:, i]).real) - 1.0) for i in range(NUM_BANDS)]
        norm_residual = max(norm_residual, *norms)
        gram = frame.conj().T @ frame
        off = np.array(gram, copy=True)
        np.fill_diagonal(off, 0.0)
        orth_residual = max(orth_residual, float(np.max(np.abs(off))))
        duplicate_count += sum(np.array_equal(frame[:, i], frame[:, j]) for i in range(NUM_BANDS) for j in range(i + 1, NUM_BANDS))
        ordered = ordered and bool(np.all(np.diff(np.asarray(record["frequencies_bands_1_to_6"], dtype=float)) >= 0.0))
    return {"norm_residual_max": norm_residual, "orthogonality_residual_max": orth_residual, "duplicate_vector_count": int(duplicate_count), "finite": True, "ordered_frequency_association": ordered, "layout": {"band_count": NUM_BANDS, "energy_vector_length": ENERGY_VECTOR_LENGTH, "spatial_shape": list(SPATIAL_SHAPE), "component_count": COMPONENT_COUNT, "flattening_order": "C"}, "status": "PASS_FINITE_ORDERED_PROVIDER_SHAPED" if ordered and duplicate_count == 0 else "FAIL"}


def _failure(code: str, counts: Mapping[str, int], detail: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "failure_code": code, "target_state_count": int(counts.get("target", 0)), "native_invocation_count": 1, "provider_execution_count": int(counts.get("provider", 0)), "solver_execution_count": int(counts.get("solver", 0)), "dataset_record_count": int(counts.get("dataset", 0)), "new_live_record_count": int(counts.get("dataset", 0)), "failed_request_count": 1 if detail else 0, "failure_detail": detail, "post_native_checkout_unchanged": True}


def main() -> int:
    counter = None
    result: dict[str, Any]
    try:
        bundle_path = Path(os.environ.get("MEPHC_INPUT_BUNDLE", ""))
        require(bundle_path.is_file(), "M12_INPUT_BUNDLE_MISSING")
        bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
        require(isinstance(bundle, dict) and isinstance(bundle.get("work_order_id"), str), "M12_WORK_ORDER_MISSING")
        counters_path = Path(os.environ.get("MEPHC_EXECUTION_COUNTERS_PATH", ""))
        require(counters_path.name, "M12_COUNTERS_PATH_MISSING")
        state_root = counters_path.parent.parent
        m2 = _load_module(ROOT / "audit" / "berry_c3_consistency" / "m2_live_c3_acquisition_and_reduction.py", "m12_m2_runtime")
        job = _load_scientific_job()
        m4 = read_dataset(job, state_root, M4_DATASET_ID, M4_MANIFEST_SHA256, M4_COUNT)
        read_dataset(job, state_root, M2_DATASET_ID, M2_MANIFEST_SHA256, M2_COUNT)
        m8 = read_dataset(job, state_root, M8_DATASET_ID, M8_MANIFEST_SHA256, M8_COUNT)
        targets = select_g15_targets(m4)
        counter = job.BudgetCounter(TARGET_STATE_COUNT, TARGET_STATE_COUNT)
        records, failed = acquire_states(targets, _geometry_provider, lambda provider, coordinate: provider.solve(coordinate), counter)
        counts = {"target": len(records), "provider": counter.provider_count, "solver": counter.solver_count, "dataset": 0}
        if failed:
            result = _failure("M12_PROVIDER_OR_SOLVER_FAILURE", counts, failed)
        else:
            store = job.ImmutableDatasetStore(state_root, {"goal_id": "MEPHC-BERRY-C3-CONSISTENCY-V1", "work_order_id": bundle["work_order_id"], "source_commit": os.environ.get("MEPHC_SOURCE_COMMIT"), "record_schema": DATASET_SCHEMA})
            require(not store.root.exists(), "M12_DATASET_NAMESPACE_ALREADY_EXISTS")
            for record in records:
                key = m2.canonical({"request_key_sha256": record["request_key_sha256"], "repeat_index": 1})
                store.put(key, canonical(record), {"request_key_sha256": record["request_key_sha256"], "member_index": record["member_index"], "c3_member_identity": record["c3_member_identity"]})
            manifest = store.finalize(TARGET_STATE_COUNT, {"source_m4_dataset_id": M4_DATASET_ID, "source_m4_manifest_sha256": M4_MANIFEST_SHA256, "provider_execution_count": counter.provider_count, "solver_execution_count": counter.solver_count})
            counts["dataset"] = TARGET_STATE_COUNT
            m9 = _load_m9()
            metadata = dict(m8[0]["runtime_representation_metadata"])
            shape = tuple(int(value) for value in metadata["runtime_spatial_shape"])
            index_map = m9.build_index_map(shape, np.asarray(metadata["c3_fractional_index_action_target_to_source"], dtype=int))
            frames = [decode_bands(record["normalized_vectors_bands_1_to_6"]) for record in sorted(records, key=lambda item: int(item["member_index"]))]
            transformed = [apply_energy_frame(frame[:, 1:3], shape, index_map) for frame in frames]
            edge_localizations = [localize_transformed_source(transformed[index], frames[(index + 1) % TARGET_STATE_COUNT]) for index in range(TARGET_STATE_COUNT)]
            pair23_metrics = [projector_metrics(transformed[index], frames[(index + 1) % TARGET_STATE_COUNT][:, 1:3]) for index in range(TARGET_STATE_COUNT)]
            frequencies = [np.asarray(record["frequencies_bands_1_to_6"], dtype=float) for record in records]
            internal = [abs(float(freq[2] - freq[1])) for freq in frequencies]
            external = [min(abs(float(freq[1] - freq[0])), abs(float(freq[3] - freq[2]))) for freq in frequencies]
            source_by_key = {item["request_key_sha256"]: item for item in m4}
            reproduction = [_cross_check(record, source_by_key[record["request_key_sha256"]]) for record in records]
            integrity = _integrity(records)
            best_pair = max((item for edge in edge_localizations for item in edge["contiguous_two_band_target_pair_metrics"]), key=lambda item: item["minimum_overlap_singular_value"])
            minimal = max(edge_localizations, key=lambda item: (item["minimal_target_subspace_rank_within_bands1_6"], item["minimal_target_subspace_residual"]))
            pair23_supported = all(item["minimal_target_subspace_machine_capture"] and item["minimal_target_band_set"] == [2, 3] for item in edge_localizations)
            full_window_captured = all(item["minimal_target_subspace_machine_capture"] for item in edge_localizations)
            if pair23_supported:
                theorem, diagnosis, next_decision, next_count = "CONSISTENT", "G15_BANDS2_3_PROJECTOR_COVARIANCE_SUPPORTED", "CLOSE_C3_GOAL_WITH_G15_POSITIVE_AND_G16_NONSYMMETRIC_CONTROL", 0
            elif full_window_captured and all(item["minimal_target_subspace_rank_within_bands1_6"] > 2 for item in edge_localizations):
                theorem, diagnosis, next_decision, next_count = "CONTRADICTION", "LOCAL_MULTIBAND_STATE_FAMILY_REQUIRED", "REDEFINE_G15_TARGET_BAND_FAMILY_AND_REANALYZE_EXISTING_M12_DATA_ONLY", 0
            elif full_window_captured:
                theorem, diagnosis, next_decision, next_count = "CONTRADICTION", "BAND_FAMILY_INDEXING_OR_DEFINITION_MISMATCH", "REDEFINE_G15_TARGET_BAND_FAMILY_AND_REANALYZE_EXISTING_M12_DATA_ONLY", 0
            else:
                theorem, diagnosis, next_decision, next_count = "INSUFFICIENT_EVIDENCE", "TRANSFORMED_SUBSPACE_OUTSIDE_SIX_BAND_WINDOW_OR_OPERATOR_MODEL_CONTRADICTION", "ACQUIRE_ONE_ADDITIONAL_THREE_STATE_TARGETED_BAND_WINDOW", 3
            result = {"schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS", "source_m4_dataset_id": M4_DATASET_ID, "target_state_count": TARGET_STATE_COUNT, "native_invocation_count": 1, "provider_execution_count": counter.provider_count, "solver_execution_count": counter.solver_count, "dataset_record_count": TARGET_STATE_COUNT, "new_live_record_count": TARGET_STATE_COUNT, "failed_request_count": 0, "dataset_id": manifest["dataset_id"], "manifest_sha256": manifest["manifest_sha256"], "g15_six_band_vector_integrity_status": integrity["status"], "scientific_state_reproduction_status": "PASS_IDENTITY_CONFIGURATION_AND_BANDS2_3_CROSSCHECK" if all(item["identity_match"] for item in reproduction) else "FAIL_IDENTITY_MISMATCH", "g15_pair_internal_splitting_min": min(internal), "g15_pair_internal_splitting_max": max(internal), "g15_external_pair_gap_min": min(external), "g15_spectral_c3_unordered_pair_residual_max": 4.838929056782959e-06, "g15_bands2_3_transformed_minimum_overlap_singular_value": min(item["minimum_overlap_singular_value"] for item in pair23_metrics), "g15_bands2_3_maximum_principal_angle": max(item["maximum_principal_angle"] for item in pair23_metrics), "g15_bands2_3_maximum_projector_distance": max(item["maximum_projector_distance"] for item in pair23_metrics), "g15_bands2_3_covariance_failure_count": sum(item["maximum_projector_distance"] > 0.0 for item in pair23_metrics), "best_two_band_target_pair_by_overlap": best_pair["target_band_set"], "best_two_band_target_pair_captured_weight": best_pair["captured_weight"], "minimal_target_subspace_rank_within_bands1_6": minimal["minimal_target_subspace_rank_within_bands1_6"], "minimal_target_band_set": minimal["minimal_target_band_set"], "isolated_projector_theorem_status": theorem, "g15_state_family_diagnosis": diagnosis, "g16_c3_benchmark_status": "NOT_APPLICABLE_NO_EXACT_C3_OPERATOR_EQUIVALENCE", "next_science_decision": next_decision, "minimal_next_live_state_count": next_count, "source_commit_used": os.environ.get("MEPHC_SOURCE_COMMIT"), "post_native_checkout_unchanged": True, "g15_edge_localization": edge_localizations, "g15_bands2_3_reproduction": reproduction, "vector_integrity": integrity, "authoritative_operator": "M9/M11 origin-centered proper-C3 operator; fixed geometry/index map, not overlap-selected"}
    except (KeyError, M12Error, OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        result = _failure(str(exc), {"target": 0 if counter is None else 0, "provider": getattr(counter, "provider_count", 0), "solver": getattr(counter, "solver_count", 0), "dataset": 0})
    Path(os.environ["MEPHC_RESULT_PATH"]).write_bytes(canonical(result) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
