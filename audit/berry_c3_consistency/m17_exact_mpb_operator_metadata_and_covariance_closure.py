"""M17: one metadata-only MPB runtime capture for the existing G15 triplet.

This entrypoint deliberately constructs the production geometry and MPB
ModeSolver but never invokes a band solve.  Its only Native side effect is
the capture of exact runtime material metadata (when the public runtime makes
that metadata available without an eigensolve) for the three already stored
M12/M13 states.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
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
DATASET_SCHEMA = "mephc-berry-c3-consistency-m17-exact-mpb-operator-metadata-dataset-v1"
RESULT_SCHEMA = "mephc-berry-c3-consistency-m17-exact-mpb-operator-metadata-and-covariance-closure-v1"
SHAPE = (128, 128)
RECORD_COUNT = 3
RUNTIME_RESOLUTION = 128
MESH_SIZE = 3
NUM_BANDS = 12
G15 = {"a": 400.0, "r1": 80.14335684352235, "r2": 75.13439704080221, "n1": 15, "n2": 15, "theta1_degrees": 0.0, "theta2_degrees": 60.0, "n_eff": 2.7, "height": 100.0}


class M17Error(ValueError):
    pass


def require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise M17Error(f"{code}:{detail}" if detail else code)


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def record_identity_payload(record: Mapping[str, Any]) -> dict[str, Any]:
    """Select only immutable semantic/content fields for record identity."""
    payload = {
        "schema": record.get("schema", DATASET_SCHEMA),
        "source_physical_state_identity": {
            "request_key_sha256": record.get("request_key_sha256"),
            "member_index": record.get("member_index"),
            "c3_member_identity": record.get("c3_member_identity"),
            "geometry_id": record.get("geometry_id"),
            "geometry_role": record.get("geometry_role"),
            "coordinate": record.get("coordinate"),
        },
        "runtime_material_grid_identity": {
            "metadata_status": record.get("metadata_status"),
            "metadata_error": record.get("metadata_error"),
            "epsilon_grid_sha256": record.get("epsilon_grid_sha256"),
            "exact_mpb_epsilon_grid_shape": record.get("exact_mpb_epsilon_grid_shape"),
            "epsilon_grid_dtype": record.get("epsilon_grid_dtype"),
            "epsilon_material_representation_type": record.get("epsilon_material_representation_type"),
            "epsilon_inverse_or_tensor_metadata_status": record.get("epsilon_inverse_or_tensor_metadata_status"),
            "subpixel_or_smoothing_configuration": record.get("subpixel_or_smoothing_configuration"),
        },
        "source_commit": record.get("source_commit", os.environ.get("MEPHC_SOURCE_COMMIT")),
    }
    return payload


def deterministic_record_id(record: Mapping[str, Any]) -> str:
    """Generate an insertion-order-independent content-semantic identity."""
    return "MEPHC-M17-METADATA-" + digest(record_identity_payload(record))


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, "M17_DEPENDENCY_UNAVAILABLE", str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _m16() -> Any:
    return _load(ROOT / "audit" / "berry_c3_consistency" / "m16_discrete_material_maxwell_residual_covariance.py", "m17_m16_helpers")


def _m13() -> Any:
    return _load(ROOT / "audit" / "berry_c3_consistency" / "m13_g15_adjacent_band_window_discrimination.py", "m17_m13_helpers")


def _job() -> Any:
    return _load(ROOT / "tools" / "mephc-flow" / "scientific_job.py", "m17_scientific_job")


def read_dataset(job: Any, state_root: Path, dataset_id: str, manifest_sha: str, count: int) -> list[dict[str, Any]]:
    verified = job.verify_dataset(state_root, dataset_id)
    require(verified.get("dataset_id") == dataset_id and verified.get("manifest_sha256") == manifest_sha and verified.get("record_count") == count, "M17_DATASET_BINDING_INVALID", dataset_id)
    result = []
    for key in verified["record_key_sha256"]:
        payload = job.resolve_dataset_record(state_root, dataset_id, manifest_sha, key).get("payload")
        require(isinstance(payload, bytes), "M17_DATASET_PAYLOAD_MISSING", dataset_id)
        value = json.loads(payload.decode("utf-8"))
        require(isinstance(value, dict), "M17_DATASET_PAYLOAD_INVALID", dataset_id)
        result.append(value)
    return result


def select_triplet(m12: Sequence[Mapping[str, Any]], m13: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    selected = _m13().select_same_triplet(m13)
    old = {item["request_key_sha256"]: item for item in m12}
    require(len(selected) == RECORD_COUNT and all(item["request_key_sha256"] in old for item in selected), "M17_G15_TRIPLET_BINDING_INVALID")
    return selected


def production_geometry_and_solver_factory() -> tuple[Any, Any, Any, Any]:
    """Construct production geometry and a solver factory without solving."""
    import meep as mp
    from meep import mpb
    from mephc.band import Band

    band = Band(a=G15["a"], r1=G15["r1"], r2=G15["r2"], n_eff=G15["n_eff"], h=G15["height"], resolution=RUNTIME_RESOLUTION, lattice_type="triangular", polarization="TE", structure_type="slab")
    pattern = band.create_unitcell(G15["n1"], G15["theta1_degrees"], G15["n2"], G15["theta2_degrees"], show=False)
    geometry = band.create_material_block() + band.convert_ndarray_to_meep_geo(pattern, rectify=True)

    def make_solver(reciprocal_k_point: Any) -> Any:
        return mpb.ModeSolver(
            geometry=geometry, geometry_lattice=band.geo_latt, k_points=[reciprocal_k_point],
            resolution=RUNTIME_RESOLUTION, num_bands=NUM_BANDS, default_material=mp.air,
            tolerance=1e-7, deterministic=False, mesh_size=MESH_SIZE,
        )

    return mp, band, make_solver, geometry


def _point_tuple(value: Any) -> list[float]:
    if isinstance(value, (tuple, list, np.ndarray)):
        array = np.asarray(value, dtype=float).reshape(-1)
        require(array.size == 3, "M17_RECIPROCAL_KPOINT_LAYOUT_INVALID")
        return [float(item) for item in array]
    return [float(getattr(value, axis)) for axis in ("x", "y", "z")]


def _incomplete_record(member: Mapping[str, Any], status: str, error: str) -> dict[str, Any]:
    """Keep failed metadata attempts serializable for bounded reconciliation."""
    record = {
        "schema": DATASET_SCHEMA,
        "request_key_sha256": member["request_key_sha256"],
        "member_index": int(member["member_index"]),
        "c3_member_identity": member["c3_member_identity"],
        "geometry_id": "G15",
        "geometry_role": "AREA_MATCHED_G15",
        "coordinate": list(member["coordinate"]),
        "metadata_status": status,
        "metadata_error": error,
        "forbidden_solver_call_count": 0,
    }
    record["source_commit"] = os.environ.get("MEPHC_SOURCE_COMMIT")
    record["record_id"] = deterministic_record_id(record)
    return record


def capture_mode_solver_metadata(solver: Any, *, member: Mapping[str, Any], reciprocal_k_point: Any, api_calls: list[str], spatial_shape: Sequence[int] = SHAPE) -> dict[str, Any]:
    """Capture only read-only material metadata; never invoke a solve API."""
    require(not any(name in api_calls for name in ("run", "run_parity", "solve", "all_freqs")), "M17_FORBIDDEN_SOLVER_CALL_TRACE")
    init = getattr(solver, "init_params", None)
    if callable(init):
        api_calls.append("ModeSolver.init_params")
        try:
            init()
        except Exception as exc:
            return _incomplete_record(member, "EXACT_MPB_METADATA_REQUIRES_EIGENSOLVE", f"init_params:{type(exc).__name__}:{str(exc)[:512]}")
    else:
        return _incomplete_record(member, "EXACT_MPB_METADATA_REQUIRES_EIGENSOLVE", "ModeSolver.init_params is not exposed; exact material access cannot be proven non-solving")
    get_epsilon = getattr(solver, "get_epsilon", None)
    if not callable(get_epsilon):
        return _incomplete_record(member, "EXACT_MPB_METADATA_REQUIRES_EIGENSOLVE", "ModeSolver.get_epsilon is not exposed before an eigensolve")
    api_calls.append("ModeSolver.get_epsilon")
    try:
        epsilon_raw = np.asarray(get_epsilon(), dtype=float)
    except Exception as exc:
        return _incomplete_record(member, "EXACT_MPB_METADATA_REQUIRES_EIGENSOLVE", f"get_epsilon:{type(exc).__name__}:{str(exc)[:512]}")
    spatial_shape = tuple(int(value) for value in spatial_shape)
    require(epsilon_raw.size == spatial_shape[0] * spatial_shape[1], "M17_EPSILON_GRID_SHAPE_INVALID", str(epsilon_raw.shape))
    epsilon = epsilon_raw.reshape(spatial_shape)
    require(np.all(np.isfinite(epsilon)) and np.all(epsilon > 0.0), "M17_EPSILON_GRID_NONFINITE")
    inverse = None
    get_inverse = getattr(solver, "get_epsilon_inverse", None)
    inverse_status = "NOT_EXPOSED"
    if callable(get_inverse):
        api_calls.append("ModeSolver.get_epsilon_inverse")
        try:
            inverse_raw = np.asarray(get_inverse(), dtype=float)
            inverse = inverse_raw.reshape(SHAPE).tolist() if inverse_raw.size == epsilon.size else None
            inverse_status = "CAPTURED_SCALAR_INVERSE" if inverse is not None else "EXPOSED_LAYOUT_UNSUPPORTED"
        except Exception as exc:
            inverse_status = f"ACCESS_FAILED_WITHOUT_SOLVE:{type(exc).__name__}"
    record = {
        "schema": DATASET_SCHEMA, "record_id": f"{member['request_key_sha256']}:m17", "request_key_sha256": member["request_key_sha256"],
        "member_index": int(member["member_index"]), "c3_member_identity": member["c3_member_identity"], "geometry_id": "G15", "geometry_role": "AREA_MATCHED_G15",
        "coordinate": list(member["coordinate"]), "mpb_reciprocal_k_point": _point_tuple(reciprocal_k_point),
        "metadata_status": "CAPTURED", "exact_mpb_epsilon_grid_shape": list(epsilon.shape), "epsilon_grid_dtype": str(epsilon.dtype),
        "epsilon_material_representation_type": "SCALAR_EPSILON_GRID", "material_grid_axis_order": "(x,y), C-order reshape of ModeSolver.get_epsilon()",
        "material_grid_coordinate_convention": "MPB geometry-lattice fractional cell coordinates, periodic [0,1)x[0,1)",
        "subpixel_or_smoothing_configuration": {"mesh_size": MESH_SIZE, "runtime_subpixel_metadata": "not exposed by ModeSolver public object"},
        "field_material_grid_alignment_status": "FIELD_GRID_ALIGNMENT_REQUIRES_RUNTIME_FIELD_METADATA; epsilon grid shape captured",
        "boundary_or_staggering_metadata_status": "MPB_PERIODIC_BOUNDARY_EXACT_BUT_FIELD_STAGGERING_NOT_EXPOSED",
        "epsilon_inverse_or_tensor_metadata_status": inverse_status,
        "epsilon_grid_sha256": hashlib.sha256(canonical(epsilon.tolist())).hexdigest(),
        "epsilon_grid": epsilon.tolist(), "epsilon_inverse_grid": inverse,
        "forbidden_solver_call_count": 0,
    }
    record["source_commit"] = os.environ.get("MEPHC_SOURCE_COMMIT")
    record["record_id"] = deterministic_record_id(record)
    return record


def capture_triplet_metadata(members: Sequence[Mapping[str, Any]], *, runtime_factory: Any | None = None, spatial_shape: Sequence[int] = SHAPE) -> tuple[list[dict[str, Any]], list[str], int]:
    if runtime_factory is None:
        mp, band, make_solver, _ = production_geometry_and_solver_factory()
        def runtime_factory(member: Mapping[str, Any]) -> tuple[Any, Any]:
            reciprocal = mp.cartesian_to_reciprocal(mp.Vector3(float(member["coordinate"][0]), float(member["coordinate"][1]), 0.0), band.geo_latt)
            return make_solver(reciprocal), reciprocal
    records, api_calls, forbidden = [], [], 0
    for member in sorted(members, key=lambda item: int(item["member_index"])):
        solver, reciprocal = runtime_factory(member)
        record = capture_mode_solver_metadata(solver, member=member, reciprocal_k_point=reciprocal, api_calls=api_calls, spatial_shape=spatial_shape)
        records.append(record); forbidden += int(record.get("forbidden_solver_call_count", 0))
    require(len(records) == RECORD_COUNT, "M17_METADATA_RECORD_COUNT_INVALID")
    return records, api_calls, forbidden


def persist_metadata(job: Any, state_root: Path, work_order_id: str, records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    namespace = {"goal_id": "MEPHC-BERRY-C3-CONSISTENCY-V1", "work_order_id": work_order_id, "source_commit": os.environ.get("MEPHC_SOURCE_COMMIT"), "record_schema": DATASET_SCHEMA}
    store = job.ImmutableDatasetStore(state_root, namespace)
    identities = []
    for record in records:
        require(isinstance(record.get("record_id"), str) and record["record_id"] == deterministic_record_id(record), "M17_RECORD_ID_INVALID", str(record.get("member_index")))
        identities.append(record["record_id"])
    require(len(identities) == len(set(identities)), "M17_RECORD_ID_NOT_UNIQUE")
    for record in records:
        key = canonical({"work_order_id": work_order_id, "member_index": int(record["member_index"]), "record_id": record["record_id"]})
        store.put(key, canonical(dict(record)), {"member_index": int(record["member_index"]), "c3_member_identity": record["c3_member_identity"], "metadata_status": record["metadata_status"]})
    return store.finalize(RECORD_COUNT, {"dataset_schema": DATASET_SCHEMA, "source_m12_dataset_id": M12_DATASET_ID, "source_m13_dataset_id": M13_DATASET_ID})


def calibrate_exact_metadata(records: Sequence[Mapping[str, Any]], m12: Sequence[Mapping[str, Any]], m13: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    complete = len(records) == RECORD_COUNT and all(item.get("metadata_status") == "CAPTURED" and isinstance(item.get("epsilon_grid"), list) for item in records)
    if not complete:
        return {"status": "NOT_CALIBRATED_METADATA_INCOMPLETE", "exact_mpb_stored_eigenstate_maxwell_residual_max": None, "exact_mpb_stored_eigenstate_curlE_residual_max": None, "exact_mpb_stored_eigenstate_curlH_residual_max": None, "comparison_vs_m16": "not computable without exact epsilon grid"}
    m16 = _m16(); _, frames, frequencies = m16._ordered_combined(m12, m13)
    residual_rows = []
    for record, frame, freq in zip(sorted(records, key=lambda item: int(item["member_index"])), frames, frequencies):
        epsilon = np.asarray(record["epsilon_grid"], dtype=float).reshape(SHAPE)
        residual = m16.stored_eigenstate_residuals([record], [frame], [freq], epsilon)
        residual_rows.append(residual)
    return {"status": "RAW_EXACT_RESIDUALS_REPORTED_NO_PREREGISTERED_THRESHOLD", "exact_mpb_stored_eigenstate_maxwell_residual_max": max(item["stored_eigenstate_maxwell_residual_max"] for item in residual_rows), "exact_mpb_stored_eigenstate_curlE_residual_max": max(item["stored_eigenstate_curlE_residual_max"] for item in residual_rows), "exact_mpb_stored_eigenstate_curlH_residual_max": max(item["stored_eigenstate_curlH_residual_max"] for item in residual_rows), "comparison_vs_m16": "exact and M16 raw residuals are reported under the same fixed derivative/sign convention; no acceptance threshold invented"}


def result_for(records: Sequence[Mapping[str, Any]], api_calls: Sequence[str], forbidden: int, manifest: Mapping[str, Any] | None, m12: Sequence[Mapping[str, Any]], m13: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    statuses = {item.get("metadata_status") for item in records}
    if statuses == {"CAPTURED"}:
        metadata_status = "CAPTURED_BUT_OPERATOR_METADATA_STILL_INCOMPLETE"
    elif "CAPTURED" in statuses:
        metadata_status = "CAPTURED_BUT_OPERATOR_METADATA_STILL_INCOMPLETE"
    elif any("REQUIRES_EIGENSOLVE" in str(item.get("metadata_status")) for item in records):
        metadata_status = "EXACT_MPB_METADATA_REQUIRES_EIGENSOLVE"
    else:
        metadata_status = "INSUFFICIENT_EVIDENCE"
    calibration = calibrate_exact_metadata(records, m12, m13)
    captured = [item for item in records if item.get("metadata_status") == "CAPTURED"]
    return {
        "schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS", "source_m12_dataset_id": M12_DATASET_ID, "source_m13_dataset_id": M13_DATASET_ID,
        "target_state_count": RECORD_COUNT, "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": len(records), "new_metadata_record_count": len(records),
        "dataset_id": manifest.get("dataset_id") if manifest else None, "manifest_sha256": manifest.get("manifest_sha256") if manifest else None,
        "metadata_api_calls": list(api_calls), "forbidden_solver_call_count": int(forbidden), "exact_mpb_operator_metadata_status": metadata_status,
        "exact_mpb_epsilon_grid_shape": list(np.asarray(captured[0]["epsilon_grid"]).shape) if captured else None,
        "epsilon_grid_dtype": str(np.asarray(captured[0]["epsilon_grid"]).dtype) if captured else None,
        "epsilon_material_representation_type": "SCALAR_EPSILON_GRID" if captured else None,
        "material_grid_axis_order": captured[0].get("material_grid_axis_order") if captured else None,
        "material_grid_coordinate_convention": captured[0].get("material_grid_coordinate_convention") if captured else None,
        "subpixel_or_smoothing_configuration": captured[0].get("subpixel_or_smoothing_configuration") if captured else "not captured",
        "field_material_grid_alignment_status": captured[0].get("field_material_grid_alignment_status") if captured else "not captured",
        "boundary_or_staggering_metadata_status": captured[0].get("boundary_or_staggering_metadata_status") if captured else "not captured",
        "epsilon_inverse_or_tensor_metadata_status": captured[0].get("epsilon_inverse_or_tensor_metadata_status") if captured else "not captured",
        "exact_mpb_stored_eigenstate_maxwell_residual_max": calibration["exact_mpb_stored_eigenstate_maxwell_residual_max"], "exact_mpb_stored_eigenstate_curlE_residual_max": calibration["exact_mpb_stored_eigenstate_curlE_residual_max"], "exact_mpb_stored_eigenstate_curlH_residual_max": calibration["exact_mpb_stored_eigenstate_curlH_residual_max"], "comparison_vs_m16_approximate_material": calibration["comparison_vs_m16"],
        "exact_mpb_c3_transformed_state_maxwell_residual_max": None, "exact_mpb_operator_intertwining_residual_max": None, "exact_mpb_epsilon_grid_c3_residual_max": None, "exact_mpb_material_c3_covariance_status": "NOT_ADJUDICATED_OPERATOR_METADATA_INCOMPLETE",
        "isolated_projector_theorem_status": "M16_PROJECTOR_CONTRADICTION_REMAINS_UNADJUDICATED_AT_EXACT_OPERATOR_LEVEL", "discrete_operator_covariance_diagnosis": "OPERATOR_RECONSTRUCTION_STILL_INCOMPLETE",
        "remaining_unresolved_questions": ["Whether MPB subpixel material tensors and field staggering are required beyond epsilon grid", "Whether exact calibrated operator supports C3 on stored states and resolves the projector contradiction"],
        "alternative_explanations_considered": ["M16 point-sampled material approximation", "MPB epsilon grid", "subpixel/smoothing material tensors", "field/material alignment", "boundary/staggering convention", "Maxwell sign/time convention", "reciprocal-folding gauge", "stored spectral/projector family"],
        "counterevidence_summary": {"metadata_status_by_member": [{"member_index": item["member_index"], "status": item["metadata_status"], "error": item.get("metadata_error")} for item in records], "solver_call_trace": list(api_calls), "m16_authority": "source-level approximation had order-unity residuals"},
        "cheapest_remaining_discriminating_test": "If get_epsilon requires eigensolve, capture the exact MPB material/operator arrays through a future metadata-safe runtime hook; do not spend solver budget in M17",
        "next_science_decision": "ACQUIRE_MINIMAL_EXACT_MPB_OPERATOR_METADATA_WITH_SOLVER_ONLY_IF_UNAVOIDABLE" if metadata_status == "EXACT_MPB_METADATA_REQUIRES_EIGENSOLVE" else "REPAIR_DISCRETE_MATERIAL_OR_OPERATOR_C3_PATH_AND_REANALYZE_EXISTING_DATA_ONLY",
        "minimal_next_live_state_count": 0, "exact_missing_operator_metadata": [item.get("metadata_error") for item in records if item.get("metadata_status") != "CAPTURED"], "source_commit_used": os.environ.get("MEPHC_SOURCE_COMMIT"), "post_analysis_checkout_unchanged": True,
    }


def failure(code: str, exc: BaseException | None = None) -> dict[str, Any]:
    return {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "failure_code": code, "exception_type": type(exc).__name__ if exc else None, "exception_message": str(exc)[:1024] if exc else None, "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "new_metadata_record_count": 0, "forbidden_solver_call_count": 0, "exact_mpb_operator_metadata_status": "INSUFFICIENT_EVIDENCE", "discrete_operator_covariance_diagnosis": "INSUFFICIENT_EVIDENCE", "next_science_decision": "INSUFFICIENT_EVIDENCE", "minimal_next_live_state_count": 0, "source_commit_used": os.environ.get("MEPHC_SOURCE_COMMIT"), "post_analysis_checkout_unchanged": True}


def main() -> int:
    try:
        bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8"))
        require(isinstance(bundle, dict) and isinstance(bundle.get("work_order_id"), str), "M17_WORK_ORDER_MISSING")
        counters = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"]); state_root = counters.parent.parent; job = _job()
        m12 = read_dataset(job, state_root, M12_DATASET_ID, M12_MANIFEST_SHA256, 3); m13 = read_dataset(job, state_root, M13_DATASET_ID, M13_MANIFEST_SHA256, 3); members = select_triplet(m12, m13)
        records, api_calls, forbidden = capture_triplet_metadata(members)
        manifest = persist_metadata(job, state_root, bundle["work_order_id"], records)
        result = result_for(records, api_calls, forbidden, manifest, m12, m13)
    except Exception as exc:
        result = failure(str(exc), exc); result["traceback_tail"] = traceback.format_exc()[-3000:]
    Path(os.environ["MEPHC_RESULT_PATH"]).write_bytes(canonical(result) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
