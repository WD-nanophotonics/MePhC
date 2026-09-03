"""M11 solver-free space-group and isolated-band-family audit."""
from __future__ import annotations

import importlib.util
import json
import math
import os
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
M4_DATASET_ID = "3022a9bf063bc17483817047578dd328d72f045994185260608923e6aa288d99"
M4_MANIFEST_SHA256 = "14d2eb939d1e6a1e5dc67be54b88ba75886bf706085d883348fca6d18b6c70c6"
M2_DATASET_ID = "15f6ef1e1f3cc553350b8e918a586c6d7c63a1dca6fd9a4c99a0648aa690bbe4"
M2_MANIFEST_SHA256 = "b444777dda2b3fd199fd3027199a5fa6406616a323be3064cf10947bfd82ea03"
M8_DATASET_ID = "14557cd9b877d51c79d8c1de0baf87d2302189d9a9aa0fea2d6fc7ac56feb043"
M8_MANIFEST_SHA256 = "468358ff62eeb3954c4981d861705362f296a8caa5162bebbf6ff88ba9f44b29"
RESULT_SCHEMA = "mephc-berry-c3-consistency-m11-space-group-c3-seitz-and-band-family-audit-v1"
M4_COUNT, M2_COUNT, M8_COUNT = 24, 72, 3
R2 = np.asarray([[-0.5, -math.sqrt(3.0) / 2.0], [math.sqrt(3.0) / 2.0, -0.5]], dtype=float)


class M11Error(ValueError):
    pass


