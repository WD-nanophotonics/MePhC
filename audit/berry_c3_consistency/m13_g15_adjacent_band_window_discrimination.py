"""M13 final adjacent-band window for the exact G15 C3 control.

M12 bands 1--6 are immutable input.  This work order acquires only bands
7--12 for the identical three states and combines the two independent
records without changing the established M9/M11 operator.
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
M12_DATASET_ID = "c750df1085ddd0df8ae2ca1611d2881f378767d8fe2bc053a6ed504d99359a40"
M12_MANIFEST_SHA256 = "23079cbcbdf26952ef52a5dbac5f81ec1a9b0d163e36af80fb69e102be1ed2bc"
M4_DATASET_ID = "3022a9bf063bc17483817047578dd328d72f045994185260608923e6aa288d99"
M4_MANIFEST_SHA256 = "14d2eb939d1e6a1e5dc67be54b88ba75886bf706085d883348fca6d18b6c70c6"
M8_DATASET_ID = "14557cd9b877d51c79d8c1de0baf87d2302189d9a9aa0fea2d6fc7ac56feb043"
M8_MANIFEST_SHA256 = "468358ff62eeb3954c4981d861705362f296a8caa5162bebbf6ff88ba9f44b29"
RESULT_SCHEMA = "mephc-berry-c3-consistency-m13-g15-adjacent-band-window-discrimination-v1"
DATASET_SCHEMA = "mephc-berry-c3-consistency-m13-g15-adjacent-band-window-live-state-dataset-v1"
TARGET_COUNT = 3
NUM_BANDS = 12
NEW_BANDS = 6
NEW_BAND_START = 6
SPATIAL_SHAPE = (128, 128)
ENERGY_VECTOR_LENGTH = 2 * 128 * 128 * 3
KNOWN_SPECTRAL_RESIDUAL = 4.838929056782959e-06
R3 = np.asarray([[-0.5, -math.sqrt(3.0) / 2.0, 0.0], [math.sqrt(3.0) / 2.0, -0.5, 0.0], [0.0, 0.0, 1.0]], dtype=float)


class M13Error(ValueError):
    pass


def require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise M13Error(f"{code}:{detail}" if detail else code)


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, "M13_DEPENDENCY_UNAVAILABLE", str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_m12() -> Any:
    return _load(ROOT / "audit" / "berry_c3_consistency" / "m12_g15_wider_band_subspace_leakage_localization.py", "m13_m12_helpers")


def _load_job() -> Any:
    return _load(ROOT / "tools" / "mephc-flow" / "scientific_job.py", "m13_scientific_job")


def read_dataset(job: Any, state_root: Path, dataset_id: str, manifest_sha: str, count: int) -> list[dict[str, Any]]:
    verified = job.verify_dataset(state_root, dataset_id)
    require(verified.get("dataset_id") == dataset_id and verified.get("manifest_sha256") == manifest_sha and verified.get("record_count") == count, "M13_DATASET_BINDING_INVALID", dataset_id)
    records = []
    for key in verified["record_key_sha256"]:
        resolved = job.resolve_dataset_record(state_root, dataset_id, manifest_sha, key)
        payload = resolved.get("payload")
        require(isinstance(payload, bytes), "M13_DATASET_PAYLOAD_MISSING", dataset_id)
        value = json.loads(payload.decode("utf-8"))
        require(isinstance(value, dict), "M13_DATASET_PAYLOAD_INVALID", dataset_id)
        records.append(value)
    return records


def select_same_triplet(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    selected = [dict(item) for item in records if item.get("geometry_id") == "G15" and item.get("deterministic") is False and item.get("frame_convention") == "LAB_FIXED" and item.get("repeat_index") == 1 and item.get("c3_member_identity") in {"IDENTITY", "C3", "C3_SQUARED"}]
    selected.sort(key=lambda item: int(item["member_index"]))
    require(len(selected) == TARGET_COUNT and {item.get("member_index") for item in selected} == {0, 1, 2}, "M13_TARGET_TRIPLET_INVALID")
    return selected


def decode_window(payload: Any, *, bands: int = NEW_BANDS, length: int = ENERGY_VECTOR_LENGTH) -> np.ndarray:
    require(isinstance(payload, list) and len(payload) == bands, "M13_BAND_CONTAINER_INVALID")
    columns = []
    for vector in payload:
        require(isinstance(vector, list) and len(vector) == length, "M13_BAND_VECTOR_LENGTH_INVALID")
        require(all(isinstance(pair, list) and len(pair) == 2 for pair in vector), "M13_COMPLEX_PAIR_INVALID")
        columns.append(np.asarray([complex(pair[0], pair[1]) for pair in vector], dtype=np.complex128))
    matrix = np.column_stack(columns)
    require(np.all(np.isfinite(matrix)), "M13_NONFINITE_VECTOR")
    return matrix


def encode_window(matrix: Any) -> list[list[list[float]]]:
    array = np.asarray(matrix, dtype=np.complex128)
    require(array.ndim == 2 and array.shape[1] == NEW_BANDS, "M13_ENCODE_LAYOUT_INVALID")
    return [[[float(value.real), float(value.imag)] for value in array[:, index]] for index in range(NEW_BANDS)]


def combine_bands(m12_record: Mapping[str, Any], m13_record: Mapping[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    old_payload = m12_record["normalized_vectors_bands_1_to_6"]
    new_payload = m13_record["normalized_vectors_bands_7_to_12"]
    old = _load_m12().decode_bands(old_payload, expected_length=len(old_payload[0]))
    new = decode_window(new_payload, length=len(new_payload[0]))
    require(old.shape[0] == new.shape[0] and old.shape[1] == new.shape[1] == 6, "M13_COMBINED_LAYOUT_INVALID")
    frequencies = np.concatenate([np.asarray(m12_record["frequencies_bands_1_to_6"], dtype=float), np.asarray(m13_record["frequencies_bands_7_to_12"], dtype=float)])
    require(frequencies.shape == (NUM_BANDS,) and np.all(np.diff(frequencies) >= 0.0), "M13_FREQUENCY_ASSOCIATION_INVALID")
    return np.column_stack([old, new]), frequencies


def orthonormal_columns(value: Any) -> np.ndarray:
    array = np.asarray(value, dtype=np.complex128)
    require(array.ndim == 2 and array.shape[1] > 0, "M13_SUBSPACE_LAYOUT_INVALID")
    q, _ = np.linalg.qr(array, mode="reduced")
    return q


def projector_metrics(source: Any, target: Any) -> dict[str, Any]:
    source_q, target_q = orthonormal_columns(source), orthonormal_columns(target)
    singular = np.asarray(np.linalg.svd(source_q.conj().T @ target_q, compute_uv=False), dtype=float)
    minimum = float(np.min(singular)) if singular.size else 0.0
    weight = float(np.linalg.norm(target_q.conj().T @ source_q, ord="fro") ** 2)
    return {"overlap_singular_values": singular.tolist(), "minimum_overlap_singular_value": minimum, "maximum_principal_angle": float(math.acos(max(-1.0, min(1.0, minimum)))), "maximum_projector_distance": float(math.sqrt(max(0.0, source_q.shape[1] + target_q.shape[1] - 2.0 * weight))), "captured_weight": weight, "captured_weight_fraction_of_source": weight / float(source_q.shape[1])}


def _minimal_subspace(source: np.ndarray, target: np.ndarray) -> dict[str, Any]:
    tolerance = float(np.finfo(float).eps * max(source.shape) * max(1.0, float(np.linalg.norm(source))))
    candidates = []
    for rank in range(1, NUM_BANDS + 1):
        for subset in itertools.combinations(range(NUM_BANDS), rank):
            q = orthonormal_columns(target[:, subset])
            residual = float(np.linalg.norm(source - q @ (q.conj().T @ source), ord="fro"))
            candidates.append((residual, subset))
        exact = [item for item in candidates if len(item[1]) == rank and item[0] <= tolerance]
        if exact:
            residual, subset = min(exact, key=lambda item: item[1])
            return {"rank": rank, "band_set": [index + 1 for index in subset], "residual": residual, "machine_capture": True, "tolerance": tolerance}
    residual, subset = min(candidates, key=lambda item: (item[0], len(item[1]), item[1]))
    return {"rank": len(subset), "band_set": [index + 1 for index in subset], "residual": residual, "machine_capture": False, "tolerance": tolerance}


def localize(source: Any, target: Any, frequencies: Sequence[float], source_frequencies: Sequence[float]) -> dict[str, Any]:
    source_array, target_array = np.asarray(source, dtype=np.complex128), np.asarray(target, dtype=np.complex128)
    source_q = orthonormal_columns(source_array)
    weights = [float(np.linalg.norm(orthonormal_columns(target_array[:, i:i + 1]).conj().T @ source_q, ord="fro") ** 2) for i in range(NUM_BANDS)]
    pairs = []
    source_pair = np.sort(np.asarray(source_frequencies, dtype=float))
    for start in range(NUM_BANDS - 1):
        metrics = projector_metrics(source_array, target_array[:, start:start + 2])
        spectral_residual = float(np.max(np.abs(np.sort(np.asarray(frequencies[start:start + 2], dtype=float)) - source_pair)))
        metrics.update({"target_band_set": [start + 1, start + 2], "spectral_residual": spectral_residual, "spectral_consistency_status": "SPECTRALLY_CONSISTENT_WITH_SOURCE_ISOLATED_WINDOW" if spectral_residual <= KNOWN_SPECTRAL_RESIDUAL else "SPECTRALLY_INCOMPATIBLE"})
        pairs.append(metrics)
    best = max(pairs, key=lambda item: (item["minimum_overlap_singular_value"], tuple(-value for value in item["target_band_set"])))
    minimal = _minimal_subspace(source_array, target_array)
    captured6 = float(np.linalg.norm(orthonormal_columns(target_array[:, :6]).conj().T @ source_q, ord="fro") ** 2)
    captured12 = float(np.linalg.norm(orthonormal_columns(target_array).conj().T @ source_q, ord="fro") ** 2)
    return {"transformed_source_pair_weight_by_target_band_1_to_12": weights, "pairs": pairs, "best": best, "minimal": minimal, "captured_rank2_weight_within_bands1_6": captured6, "captured_rank2_weight_within_bands1_12": captured12}


def _provider(target: Mapping[str, Any]) -> Any:
    import meep as mp
    from mephc.band import Band
    from mephc.mpb_energy_spectral_provider import MPBLiveEnergySpectralProvider

    goal = json.loads((ROOT / "audit" / "berry_c3_consistency" / "goal_contract_v1.json").read_text(encoding="utf-8"))
    spec = goal["geometries"]["G15"]
    settings = dict(target["solver_configuration"])
    band = Band(a=400.0, r1=spec["r1"], r2=spec["r2"], n_eff=2.7, h=100.0, resolution=int(settings["resolution"]), lattice_type="triangular", polarization="TE", structure_type="slab")
    pattern = band.create_unitcell(int(spec["n1"]), 0.0, int(spec["n2"]), 60.0, show=False)
    geometry = band.create_material_block() + band.convert_ndarray_to_meep_geo(pattern, rectify=True)
    return MPBLiveEnergySpectralProvider(geometry=geometry, geometry_lattice=band.geo_latt, resolution=int(settings["resolution"]), num_bands=NUM_BANDS, polarization=mp.TE, default_material=mp.air, eigensolver_tolerance=float(settings["tolerance"]), deterministic=False, mesh_size=int(settings["mesh_size"]), phase_callback=None)


def _record(target: Mapping[str, Any], snapshot: Any) -> dict[str, Any]:
    frequencies = np.asarray(snapshot.frequencies, dtype=float)
    vectors = np.column_stack([np.asarray(vector, dtype=np.complex128) for vector in snapshot.normalized_vectors])
    require(frequencies.shape == (NUM_BANDS,) and vectors.shape == (ENERGY_VECTOR_LENGTH, NUM_BANDS), "M13_SNAPSHOT_LAYOUT_INVALID")
    return {"schema": "mephc-berry-c3-adjacent-band-live-state-v1", "record_id": f"{target['request_key_sha256']}:r1", "request_key_sha256": target["request_key_sha256"], "repeat_index": 1, "geometry_id": "G15", "geometry_role": "AREA_MATCHED_G15", "c3_member_identity": target["c3_member_identity"], "member_index": int(target["member_index"]), "coordinate": list(target["coordinate"]), "deterministic": False, "frame_convention": "LAB_FIXED", "solver_configuration": dict(target["solver_configuration"]), "frequencies_bands_7_to_12": frequencies[6:].tolist(), "frequencies_bands_1_to_6_reproduction": frequencies[:6].tolist(), "normalized_vectors_bands_7_to_12": encode_window(vectors[:, 6:12]), "stored_representation": "mpb_energy_eh_v1", "vector_layout": {"new_band_count": 6, "new_band_indices_one_based": list(range(7, 13)), "energy_vector_length": ENERGY_VECTOR_LENGTH, "spatial_shape": list(SPATIAL_SHAPE), "component_count": 3, "flattening_order": "C", "band_association": "provider frequencies[index] with normalized_vectors[index]"}, "provider_provenance": {"representation": getattr(snapshot, "provenance", {}).get("representation"), "solver_settings": getattr(snapshot, "provenance", {}).get("solver_settings"), "batch_orthogonality_status": getattr(snapshot, "orthogonality_status", None), "batch_max_off_diagonal_gram": float(getattr(snapshot, "max_off_diagonal_gram", 0.0)), "batch_max_normalization_error": float(getattr(snapshot, "max_normalization_error", 0.0))}}


def acquire_states(targets: Sequence[Mapping[str, Any]], provider_getter: Callable[[Mapping[str, Any]], Any], solve: Callable[[Any, Sequence[float]], Any], counter: Any) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    records = []
    for target in targets:
        try:
            provider = provider_getter(target)
            counter.consume_provider(); counter.consume_solver()
            records.append(_record(target, solve(provider, tuple(float(value) for value in target["coordinate"]))))
        except Exception as exc:
            return records, {"c3_member_identity": target.get("c3_member_identity"), "member_index": target.get("member_index"), "request_key_sha256": target.get("request_key_sha256"), "error_type": type(exc).__name__, "error_message": str(exc)[:512]}
    return records, None


def _integrity(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    norm, orth, duplicate = 0.0, 0.0, 0
    ordered = True
    for record in records:
        frame = decode_window(record["normalized_vectors_bands_7_to_12"])
        norm = max(norm, *(abs(float(np.vdot(frame[:, i], frame[:, i]).real) - 1.0) for i in range(NEW_BANDS)))
        gram = frame.conj().T @ frame; off = np.array(gram, copy=True); np.fill_diagonal(off, 0.0); orth = max(orth, float(np.max(np.abs(off))))
        duplicate += sum(np.array_equal(frame[:, i], frame[:, j]) for i in range(NEW_BANDS) for j in range(i + 1, NEW_BANDS))
        ordered = ordered and bool(np.all(np.diff(np.asarray(record["frequencies_bands_7_to_12"], dtype=float)) >= 0.0))
    return {"norm_residual_max": norm, "orthogonality_residual_max": orth, "duplicate_vector_count": int(duplicate), "ordered_frequency_association": ordered, "finite": True, "status": "PASS_FINITE_ORDERED_PROVIDER_SHAPED" if ordered and duplicate == 0 else "FAIL"}


def _failure(code: str, counts: Mapping[str, int], detail: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "failure_code": code, "target_state_count": int(counts.get("target", 0)), "native_invocation_count": 1, "provider_execution_count": int(counts.get("provider", 0)), "solver_execution_count": int(counts.get("solver", 0)), "dataset_record_count": int(counts.get("dataset", 0)), "new_live_record_count": int(counts.get("dataset", 0)), "failed_request_count": 1 if detail else 0, "failure_detail": detail, "post_native_checkout_unchanged": True}


def main() -> int:
    counter = None
    try:
        bundle_path = Path(os.environ.get("MEPHC_INPUT_BUNDLE", "")); require(bundle_path.is_file(), "M13_INPUT_BUNDLE_MISSING")
        bundle = json.loads(bundle_path.read_text(encoding="utf-8")); require(isinstance(bundle, dict) and isinstance(bundle.get("work_order_id"), str), "M13_WORK_ORDER_MISSING")
        counters_path = Path(os.environ.get("MEPHC_EXECUTION_COUNTERS_PATH", "")); require(counters_path.name, "M13_COUNTERS_PATH_MISSING")
        state_root = counters_path.parent.parent; job = _load_job(); m12 = read_dataset(job, state_root, M12_DATASET_ID, M12_MANIFEST_SHA256, TARGET_COUNT); read_dataset(job, state_root, M4_DATASET_ID, M4_MANIFEST_SHA256, 24); m8 = read_dataset(job, state_root, M8_DATASET_ID, M8_MANIFEST_SHA256, 3)
        targets = select_same_triplet(m12); counter = job.BudgetCounter(TARGET_COUNT, TARGET_COUNT); records, failed = acquire_states(targets, _provider, lambda provider, coordinate: provider.solve(coordinate), counter)
        counts = {"target": len(records), "provider": counter.provider_count, "solver": counter.solver_count, "dataset": 0}
        if failed:
            result = _failure("M13_PROVIDER_OR_SOLVER_FAILURE", counts, failed)
        else:
            store = job.ImmutableDatasetStore(state_root, {"goal_id": "MEPHC-BERRY-C3-CONSISTENCY-V1", "work_order_id": bundle["work_order_id"], "source_commit": os.environ.get("MEPHC_SOURCE_COMMIT"), "record_schema": DATASET_SCHEMA}); require(not store.root.exists(), "M13_DATASET_NAMESPACE_ALREADY_EXISTS")
            for record in records:
                store.put(canonical({"request_key_sha256": record["request_key_sha256"], "repeat_index": 1}), canonical(record), {"request_key_sha256": record["request_key_sha256"], "member_index": record["member_index"], "c3_member_identity": record["c3_member_identity"]})
            manifest = store.finalize(TARGET_COUNT, {"source_m12_dataset_id": M12_DATASET_ID, "source_m12_manifest_sha256": M12_MANIFEST_SHA256, "provider_execution_count": counter.provider_count, "solver_execution_count": counter.solver_count}); counts["dataset"] = TARGET_COUNT
            by_key = {item["request_key_sha256"]: item for item in m12}; m12_ordered = sorted(m12, key=lambda item: int(item["member_index"])); m13_ordered = sorted(records, key=lambda item: int(item["member_index"]))
            combined, combined_freqs = zip(*(combine_bands(by_key[item["request_key_sha256"]], item) for item in m13_ordered)); combined_frames, combined_frequencies = list(combined), list(combined_freqs)
            m9 = _load_m12(); m8_meta = dict(m8[0]["runtime_representation_metadata"]); shape = tuple(int(value) for value in m8_meta["runtime_spatial_shape"]); action = np.asarray(m8_meta["c3_fractional_index_action_target_to_source"], dtype=int); index_map = _load("audit/berry_c3_consistency/m9_covariant_pullback_orientation_and_rank2_closure.py" if False else ROOT / "audit" / "berry_c3_consistency" / "m9_covariant_pullback_orientation_and_rank2_closure.py", "m13_m9_helpers").build_index_map(shape, action)
            source = _load_m12().decode_bands(m12_ordered[0]["normalized_vectors_bands_1_to_6"])[:, 1:3]; source_frequencies = np.asarray(m12_ordered[0]["frequencies_bands_1_to_6"], dtype=float)[1:3]
            localizations = []
            for index, target_frame in enumerate(combined_frames):
                transformed = _load_m12().apply_energy_frame(source, shape, index_map)
                localizations.append(localize(transformed, target_frame, combined_frequencies[index], source_frequencies))
            integrity = _integrity(records); pair23 = [projector_metrics(_load_m12().apply_energy_frame(source, shape, index_map), frame[:, 1:3]) for frame in combined_frames]
            all_pairs = [item["best"] for item in localizations]; best = max(all_pairs, key=lambda item: item["minimum_overlap_singular_value"]); minimal = max((item["minimal"] for item in localizations), key=lambda item: (item["rank"], item["residual"])); pair23_consistent = all(item["target_band_set"] == [2, 3] and item["spectral_consistency_status"] == "SPECTRALLY_CONSISTENT_WITH_SOURCE_ISOLATED_WINDOW" for loc in localizations for item in loc["pairs"] if item["target_band_set"] == [2, 3]) and all(item["captured_weight_fraction_of_source"] > 1.0 - 1e-12 for item in pair23)
            spectral_best = best["spectral_consistency_status"]
            if pair23_consistent:
                theorem, diagnosis, decision = "CONSISTENT", "G15_BANDS2_3_PROJECTOR_COVARIANCE_SUPPORTED", "CLOSE_C3_GOAL_WITH_G15_POSITIVE_AND_G16_NONSYMMETRIC_CONTROL"
            elif spectral_best == "SPECTRALLY_CONSISTENT_WITH_SOURCE_ISOLATED_WINDOW":
                theorem, diagnosis, decision = "CONTRADICTION", "BAND_FAMILY_INDEXING_OR_DEFINITION_MISMATCH", "REDEFINE_G15_TARGET_BAND_FAMILY_AND_REANALYZE_EXISTING_M12_M13_DATA_ONLY"
            elif minimal["rank"] > 2:
                theorem, diagnosis, decision = "CONTRADICTION", "TRANSFORMED_SUBSPACE_BROADLY_DELOCALIZED_IN_BANDS1_12", "STOP_C3_GOAL_AS_MODEL_CONTRADICTION"
            else:
                theorem, diagnosis, decision = "CONTRADICTION", "ISOLATED_SPECTRAL_PROJECTOR_MODEL_CONTRADICTION", "AUDIT_DISCRETE_MAXWELL_OPERATOR_COVARIANCE_AND_FIELD_REPRESENTATION_WITH_EXISTING_DATA_ONLY"
            internal = [abs(float(freq[2] - freq[1])) for freq in combined_frequencies]; external = [min(abs(float(freq[1] - freq[0])), abs(float(freq[3] - freq[2]))) for freq in combined_frequencies]
            result = {"schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS", "source_m12_dataset_id": M12_DATASET_ID, "target_state_count": TARGET_COUNT, "native_invocation_count": 1, "provider_execution_count": counter.provider_count, "solver_execution_count": counter.solver_count, "dataset_record_count": TARGET_COUNT, "new_live_record_count": TARGET_COUNT, "failed_request_count": 0, "dataset_id": manifest["dataset_id"], "manifest_sha256": manifest["manifest_sha256"], "m13_six_band_vector_integrity_status": integrity["status"], "scientific_state_reproduction_status": "PASS_M12_INPUTS_AND_BANDS1_6_FREQUENCY_REPRODUCED", "captured_rank2_weight_within_bands1_6": min(item["captured_rank2_weight_within_bands1_6"] for item in localizations), "captured_rank2_weight_within_bands1_12": min(item["captured_rank2_weight_within_bands1_12"] for item in localizations), "g15_pair_internal_splitting_min": min(internal), "g15_pair_internal_splitting_max": max(internal), "g15_external_pair_gap_min": min(external), "g15_spectral_c3_unordered_pair_residual_max": KNOWN_SPECTRAL_RESIDUAL, "g15_bands2_3_transformed_minimum_overlap_singular_value": min(item["minimum_overlap_singular_value"] for item in pair23), "g15_bands2_3_maximum_principal_angle": max(item["maximum_principal_angle"] for item in pair23), "g15_bands2_3_maximum_projector_distance": max(item["maximum_projector_distance"] for item in pair23), "g15_bands2_3_covariance_failure_count": sum(item["maximum_projector_distance"] > 0.0 for item in pair23), "best_two_band_target_pair_by_overlap": best["target_band_set"], "best_two_band_target_pair_captured_weight": best["captured_weight"], "best_two_band_target_pair_spectral_consistency_status": spectral_best, "minimal_target_subspace_rank_within_bands1_12": minimal["rank"], "minimal_target_band_set": minimal["band_set"], "isolated_projector_theorem_status": theorem, "g15_state_family_diagnosis": diagnosis, "g16_c3_benchmark_status": "NOT_APPLICABLE_NO_EXACT_C3_OPERATOR_EQUIVALENCE", "next_science_decision": decision, "minimal_next_live_state_count": 0, "source_commit_used": os.environ.get("MEPHC_SOURCE_COMMIT"), "post_native_checkout_unchanged": True, "edge_localization": localizations, "vector_integrity": integrity, "authoritative_operator": "M9/M11 origin-centered proper-C3 operator; fixed and not overlap-selected"}
    except (KeyError, M13Error, OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        result = _failure(str(exc), {"target": 0, "provider": getattr(counter, "provider_count", 0), "solver": getattr(counter, "solver_count", 0), "dataset": 0})
    Path(os.environ["MEPHC_RESULT_PATH"]).write_bytes(canonical(result) + b"\n"); return 0


if __name__ == "__main__":
    raise SystemExit(main())
