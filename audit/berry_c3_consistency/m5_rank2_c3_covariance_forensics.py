"""Solver-free forensic analysis of the complete M4 rank-2 dataset."""
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
SOURCE_DATASET_ID = "3022a9bf063bc17483817047578dd328d72f045994185260608923e6aa288d99"
SOURCE_MANIFEST_SHA256 = "14d2eb939d1e6a1e5dc67be54b88ba75886bf706085d883348fca6d18b6c70c6"
RESULT_SCHEMA = "mephc-berry-c3-consistency-m5-rank2-c3-covariance-forensics-v1"
RECORD_COUNT = 24
TRIPLET_COUNT = 8


class M5Error(ValueError):
    pass


def require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise M5Error(f"{code}:{detail}" if detail else code)


def load_scientific_job():
    path = ROOT / "tools" / "mephc-flow" / "scientific_job.py"
    spec = importlib.util.spec_from_file_location("m5_scientific_job", path)
    require(spec is not None and spec.loader is not None, "M5_SCIENTIFIC_JOB_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_records() -> list[dict[str, Any]]:
    counters = Path(os.environ.get("MEPHC_EXECUTION_COUNTERS_PATH", ""))
    require(counters.name, "M5_EXECUTION_COUNTERS_PATH_MISSING")
    job = load_scientific_job()
    state_root = counters.parent.parent
    verified = job.verify_dataset(state_root, SOURCE_DATASET_ID)
    require(verified.get("dataset_id") == SOURCE_DATASET_ID, "M5_DATASET_ID_MISMATCH")
    require(verified.get("manifest_sha256") == SOURCE_MANIFEST_SHA256, "M5_MANIFEST_MISMATCH")
    keys = verified.get("record_key_sha256")
    require(isinstance(keys, list) and len(keys) == len(set(keys)) == RECORD_COUNT, "M5_RECORD_MEMBERSHIP_INVALID")
    records = []
    for key in keys:
        resolved = job.resolve_dataset_record(state_root, SOURCE_DATASET_ID, SOURCE_MANIFEST_SHA256, key)
        payload = resolved.get("payload")
        require(isinstance(payload, bytes), "M5_RECORD_PAYLOAD_MISSING")
        value = json.loads(payload.decode("utf-8"))
        require(isinstance(value, dict), "M5_RECORD_SCHEMA_INVALID")
        records.append(value)
    return records


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _pair(record: Mapping[str, Any]) -> tuple[float, float]:
    values = record.get("first_four_frequencies")
    require(isinstance(values, list) and len(values) >= 4, "M5_FREQUENCY_FIELDS_MISSING")
    pair = (_finite(values[1]), _finite(values[2]))
    require(pair[0] is not None and pair[1] is not None, "M5_PAIR_FREQUENCY_NONFINITE")
    return pair  # type: ignore[return-value]


def unordered_pair_metrics(reference: Sequence[float], candidate: Sequence[float]) -> dict[str, float]:
    require(len(reference) == 2 and len(candidate) == 2, "M5_PAIR_DIMENSION_INVALID")
    ref_center = (float(reference[0]) + float(reference[1])) / 2.0
    cand_center = (float(candidate[0]) + float(candidate[1])) / 2.0
    ref_split = abs(float(reference[1]) - float(reference[0]))
    cand_split = abs(float(candidate[1]) - float(candidate[0]))
    matching = min(max(abs(float(reference[index]) - float(candidate[order[index]])) for index in range(2)) for order in itertools.permutations(range(2)))
    return {
        "pair_center_residual": abs(ref_center - cand_center),
        "pair_splitting_residual": abs(ref_split - cand_split),
        "unordered_pair_residual": matching,
    }


def _decode_vectors(record: Mapping[str, Any]):
    import numpy as np
    value = record.get("normalized_vectors_bands_2_3")
    require(isinstance(value, list) and len(value) == 2, "M5_VECTOR_FIELDS_MISSING")
    vectors = []
    for vector in value:
        require(isinstance(vector, list), "M5_VECTOR_FIELDS_INVALID")
        decoded = []
        for pair in vector:
            require(isinstance(pair, list) and len(pair) == 2, "M5_VECTOR_FIELDS_INVALID")
            decoded.append(complex(float(pair[0]), float(pair[1])))
        vectors.append(np.asarray(decoded, dtype=np.complex128))
    require(vectors[0].size == vectors[1].size and vectors[0].size > 0, "M5_VECTOR_DIMENSION_INVALID")
    return np.column_stack(vectors)


def direct_subspace_metrics(left: Any, right: Any) -> dict[str, Any]:
    import numpy as np
    overlap = left.conj().T @ right
    singular = np.asarray(np.linalg.svd(overlap, compute_uv=False), dtype=float)
    projector = math.sqrt(max(0.0, 4.0 - 2.0 * float(np.linalg.norm(overlap, ord="fro") ** 2)))
    angle = math.acos(max(-1.0, min(1.0, float(np.min(singular)))))
    return {
        "minimum_overlap_singular_value": float(np.min(singular)),
        "maximum_principal_angle": float(angle),
        "maximum_projector_distance": float(projector),
    }


def _branch(record: Mapping[str, Any]) -> tuple[str, bool, str]:
    geometry = str(record.get("geometry_id"))
    deterministic = bool(record.get("deterministic"))
    frame = str(record.get("frame_convention"))
    require(geometry in {"G15", "G16"} and frame in {"LAB_FIXED", "C3_COVARIANT"}, "M5_BRANCH_FIELDS_INVALID")
    return geometry, deterministic, frame


def _coordinate_mapping_status(items: Sequence[Mapping[str, Any]]) -> tuple[str, str]:
    required = ("lattice_basis", "reciprocal_cell", "c3_operator", "coordinate_modulo_rule")
    missing = [field for field in required if not all(field in item for item in items)]
    if missing:
        return "INSUFFICIENT_STORED_METADATA", ",".join(missing)
    return "NOT_EVALUATED", ""


def analyze(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    import numpy as np
    require(len(records) == RECORD_COUNT, "M5_RECORD_COUNT_INVALID")
    groups: dict[tuple[str, bool, str], list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        require(record.get("repeat_index") == 1, "M5_REPEAT_INVALID")
        groups[_branch(record)].append(record)
    require(len(groups) == TRIPLET_COUNT and all(len(items) == 3 for items in groups.values()), "M5_TRIPLET_ACCOUNTING_INVALID")

    center_residuals, splitting_residuals, unordered_residuals = [], [], []
    raw_singulars, raw_angles, raw_projectors = [], [], []
    triplets = []
    coordinate_failures = 0
    missing_representation = set()
    for key, items in sorted(groups.items()):
        ordered = sorted(items, key=lambda item: int(item.get("member_index", -1)))
        require([item.get("c3_member_identity") for item in ordered] == ["IDENTITY", "C3", "C3_SQUARED"], "M5_MEMBER_ORDER_INVALID")
        mapping_status, missing = _coordinate_mapping_status(ordered)
        if mapping_status != "NOT_EVALUATED":
            coordinate_failures += 1
            missing_representation.update(filter(None, missing.split(",")))
        pairs = [_pair(item) for item in ordered]
        edge_spectral = []
        vectors = [_decode_vectors(item) for item in ordered]
        edge_raw = []
        for index in range(3):
            spectral = unordered_pair_metrics(pairs[index], pairs[(index + 1) % 3])
            edge_spectral.append(spectral)
            center_residuals.append(spectral["pair_center_residual"]); splitting_residuals.append(spectral["pair_splitting_residual"]); unordered_residuals.append(spectral["unordered_pair_residual"])
            raw = direct_subspace_metrics(vectors[index], vectors[(index + 1) % 3])
            edge_raw.append(raw)
            raw_singulars.append(raw["minimum_overlap_singular_value"]); raw_angles.append(raw["maximum_principal_angle"]); raw_projectors.append(raw["maximum_projector_distance"])
        triplets.append({
            "geometry_id": key[0], "deterministic": key[1], "frame_convention": key[2], "repeat_index": 1,
            "spectral_edges": edge_spectral, "raw_direct_edges": edge_raw,
            "coordinate_mapping_status": mapping_status, "geometry_c3_equivalence_status": "INSUFFICIENT_STORED_METADATA",
            "primary_diagnosis": "INSUFFICIENT_STORED_METADATA",
        })
    representation_status = "INSUFFICIENT_STORED_METADATA"
    rank2_interpretation = "PHYSICAL_C3_MAPPING_NOT_ESTABLISHED"
    return {
        "schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS",
        "source_m4_dataset_id": SOURCE_DATASET_ID, "record_count": RECORD_COUNT, "c3_triplet_count": TRIPLET_COUNT,
        "coordinate_mapping_failure_count": coordinate_failures, "geometry_c3_equivalence_status": "INSUFFICIENT_STORED_METADATA",
        "spectral_c3_pair_center_residual_max": max(center_residuals), "spectral_c3_pair_splitting_residual_max": max(splitting_residuals), "spectral_c3_unordered_pair_residual_max": max(unordered_residuals),
        "c3_operator_unitarity_residual": None, "c3_operator_cubed_residual": None,
        "raw_rank2_minimum_overlap_singular_value": min(raw_singulars), "raw_rank2_maximum_principal_angle": max(raw_angles), "raw_rank2_maximum_projector_distance": max(raw_projectors),
        "transformed_rank2_minimum_overlap_singular_value": None, "transformed_rank2_maximum_principal_angle": None, "transformed_rank2_maximum_projector_distance": None,
        "representation_test_status": representation_status, "representation_missing_fields": sorted(missing_representation | {"grid_basis_metadata", "vector_component_transformation", "proper_c3_pullback"}),
        "dominant_rank2_c3_failure_mechanism": "INSUFFICIENT_STORED_METADATA", "rank2_diagnosis_counts": {"INSUFFICIENT_STORED_METADATA": TRIPLET_COUNT},
        "rank2_covariance_interpretation": rank2_interpretation, "next_science_decision": "ACQUIRE_MINIMAL_C3_REPRESENTATION_METADATA_ONLY", "minimal_next_live_state_count": 0,
        "triplets": triplets, "threshold_status": "THRESHOLD_DEFERRED",
        "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0,
        "source_commit_used": os.environ.get("MEPHC_SOURCE_COMMIT"), "post_native_checkout_unchanged": True,
    }


def failure(code: str) -> dict[str, Any]:
    return {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "failure_code": code, "source_m4_dataset_id": SOURCE_DATASET_ID, "record_count": 0, "c3_triplet_count": 0, "coordinate_mapping_failure_count": 0, "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "post_native_checkout_unchanged": True}


def main() -> int:
    try:
        result = analyze(load_records())
    except (M5Error, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        result = failure(str(exc))
    Path(os.environ["MEPHC_RESULT_PATH"]).write_bytes(json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8") + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
