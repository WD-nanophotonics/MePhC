"""M54R1: recover the material-grid A/B with canonical integer mesh keys.

M54 reached its one native child but failed before capture because its local
frequency dictionary mixed integer and string mesh keys.  This corrective
work order keeps that run immutable, reuses only the published M54 capture
primitives, and performs one new, bounded material-only readback.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "audit/berry_c3_consistency/m54_r256_material_grid_subpixel_c3_readback_ab.py"
SPEC = importlib.util.spec_from_file_location("m54r1_m54_reference", SOURCE)
assert SPEC and SPEC.loader
m54 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m54)

RESULT_SCHEMA = "mephc-berry-c3-consistency-m54r1-r256-material-grid-subpixel-c3-ab-v1"
DATASET_SCHEMA = "mephc-berry-c3-consistency-m54r1-r256-material-grid-subpixel-readback-dataset-v1"
MESHES = (1, 3, 5)


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _record_for_r1(record: Mapping[str, Any]) -> dict[str, Any]:
    value = dict(record)
    value["schema"] = DATASET_SCHEMA
    value["recovery_of_work_order"] = "MEPHC-BERRY-C3-M54-R256-MATERIAL-GRID-SUBPIXEL-C3-READBACK-AB-20260905-132"
    identity = {key: item for key, item in value.items() if key != "record_id"}
    value["record_id"] = "MEPHC-M54R1-MATERIAL-" + hashlib.sha256(canonical(identity)).hexdigest()
    return value


def canonical_frequency_map(frequency_rows: Mapping[int, Mapping[tuple[int, int, str], Mapping[str, Any]]]) -> dict[int, dict[str, Any]]:
    """Return the only internal frequency map shape permitted by M54R1."""
    require_keys = {int(key) for key in frequency_rows}
    if require_keys != set(MESHES) or any(type(key) is not int for key in frequency_rows):
        raise ValueError("M54R1_MESH_KEY_SET_INVALID")
    return {mesh: m54.frequency_ledger(frequency_rows[mesh]) for mesh in MESHES}


def classify(frequency: Mapping[int, Mapping[str, Any]], material: Mapping[int, Mapping[str, Any]]) -> tuple[str, str]:
    if set(frequency) != set(MESHES) or set(material) != set(MESHES):
        raise ValueError("M54R1_CLASSIFICATION_KEY_SET_INVALID")
    if int(frequency[5]["failure_count"]) == 0:
        return "R256_FREQUENCY_C3_FAILURE_NOT_REPRODUCED", "R256_M5_FREQUENCY_SCALAR_REQUALIFICATION"
    m1, m3, m5 = material[1], material[3], material[5]
    m1_defect = m1["scalar_c3_status"] == "FAIL" or m1["tensor_c3_status"] == "FAIL"
    if m1_defect:
        return "R256_BASE_GEOMETRY_RASTER_OR_GRID_C3_BREAKING", "IMPLEMENT_PROJECT_CONTAINED_EXACT_C3_GEOMETRY_RASTER_PATCH_AND_BOUNDED_FREQUENCY_AB"
    if m5["scalar_c3_status"] == "FAIL" and frequency[1]["failure_count"] == 0:
        return "R256_SUBPIXEL_SCALAR_MATERIAL_C3_CAUSAL_SIGNATURE_SUPPORTED", "IMPLEMENT_PROJECT_CONTAINED_C3_PROJECTED_SCALAR_EPSILON_INPUT_AND_BOUNDED_FREQUENCY_AB"
    if m5["scalar_c3_status"] == "PASS" and m5["tensor_c3_status"] == "FAIL" and frequency[1]["failure_count"] == 0:
        return "R256_SUBPIXEL_TENSOR_MATERIAL_C3_CAUSAL_SIGNATURE_SUPPORTED", "IMPLEMENT_TENSOR_AWARE_C3_SUBPIXEL_OPERATOR_PATCH_AND_BOUNDED_FREQUENCY_AB"
    if any(item["scalar_c3_status"] == "FAIL" or item["tensor_c3_status"] == "FAIL" for item in (m3, m5)):
        return "R256_SUBPIXEL_MATERIAL_C3_MIXED_CONTRIBUTOR", "IMPLEMENT_MATERIAL_C3_PATCH_AB_WITH_SECONDARY_K_OPERATOR_DIAGNOSTIC"
    return "R256_MATERIAL_READBACK_C3_COVARIANT_DESPITE_FREQUENCY_FAILURE", "MPB_K_DEPENDENT_DISCRETE_OPERATOR_C3_SOURCE_AUDIT"


def _persist(store: Any, work_order_id: str, record: Mapping[str, Any]) -> dict[str, Any]:
    key = canonical({"work_order_id": work_order_id, "mesh_size": record["mesh_size"], "record_id": record["record_id"]})
    return store.put(key, canonical(dict(record)), {"mesh_size": record["mesh_size"], "record_id": record["record_id"], "schema": DATASET_SCHEMA})


def main() -> int:
    bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8"))
    source_commit = str(os.environ.get("MEPHC_SOURCE_COMMIT") or bundle.get("source_commit") or "")
    records: list[dict[str, Any]] = []
    try:
        job = m54.m52r1.m41r3._load(ROOT / "tools/mephc-flow/scientific_job.py", "m54r1_job")
        counters = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"]); state_root = counters.parent.parent
        frequency_rows = {mesh: m54._read_frequency_rows(job, state_root, dataset) for mesh, dataset in zip(MESHES, m54.m52r1.MESH_DATASETS)}
        frequency = canonical_frequency_map(frequency_rows)
        if frequency[5]["failure_count"] == 0:
            raise ValueError("M54R1_MESH5_FREQUENCY_FAILURE_NOT_REPRODUCED")
        member = frequency_rows[5][(0, 0, "IDENTITY")]
        index_map = m54.build_index_map()
        synthetic = m54.synthetic_tensor_rotation_check()
        if not synthetic["direct_grid_bijection"] or not synthetic["direct_grid_c3_cubed"]:
            raise ValueError("M54R1_SYNTHETIC_GRID_REGRESSION_FAILED")
        namespace = {"goal_id": "MEPHC-BERRY-C3-CONSISTENCY-V1", "work_order_id": bundle["work_order_id"], "source_commit": source_commit, "record_schema": DATASET_SCHEMA}
        store = job.ImmutableDatasetStore(state_root, namespace)
        material: dict[int, dict[str, Any]] = {}
        for mesh in MESHES:
            raw_record, data = m54.capture_material(member, mesh, index_map)
            record = _record_for_r1(raw_record)
            _persist(store, bundle["work_order_id"], record)
            records.append(record)
            material[mesh] = data[2]
        manifest = store.finalize(3, {"dataset_schema": DATASET_SCHEMA, "readback_only": True, "mesh_sizes": list(MESHES), "geometry": m54.G15, "eigensolver_called": False, "recovered_native_work_order": "MEPHC-BERRY-C3-M54-R256-MATERIAL-GRID-SUBPIXEL-C3-READBACK-AB-20260905-132"})
        classification, decision = classify(frequency, material)
        result = {"schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 3, "dataset_write": True, "dataset_id": manifest.get("dataset_id"), "manifest_sha256": manifest.get("manifest_sha256"), "dataset_schema": DATASET_SCHEMA, "source_commit_used": source_commit, "mesh_key_type": "integer", "mesh_key_set": list(MESHES), "frequency_reference": {str(mesh): frequency[mesh] for mesh in MESHES}, "material_readback": {str(mesh): material[mesh] for mesh in MESHES}, "material_record_ids": [record["record_id"] for record in records], "material_record_count": len(records), "synthetic_tensor_rotation_check": synthetic, "classification": classification, "causal_outcome": classification, "next_science_decision": decision, "material_projection_status": "AUDIT_ONLY_NOT_FED_TO_EIGENSOLVER", "eigensolver_called": False, "forbidden_solver_call_count": 0, "no_new_band_states": True, "recovered_prior_native_run": "MEPHC-NATIVE-35aa1eef4bbe3f7e9502753e", "post_native_checkout_unchanged": True}
    except BaseException as exc:
        result = {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": len(records), "dataset_write": bool(records), "failure_code": str(exc)[:1024], "failure_stage": "m54r1_material_grid_subpixel_c3_readback", "exception_type": type(exc).__name__, "source_commit_used": source_commit, "completed_record_ids": [record["record_id"] for record in records], "post_native_checkout_unchanged": True}
    Path(os.environ["MEPHC_RESULT_PATH"]).write_text(json.dumps(m54._safe(result), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
