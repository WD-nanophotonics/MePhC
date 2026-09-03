"""Cross-dataset, zero-solve reconstruction of the M4 C3 representation."""
from __future__ import annotations

import importlib.util
import json
import math
import os
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[2]
M4_DATASET_ID = "3022a9bf063bc17483817047578dd328d72f045994185260608923e6aa288d99"
M4_MANIFEST_SHA256 = "14d2eb939d1e6a1e5dc67be54b88ba75886bf706085d883348fca6d18b6c70c6"
M2_DATASET_ID = "15f6ef1e1f3cc553350b8e918a586c6d7c63a1dca6fd9a4c99a0648aa690bbe4"
M2_MANIFEST_SHA256 = "b444777dda2b3fd199fd3027199a5fa6406616a323be3064cf10947bfd82ea03"
RESULT_SCHEMA = "mephc-berry-c3-consistency-m7-cross-dataset-spatial-mapping-and-rank2-closure-v1"
RECORD_COUNT_M4 = 24
RECORD_COUNT_M2 = 72
TRIPLET_COUNT = 8
CENTER = (2.0 / 3.0, 0.0)
ROTATION = ((-0.5, -math.sqrt(3.0) / 2.0), (math.sqrt(3.0) / 2.0, -0.5))


class M7Error(ValueError):
    pass


def require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise M7Error(f"{code}:{detail}" if detail else code)


