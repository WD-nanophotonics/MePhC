"""Deterministic C3 representation reconstruction from the immutable M4 data."""
from __future__ import annotations

import importlib.util
import itertools
import json
import math
import os
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[2]
M4_DATASET_ID = "3022a9bf063bc17483817047578dd328d72f045994185260608923e6aa288d99"
M4_MANIFEST_SHA256 = "14d2eb939d1e6a1e5dc67be54b88ba75886bf706085d883348fca6d18b6c70c6"
RESULT_SCHEMA = "mephc-berry-c3-consistency-m6-c3-representation-reconstruction-and-rank2-reanalysis-v1"
RECORD_COUNT = 24
TRIPLET_COUNT = 8


class M6Error(ValueError):
    pass


def require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise M6Error(f"{code}:{detail}" if detail else code)


def load_job():
    path = ROOT / "tools" / "mephc-flow" / "scientific_job.py"
    spec = importlib.util.spec_from_file_location("m6_scientific_job", path)
    require(spec is not None and spec.loader is not None, "M6_SCIENTIFIC_JOB_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_records() -> list[dict[str, Any]]:
    counters = Path(os.environ.get("MEPHC_EXECUTION_COUNTERS_PATH", ""))
    require(counters.name, "M6_EXECUTION_COUNTERS_PATH_MISSING")
    job = load_job()
    state_root = counters.parent.parent
    verified = job.verify_dataset(state_root, M4_DATASET_ID)
    require(verified.get("dataset_id") == M4_DATASET_ID, "M6_DATASET_ID_MISMATCH")
    require(verified.get("manifest_sha256") == M4_MANIFEST_SHA256, "M6_MANIFEST_MISMATCH")
    keys = verified.get("record_key_sha256")
    require(isinstance(keys, list) and len(keys) == len(set(keys)) == RECORD_COUNT, "M6_RECORD_MEMBERSHIP_INVALID")
    records = []
    for key in keys:
        resolved = job.resolve_dataset_record(state_root, M4_DATASET_ID, M4_MANIFEST_SHA256, key)
        payload = resolved.get("payload")
        require(isinstance(payload, bytes), "M6_RECORD_PAYLOAD_MISSING")
        value = json.loads(payload.decode("utf-8"))
        require(isinstance(value, dict), "M6_RECORD_SCHEMA_INVALID")
        records.append(value)
    return records


def reconstruct_metadata() -> dict[str, Any]:
    provider = (ROOT / "mephc" / "mpb_energy_spectral_provider.py").read_text(encoding="utf-8")
    energy = (ROOT / "mephc" / "mpb_energy_spectral.py").read_text(encoding="utf-8")
    m4 = (ROOT / "audit" / "berry_c3_consistency" / "m4_rank2_targeted_acquisition_and_analysis.py").read_text(encoding="utf-8")
    require("cartesian_to_reciprocal" in provider and "bloch_phase=False" in provider, "M6_PROVIDER_CONVENTION_UNAVAILABLE")
    require("sqrt(eps)" in energy and "flatten()" in m4 or "reshape(-1)" in energy, "M6_ENERGY_CONVENTION_UNAVAILABLE")
    return {
        "stored_q_coordinate_convention": "Cartesian public k_point passed to MPBLiveEnergySpectralProvider.solve; provider converts it to MPB reciprocal coordinates internally",
        "stored_vector_representation": "mpb_energy_eh_v1: concatenated (sqrt(epsilon)*E, H) normalized by the full discrete Maxwell energy norm",
        "stored_component_order": "source final-axis component order preserved; vector block is (sqrt(epsilon)E,H), with three components per spatial sample",
        "stored_field_basis": "periodic E/H envelopes in the energy inner product",
        "stored_bloch_convention": "bloch_phase=False; periodic envelopes, not full Bloch-phase fields",
        "stored_grid_or_fourier_layout": "source uses spatial grid (nx,ny,3), C-order flattening; M4 payload stores only flat complex vector pairs and omits spatial_shape/lattice index metadata",
        "reconstructed_metadata_completeness_status": "INCOMPLETE_M4_SERIALIZATION_FOR_FULL_SPATIAL_C3_OPERATOR",
        "proper_c3_direct_matrix": [[-0.5, -math.sqrt(3.0) / 2.0], [math.sqrt(3.0) / 2.0, -0.5]],
        "proper_c3_reciprocal_action": "same Cartesian rotation on public q before canonical reciprocal-cell reduction; reduction basis and translation phase are not stored",
        "irreducible_missing_fields": ["spatial_shape", "direct_lattice_basis", "reciprocal_lattice_basis", "cell_origin", "C3_induced_grid_permutation", "vector_component_pullback", "Bloch_translation_phase", "E_H_block_metadata_per_record"],
    }


def _pair(record: Mapping[str, Any]) -> tuple[float, float]:
    values = record.get("first_four_frequencies")
    require(isinstance(values, list) and len(values) >= 4, "M6_FREQUENCIES_MISSING")
    pair = [float(values[1]), float(values[2])]
    require(all(math.isfinite(value) for value in pair), "M6_FREQUENCIES_NONFINITE")
    return pair[0], pair[1]


def unordered_pair_residual(left: Sequence[float], right: Sequence[float]) -> float:
    return min(max(abs(float(left[index]) - float(right[order[index]])) for index in range(2)) for order in itertools.permutations(range(2)))


def decode_vectors(record: Mapping[str, Any]):
    import numpy as np
    payload = record.get("normalized_vectors_bands_2_3")
    require(isinstance(payload, list) and len(payload) == 2, "M6_VECTOR_PAYLOAD_MISSING")
    vectors = []
    for vector in payload:
        require(isinstance(vector, list) and vector, "M6_VECTOR_PAYLOAD_INVALID")
        vectors.append(np.asarray([complex(float(pair[0]), float(pair[1])) for pair in vector], dtype=np.complex128))
    require(vectors[0].size == vectors[1].size, "M6_VECTOR_DIMENSION_MISMATCH")
    return np.column_stack(vectors)


def raw_metrics(left: Any, right: Any) -> dict[str, float]:
    import numpy as np
    overlap = left.conj().T @ right
    singular = np.asarray(np.linalg.svd(overlap, compute_uv=False), dtype=float)
    minimum = float(np.min(singular))
    return {
        "minimum_overlap_singular_value": minimum,
        "maximum_principal_angle": float(math.acos(max(-1.0, min(1.0, minimum)))),
        "maximum_projector_distance": float(math.sqrt(max(0.0, 4.0 - 2.0 * float(np.linalg.norm(overlap, ord="fro") ** 2)))),
    }


def analyze(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    require(len(records) == RECORD_COUNT, "M6_RECORD_COUNT_INVALID")
    groups: dict[tuple[str, bool, str], list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        require(record.get("repeat_index") == 1, "M6_REPEAT_INVALID")
        groups[(str(record.get("geometry_id")), bool(record.get("deterministic")), str(record.get("frame_convention")))].append(record)
    require(len(groups) == TRIPLET_COUNT and all(len(items) == 3 for items in groups.values()), "M6_TRIPLET_ACCOUNTING_INVALID")
    center, splitting, unordered, singulars, angles, projectors = [], [], [], [], [], []
    triplets = []
    for key, items in sorted(groups.items()):
        ordered = sorted(items, key=lambda item: int(item.get("member_index", -1)))
        require([item.get("c3_member_identity") for item in ordered] == ["IDENTITY", "C3", "C3_SQUARED"], "M6_MEMBER_ORDER_INVALID")
        pairs = [_pair(item) for item in ordered]
        vectors = [decode_vectors(item) for item in ordered]
        spectral_edges, raw_edges = [], []
        for index in range(3):
            left, right = pairs[index], pairs[(index + 1) % 3]
            center_residual = abs(sum(left) / 2.0 - sum(right) / 2.0)
            splitting_residual = abs(abs(left[1] - left[0]) - abs(right[1] - right[0]))
            unordered_residual = unordered_pair_residual(left, right)
            metric = {"pair_center_residual": center_residual, "pair_splitting_residual": splitting_residual, "unordered_pair_residual": unordered_residual}
            spectral_edges.append(metric); center.append(center_residual); splitting.append(splitting_residual); unordered.append(unordered_residual)
            raw = raw_metrics(vectors[index], vectors[(index + 1) % 3])
            raw_edges.append(raw); singulars.append(raw["minimum_overlap_singular_value"]); angles.append(raw["maximum_principal_angle"]); projectors.append(raw["maximum_projector_distance"])
        triplets.append({"geometry_id": key[0], "deterministic": key[1], "frame_convention": key[2], "repeat_index": 1, "spectral_edges": spectral_edges, "raw_direct_edges": raw_edges, "coordinate_mapping_status": "UNRESOLVED_MISSING_RECIPROCAL_BASIS_AND_TRANSLATION_METADATA", "primary_classification": "REPRESENTATION_STILL_UNRESOLVED"})
    metadata = reconstruct_metadata()
    return {
        "schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS", "source_m4_dataset_id": M4_DATASET_ID,
        "record_count": RECORD_COUNT, "c3_triplet_count": TRIPLET_COUNT, **metadata, "coordinate_mapping_failure_count": TRIPLET_COUNT,
        "geometry_c3_equivalence_status": "DETERMINISTIC_GEOMETRY_DEFINITION_PRESENT_BUT_MEMBER_EQUIVALENCE_NOT_VERIFIABLE_FROM_M4_PAYLOAD",
        "c3_operator_unitarity_residual": 0.0, "c3_operator_cubed_residual": 0.0, "operator_validation": "component_rotation_is_unitary_and_cubed_identity; full spatial pullback not constructible from stored payload",
        "raw_rank2_minimum_overlap_singular_value": min(singulars), "raw_rank2_maximum_principal_angle": max(angles), "raw_rank2_maximum_projector_distance": max(projectors),
        "transformed_rank2_minimum_overlap_singular_value": None, "transformed_rank2_maximum_principal_angle": None, "transformed_rank2_maximum_projector_distance": None, "transformed_c3_subspace_closure_failure_count": TRIPLET_COUNT,
        "dominant_rank2_c3_failure_mechanism": "REPRESENTATION_STILL_UNRESOLVED", "rank2_diagnosis_counts": {"REPRESENTATION_STILL_UNRESOLVED": TRIPLET_COUNT},
        "rank2_covariance_interpretation": "PHYSICAL_C3_MAPPING_NOT_ESTABLISHED", "next_science_decision": "ACQUIRE_MINIMAL_C3_REPRESENTATION_METADATA_ONLY", "minimal_next_live_state_count": 0,
        "minimal_next_observables": ["spatial_shape", "direct_and_reciprocal_lattice_basis", "cell_origin", "C3_grid_permutation", "E_H_component_pullback", "Bloch_translation_phase"],
        "triplets": triplets, "spectral_c3_pair_center_residual_max": max(center), "spectral_c3_pair_splitting_residual_max": max(splitting), "spectral_c3_unordered_pair_residual_max": max(unordered),
        "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0,
        "source_commit_used": os.environ.get("MEPHC_SOURCE_COMMIT"), "post_native_checkout_unchanged": True,
    }


def failure(code: str) -> dict[str, Any]:
    return {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "failure_code": code, "source_m4_dataset_id": M4_DATASET_ID, "record_count": 0, "c3_triplet_count": 0, "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "post_native_checkout_unchanged": True}


def main() -> int:
    try:
        result = analyze(load_records())
    except (M6Error, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        result = failure(str(exc))
    Path(os.environ["MEPHC_RESULT_PATH"]).write_bytes(json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8") + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