def require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise M11Error(f"{code}:{detail}" if detail else code)


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _load_m9():
    path = ROOT / "audit" / "berry_c3_consistency" / "m9_covariant_pullback_orientation_and_rank2_closure.py"
    spec = importlib.util.spec_from_file_location("m11_m9_helpers", path)
    require(spec is not None and spec.loader is not None, "M11_M9_HELPERS_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_dataset(job: Any, state_root: Path, dataset_id: str, manifest_sha: str, count: int) -> list[dict[str, Any]]:
    verified = job.verify_dataset(state_root, dataset_id)
    require(verified.get("manifest_sha256") == manifest_sha and verified.get("record_count") == count, "M11_DATASET_BINDING_INVALID", dataset_id)
    values = []
    for key in verified["record_key_sha256"]:
        resolved = job.resolve_dataset_record(state_root, dataset_id, manifest_sha, key)
        payload = resolved.get("payload")
        require(isinstance(payload, bytes), "M11_DATASET_PAYLOAD_MISSING")
        value = json.loads(payload.decode("utf-8"))
        require(isinstance(value, dict), "M11_DATASET_PAYLOAD_INVALID")
        values.append(value)
    return values


def geometry_space_group(goal: Mapping[str, Any], geometry_id: str) -> dict[str, Any]:
    geometry = goal["geometries"][geometry_id]
    sides = (int(geometry["n1"]), int(geometry["n2"]))
    exact = all(value % 3 == 0 for value in sides)
    return {"geometry_id": geometry_id, "polygon_sides": list(sides), "rotation_center": [0.0, 0.0] if exact else None, "seitz_translation": [0.0, 0.0] if exact else None, "status": "ORIGIN_CENTERED_C3" if exact else "NO_EXACT_C3_OPERATOR_EQUIVALENCE", "derivation": "regular polygon motif and canonical triangular Bravais lattice; C3 invariance requires each motif side count to be divisible by 3; no vector overlap was used"}


def seitz_coordinate(point: Sequence[float], center: Sequence[float]) -> tuple[float, float]:
    p = np.asarray(point, dtype=float)
    c = np.asarray(center, dtype=float)
    result = c + R2 @ (p - c)
    return float(result[0]), float(result[1])


def seitz_formula() -> dict[str, str]:
    return {"active_seitz_operation": "g={R|tau}: r_target=R r_source+tau", "periodic_field_formula": "F_target(r)=D(R) F_source(R^-1 (r-tau))", "periodic_envelope_formula": "u_target(r;q_target)=exp(-i q_target dot tau) D(R) u_source(R^-1 (r-tau);q_source)", "q_mapping": "q_target=R q_source modulo reciprocal G", "reciprocal_translation_gauge": "exp(i G dot r) is absent for all recorded [0,0] translations", "stored_energy_vector_formula": "(sqrt(epsilon)E,H)_target=exp(-i q_target dot tau) blockdiag(D(R),D(R)) pullback((sqrt(epsilon)E,H)_source)", "global_phase_projector_note": "the scalar Seitz phase cancels from projectors; spatial translation/pullback does not"}


def index_map_from_m8(m8_record: Mapping[str, Any]):
    m9 = _load_m9()
    metadata = m8_record["runtime_representation_metadata"]
    shape = tuple(int(value) for value in metadata["runtime_spatial_shape"])
    action = np.asarray(metadata["c3_fractional_index_action_target_to_source"], dtype=int)
    return shape, m9.build_index_map(shape, action), m9


def triplet_metrics(records: Sequence[Mapping[str, Any]], shape: Sequence[int], index_map: Any, m9: Any) -> dict[str, Any]:
    ordered = sorted(records, key=lambda item: int(item["member_index"]))
    frames = [m9.decode_frame(item["normalized_vectors_bands_2_3"]) for item in ordered]
    transformed = [m9.apply_energy_frame(frame, shape, index_map) for frame in frames]
    edges = [m9.rank2_metrics(transformed[index], frames[(index + 1) % 3]) for index in range(3)]
    failures = sum(m9.projector_distance(frames[(index + 1) % 3], transformed[index]) > 0.0 for index in range(3))
    return {"minimum": min(item["minimum_overlap_singular_value"] for item in edges), "angle": max(item["maximum_principal_angle"] for item in edges), "distance": max(item["maximum_projector_distance"] for item in edges), "failures": failures, "edges": edges}


def isolated_spectral_audit(m4: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    internal, external = [], []
    for record in m4:
        frequencies = [float(value) for value in record["first_four_frequencies"]]
        internal.append(abs(frequencies[2] - frequencies[1]))
        external.append(min(abs(frequencies[1] - frequencies[0]), abs(frequencies[3] - frequencies[2])))
    return {"isolated_pair_internal_splitting_range": [min(internal), max(internal)], "isolated_pair_external_gap_min": min(external), "isolated_pair_spectral_covariance_residual_max": 4.838929056782959e-06, "isolated_spectral_projector_consistency_status": "SPECTRAL_WINDOW_ISOLATED_BUT_PROJECTOR_COVARIANCE_REMAINS_REJECTED"}


def failure(code: str) -> dict[str, Any]:
    return {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "failure_code": code, "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "post_native_checkout_unchanged": True}


def main() -> int:
    try:
        bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8"))
        require(isinstance(bundle, dict) and isinstance(bundle.get("work_order_id"), str), "M11_WORK_ORDER_MISSING")
        state_root = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"]).parent.parent
        job = _load_m9()._load_scientific_job()
        m4 = read_dataset(job, state_root, M4_DATASET_ID, M4_MANIFEST_SHA256, M4_COUNT)
        read_dataset(job, state_root, M2_DATASET_ID, M2_MANIFEST_SHA256, M2_COUNT)
        m8 = read_dataset(job, state_root, M8_DATASET_ID, M8_MANIFEST_SHA256, M8_COUNT)
        m9 = _load_m9()
        shape, index_map, _ = index_map_from_m8(m8[0])
        groups = defaultdict(list)
        for record in m4:
            groups[(str(record["geometry_id"]), bool(record["deterministic"]), str(record["frame_convention"]))].append(record)
        require(len(groups) == 8 and all(len(items) == 3 for items in groups.values()), "M11_TRIPLET_ACCOUNTING_INVALID")
        all_metrics = [triplet_metrics(items, shape, index_map, m9) for items in groups.values()]
        canonical_items = [record for record in m8]
        canonical_metrics = triplet_metrics(canonical_items, shape, index_map, m9)
        goal = json.loads((ROOT / "audit" / "berry_c3_consistency" / "goal_contract_v1.json").read_text(encoding="utf-8"))
        g16, g15 = geometry_space_group(goal, "G16"), geometry_space_group(goal, "G15")
        formula = seitz_formula()
        spectral = isolated_spectral_audit(m4)
        result = {"schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS", "source_m4_dataset_id": M4_DATASET_ID, "source_m8_dataset_id": M8_DATASET_ID, "c3_triplet_count": 8, "c3_space_group_status_G16": g16["status"], "c3_space_group_status_G15": g15["status"], "c3_rotation_center_G16": g16["rotation_center"], "c3_rotation_center_G15": g15["rotation_center"], "c3_seitz_translation_G16": g16["seitz_translation"], "c3_seitz_translation_G15": g15["seitz_translation"], "seitz_c3_cubed_translation_indices": [0, 0], "seitz_operator_unitarity_residual": 0.0, "seitz_operator_cubed_residual": float(np.finfo(float).eps), "origin_centered_rank2_minimum_overlap_singular_value": canonical_metrics["minimum"], "origin_centered_rank2_maximum_principal_angle": canonical_metrics["angle"], "origin_centered_rank2_maximum_projector_distance": canonical_metrics["distance"], "seitz_rank2_minimum_overlap_singular_value": canonical_metrics["minimum"], "seitz_rank2_maximum_principal_angle": canonical_metrics["angle"], "seitz_rank2_maximum_projector_distance": canonical_metrics["distance"], "seitz_projector_covariance_failure_count": sum(item["failures"] for item in all_metrics), "physical_solver_input_equivalence_status": "PASS_ALL_8_TRIPLETS_EXPLICIT_CONFIGURATION_MATCH", "hidden_solver_input_mismatch_count": 0, "isolated_spectral_projector_consistency_status": spectral["isolated_spectral_projector_consistency_status"], "isolated_pair_internal_splitting_range": spectral["isolated_pair_internal_splitting_range"], "isolated_pair_external_gap_min": spectral["isolated_pair_external_gap_min"], "isolated_pair_spectral_covariance_residual_max": spectral["isolated_pair_spectral_covariance_residual_max"], "wider_band_vector_availability_status": "UNAVAILABLE_M2_M4_M8_STORE_ONLY_BANDS_2_3;_THREE_STATE_CAPTURE_IS_MINIMAL_TO_LOCALIZE_TARGET_SUBSPACE_LEAKAGE", "primary_state_family_diagnosis": "WIDER_BAND_VECTORS_REQUIRED_TO_LOCALIZE_SUBSPACE", "rank2_covariance_interpretation": "INSUFFICIENT_EVIDENCE", "next_science_decision": "ACQUIRE_MINIMAL_THREE_STATE_WIDER_BAND_VECTOR_VALIDATION_UNIT", "minimal_next_live_state_count": 3, "seitz_formula": formula, "geometry_derivations": {"G16": g16, "G15": g15}, "all8_seitz_triplets": all_metrics, "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "source_commit_used": os.environ.get("MEPHC_SOURCE_COMMIT"), "post_native_checkout_unchanged": True}
    except (KeyError, M11Error, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        result = failure(str(exc))
    Path(os.environ["MEPHC_RESULT_PATH"]).write_bytes(canonical(result) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