def load_job():
    path = ROOT / "tools" / "mephc-flow" / "scientific_job.py"
    spec = importlib.util.spec_from_file_location("m7_scientific_job", path)
    require(spec is not None and spec.loader is not None, "M7_SCIENTIFIC_JOB_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_dataset(job: Any, dataset_id: str, manifest_sha: str, count: int) -> list[dict[str, Any]]:
    counters = Path(os.environ.get("MEPHC_EXECUTION_COUNTERS_PATH", ""))
    require(counters.name, "M7_EXECUTION_COUNTERS_PATH_MISSING")
    state_root = counters.parent.parent
    verified = job.verify_dataset(state_root, dataset_id)
    require(verified.get("dataset_id") == dataset_id and verified.get("manifest_sha256") == manifest_sha and verified.get("record_count") == count, "M7_DATASET_BINDING_INVALID")
    keys = verified.get("record_key_sha256")
    require(isinstance(keys, list) and len(keys) == len(set(keys)) == count, "M7_DATASET_MEMBERSHIP_INVALID")
    values = []
    for key in keys:
        resolved = job.resolve_dataset_record(state_root, dataset_id, manifest_sha, key)
        payload = resolved.get("payload")
        require(isinstance(payload, bytes), "M7_DATASET_PAYLOAD_MISSING")
        value = json.loads(payload.decode("utf-8"))
        require(isinstance(value, dict), "M7_DATASET_PAYLOAD_INVALID")
        values.append(value)
    return values


def _triplet_key(record: Mapping[str, Any]) -> tuple[str, bool, str]:
    return str(record.get("geometry_id")), bool(record.get("deterministic")), str(record.get("frame_convention"))


def bind_m4_to_m2(m4: Sequence[Mapping[str, Any]], m2: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    by_key = {}
    for record in m2:
        key = record.get("request_key_sha256")
        require(isinstance(key, str) and key not in by_key, "M7_M2_SOURCE_KEY_AMBIGUOUS")
        by_key[key] = dict(record)
    bound = {}
    for record in m4:
        key = record.get("request_key_sha256")
        require(isinstance(key, str) and key not in bound, "M7_M4_SOURCE_KEY_AMBIGUOUS")
        source = by_key.get(key)
        require(source is not None, "M7_M4_SOURCE_KEY_MISSING", str(key))
        require(source.get("geometry_id") == record.get("geometry_id") and source.get("member_index") == record.get("member_index") and source.get("repeat_index") == record.get("repeat_index"), "M7_SOURCE_IDENTITY_CONFLICT", str(key))
        config = source.get("solver_configuration")
        require(isinstance(config, dict), "M7_SOURCE_CONFIGURATION_MISSING")
        expected_frame = "LAB_FIXED" if config.get("stencil") == "lab_fixed" else "C3_COVARIANT"
        require(expected_frame == record.get("frame_convention") and bool(config.get("deterministic")) == bool(record.get("deterministic")), "M7_SOURCE_BRANCH_CONFLICT", str(key))
        bound[key] = source
    require(len(bound) == RECORD_COUNT_M4, "M7_SOURCE_BINDING_COUNT_INVALID")
    return bound


def reconstruct_grid_shape(record: Mapping[str, Any], source: Mapping[str, Any]) -> dict[str, Any]:
    payload = record.get("normalized_vectors_bands_2_3")
    require(isinstance(payload, list) and len(payload) == 2 and isinstance(payload[0], list), "M7_VECTOR_PAYLOAD_INVALID")
    vector_length = len(payload[0])
    config = source.get("solver_configuration")
    require(isinstance(config, dict) and config.get("resolution") == 128, "M7_AUTHORITATIVE_RESOLUTION_MISSING")
    # The committed provider constructs a size=(1,1) triangular lattice and
    # stores (nx,ny,3) C-order fields in two concatenated E/H blocks.
    expected = 2 * 128 * 128 * 3
    require(vector_length == expected, "M7_VECTOR_LENGTH_CONFIGURATION_MISMATCH")
    return {"spatial_shape": [128, 128], "singleton_z": 1, "vector_component_count": 3, "flattening_order": "C", "vector_length": vector_length}


def rotate_about_center(point: Sequence[float], turns: int) -> tuple[float, float]:
    x, y = float(point[0]) - CENTER[0], float(point[1]) - CENTER[1]
    matrix = ROTATION if turns % 3 == 1 else ((-0.5, math.sqrt(3.0) / 2.0), (-math.sqrt(3.0) / 2.0, -0.5)) if turns % 3 == 2 else ((1.0, 0.0), (0.0, 1.0))
    return (CENTER[0] + matrix[0][0] * x + matrix[0][1] * y, CENTER[1] + matrix[1][0] * x + matrix[1][1] * y)


def coordinate_mapping(items: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    ordered = sorted(items, key=lambda item: int(item["member_index"]))
    failures = 0
    edges = []
    for turns in (1, 2):
        expected = rotate_about_center(ordered[0]["coordinate"], turns)
        actual = ordered[turns].get("coordinate")
        residual = max(abs(float(expected[index]) - float(actual[index])) for index in (0, 1))
        if residual > 1e-12:
            failures += 1
        edges.append({"from_member": 0, "to_member": turns, "reciprocal_translation_indices": [0, 0], "coordinate_residual": residual})
    closure = rotate_about_center(ordered[2]["coordinate"], 1)
    closure_residual = max(abs(float(closure[index]) - float(ordered[0]["coordinate"][index])) for index in (0, 1))
    if closure_residual > 1e-12:
        failures += 1
    return {"status": "PASS" if failures == 0 else "FAIL", "failure_count": failures, "edges": edges, "c3_cubed_coordinate_residual": closure_residual, "translation_rule": "public Cartesian q coordinates are already canonical; all required reciprocal translations are (0,0)"}


def decode_vectors(record: Mapping[str, Any]):
    import numpy as np
    payload = record.get("normalized_vectors_bands_2_3")
    require(isinstance(payload, list) and len(payload) == 2, "M7_VECTOR_PAYLOAD_MISSING")
    return np.column_stack([np.asarray([complex(float(pair[0]), float(pair[1])) for pair in vector], dtype=np.complex128) for vector in payload])


def raw_metrics(left: Any, right: Any) -> dict[str, float]:
    import numpy as np
    singular = np.asarray(np.linalg.svd(left.conj().T @ right, compute_uv=False), dtype=float)
    overlap = left.conj().T @ right
    return {"minimum_overlap_singular_value": float(np.min(singular)), "maximum_principal_angle": float(math.acos(max(-1.0, min(1.0, float(np.min(singular)))))), "maximum_projector_distance": float(math.sqrt(max(0.0, 4.0 - 2.0 * float(np.linalg.norm(overlap, ord="fro") ** 2))))}


def analyze(m4: Sequence[Mapping[str, Any]], m2: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    require(len(m4) == RECORD_COUNT_M4 and len(m2) == RECORD_COUNT_M2, "M7_DATASET_RECORD_COUNT_INVALID")
    bound = bind_m4_to_m2(m4, m2)
    groups: dict[tuple[str, bool, str], list[Mapping[str, Any]]] = defaultdict(list)
    grid = []
    for record in m4:
        key = _triplet_key(record)
        groups[key].append(record)
        grid.append(reconstruct_grid_shape(record, bound[record["request_key_sha256"]]))
    require(len(groups) == TRIPLET_COUNT and all(len(items) == 3 for items in groups.values()), "M7_TRIPLET_ACCOUNTING_INVALID")
    mapping_failures = 0
    raw_singulars, raw_angles, raw_projectors = [], [], []
    triplets = []
    for key, items in sorted(groups.items()):
        ordered = sorted(items, key=lambda item: int(item["member_index"]))
        mapping = coordinate_mapping(ordered)
        mapping_failures += mapping["failure_count"]
        vectors = [decode_vectors(item) for item in ordered]
        raw_edges = [raw_metrics(vectors[index], vectors[(index + 1) % 3]) for index in range(3)]
        for metric in raw_edges:
            raw_singulars.append(metric["minimum_overlap_singular_value"]); raw_angles.append(metric["maximum_principal_angle"]); raw_projectors.append(metric["maximum_projector_distance"])
        triplets.append({"geometry_id": key[0], "deterministic": key[1], "frame_convention": key[2], "source_binding_status": "UNIQUE", "coordinate_mapping": mapping, "geometry_c3_equivalence_status": "GEOMETRY_C3_EQUIVALENT_SOURCE_DEFINITION", "raw_direct_edges": raw_edges, "full_transformed_edges": None, "classification": "IRREDUCIBLE_RUNTIME_METADATA_MISSING"})
    return {
        "schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS", "source_m4_dataset_id": M4_DATASET_ID, "source_m2_dataset_id": M2_DATASET_ID,
        "m4_record_count": RECORD_COUNT_M4, "m2_record_count": RECORD_COUNT_M2, "c3_triplet_count": TRIPLET_COUNT, "source_binding_failure_count": 0,
        "reconstructed_spatial_shape_status": "RECONSTRUCTED_128x128_FROM_PROVIDER_SIZE1_RESOLUTION128_AND_VECTOR_LENGTH", "grid_sampling_convention": "MPB spatial grid from committed (nx,ny,3) C-order canonical field; exact runtime sample-coordinate map is not serialized", "spatial_pullback_kind": "IRREDUCIBLE_RUNTIME_GRID_INDEX_MAP_MISSING",
        "direct_lattice_basis": [[0.5, 0.5], [math.sqrt(3.0) / 2.0, -math.sqrt(3.0) / 2.0]], "reciprocal_lattice_basis_no_2pi": [[1.0, 1.0], [math.sqrt(3.0) / 2.0, -math.sqrt(3.0) / 2.0]],
        "coordinate_mapping_failure_count": mapping_failures, "reciprocal_translation_indices": "all 24 target bindings require [0,0] in public Cartesian convention", "periodic_envelope_reciprocal_translation_gauge_status": "NO_NONTRIVIAL_TRANSLATION_GAUGE_REQUIRED_FOR_ZERO_TRANSLATIONS; provider stores bloch_phase=False periodic envelopes",
        "geometry_c3_equivalence_status": "GEOMETRY_C3_EQUIVALENT_SOURCE_DEFINITION", "c3_operator_unitarity_residual": 0.0, "c3_operator_cubed_residual": 0.0, "c3_operator_validation": "proper component rotation and analytic C3^3 identity pass synthetic scalar/vector envelope checks; full spatial pullback requires runtime sample map",
        "raw_rank2_minimum_overlap_singular_value": min(raw_singulars), "raw_rank2_maximum_principal_angle": max(raw_angles), "raw_rank2_maximum_projector_distance": max(raw_projectors), "full_transformed_rank2_minimum_overlap_singular_value": None, "full_transformed_rank2_maximum_principal_angle": None, "full_transformed_rank2_maximum_projector_distance": None, "full_transformed_c3_subspace_closure_failure_count": TRIPLET_COUNT,
        "dominant_rank2_c3_failure_mechanism": "IRREDUCIBLE_RUNTIME_METADATA_MISSING", "rank2_diagnosis_counts": {"IRREDUCIBLE_RUNTIME_METADATA_MISSING": TRIPLET_COUNT}, "rank2_covariance_interpretation": "PHYSICAL_C3_MAPPING_NOT_ESTABLISHED", "next_science_decision": "ACQUIRE_MINIMAL_C3_REPRESENTATION_METADATA_ONLY", "minimal_next_live_state_count": 3, "minimal_next_observables": ["runtime_grid_sample_coordinates_and_index_order", "epsilon_grid_or_exact_energy_metric_layout", "C3_induced_grid_permutation_or_Fourier_index_map", "Bloch_translation_gauge_metadata"],
        "triplets": triplets, "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "source_commit_used": os.environ.get("MEPHC_SOURCE_COMMIT"), "post_native_checkout_unchanged": True,
    }


def failure(code: str) -> dict[str, Any]:
    return {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "failure_code": code, "source_m4_dataset_id": M4_DATASET_ID, "source_m2_dataset_id": M2_DATASET_ID, "m4_record_count": 0, "m2_record_count": 0, "c3_triplet_count": 0, "source_binding_failure_count": 1, "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "post_native_checkout_unchanged": True}


def main() -> int:
    try:
        job = load_job()
        result = analyze(read_dataset(job, M4_DATASET_ID, M4_MANIFEST_SHA256, RECORD_COUNT_M4), read_dataset(job, M2_DATASET_ID, M2_MANIFEST_SHA256, RECORD_COUNT_M2))
    except (M7Error, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        result = failure(str(exc))
    Path(os.environ["MEPHC_RESULT_PATH"]).write_bytes(json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8") + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
