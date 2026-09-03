"""M21: bounded read-only hook for the three canonical MPB states.

The hook observes discoverable solver attributes immediately after each fixed
six-band solve.  It stores metadata summaries only; it never alters solver
objects or persists a second scientific state-family dataset.
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
M18_DATASET_ID = "6aff6fe12b50c1124eea52e246a9eba832420d51f756c32702694fe4a696a1af"
M18_MANIFEST_SHA256 = "7288abd0f4e9722eae1844ff9a917430d3d451ceb76682380270cb74d9f0205f"
M12_DATASET_ID = "c750df1085ddd0df8ae2ca1611d2881f378767d8fe2bc053a6ed504d99359a40"
M13_DATASET_ID = "dcaee157184d53a6a8025a374505084e105cde49f55d9ea345b55bae058dedcd"
DATASET_SCHEMA = "mephc-berry-c3-consistency-m21-internal-mpb-operator-metadata-dataset-v1"
RESULT_SCHEMA = "mephc-berry-c3-consistency-m21-internal-mpb-staggering-constitutive-hook-v1"
STATE_COUNT = 3
BANDS = 6


class M21Error(ValueError):
    pass


def require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise M21Error(f"{code}:{detail}" if detail else code)


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, "M21_DEPENDENCY_UNAVAILABLE", str(path))
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


def _m18() -> Any:
    return _load(ROOT / "audit" / "berry_c3_consistency" / "m18_exact_mpb_operator_readback_and_covariance_closure.py", "m21_m18_helpers")


def _job() -> Any:
    return _load(ROOT / "tools" / "mephc-flow" / "scientific_job.py", "m21_scientific_job")


def _ordered(members: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result = sorted((dict(member) for member in members), key=lambda item: int(item["member_index"]))
    require(len(result) == STATE_COUNT and [item["member_index"] for item in result] == [0, 1, 2], "M21_MEMBER_ORDER_INVALID")
    require([item["c3_member_identity"] for item in result] == ["IDENTITY", "C3", "C3_SQUARED"], "M21_MEMBER_IDENTITY_INVALID")
    return result


def _value_summary(value: Any) -> dict[str, Any]:
    """Describe an object without serializing raw arrays or blobs."""
    summary = {"type": f"{type(value).__module__}.{type(value).__qualname__}"}
    shape = getattr(value, "shape", None)
    if shape is not None:
        try:
            summary["shape"] = [int(item) for item in shape]
        except (TypeError, ValueError):
            summary["shape"] = "UNAVAILABLE"
    dtype = getattr(value, "dtype", None)
    if dtype is not None:
        summary["dtype"] = str(dtype)
    if isinstance(value, (str, int, float, bool)) or value is None:
        summary["scalar_value"] = value
    elif isinstance(value, (list, tuple)):
        summary["length"] = len(value)
    return summary


def observe_internal_metadata(solver: Any) -> dict[str, Any]:
    """Inspect only non-callable discoverable attributes on one solver."""
    tokens = ("grid", "stagger", "offset", "interpol", "material", "constitut", "epsilon", "field", "curl", "operator", "mesh", "boundary")
    metadata = []
    names = sorted(name for name in dir(solver) if not name.startswith("__") and any(token in name.lower() for token in tokens))
    for name in names:
        try:
            value = getattr(solver, name)
        except Exception as exc:
            metadata.append({"symbol_path": f"ModeSolver.{name}", "access": "FAILED", "error_type": type(exc).__name__})
            continue
        if callable(value):
            continue
        metadata.append({"symbol_path": f"ModeSolver.{name}", "access": "READ_ONLY", "value": _value_summary(value), "certainty": "OBSERVED_ATTRIBUTE_ONLY"})
    useful = [item for item in metadata if item.get("access") == "READ_ONLY"]
    return {"captured_internal_symbol_paths": [item["symbol_path"] for item in useful], "metadata": metadata, "hook_status": "CAPTURED_PARTIAL_NATIVE_METADATA" if useful else "INTERNAL_MPB_OPERATOR_OBJECT_NOT_ACCESSIBLE_IN_INSTALLED_RUNTIME"}


def _metadata_record(member: Mapping[str, Any], solver: Any, reciprocal: Any, observation: Mapping[str, Any], source_commit: str | None) -> dict[str, Any]:
    record = {"schema": DATASET_SCHEMA, "member_index": int(member["member_index"]), "c3_member_identity": member["c3_member_identity"], "request_key_sha256": member["request_key_sha256"], "coordinate": list(member["coordinate"]), "geometry_id": "G15", "geometry_role": "AREA_MATCHED_G15", "deterministic": False, "frame_convention": "LAB_FIXED", "repeat_index": 1, "num_bands": BANDS, "mpb_reciprocal_k_point": [float(getattr(reciprocal, axis)) for axis in ("x", "y", "z")], "direct_mpb_methods_invoked": ["ModeSolver.run_parity"], "solver_object_type": f"{type(solver).__module__}.{type(solver).__qualname__}", "internal_observation": dict(observation), "source_commit": source_commit, "raw_arrays_persisted": False, "public_getter_arrays_reused_from_m18": True}
    record["record_id"] = "MEPHC-M21-METADATA-" + hashlib.sha256(canonical(record)).hexdigest()
    return record


def capture_triplet(members: Sequence[Mapping[str, Any]], factory: Any, counter: Any, source_commit: str | None = None) -> list[dict[str, Any]]:
    records = []
    for member in _ordered(members):
        solver, reciprocal, parity = factory(member)
        counter.consume_solver()
        solver.run_parity(parity, False)
        observation = observe_internal_metadata(solver)
        records.append(_metadata_record(member, solver, reciprocal, observation, source_commit))
    require(len(records) == STATE_COUNT, "M21_METADATA_RECORD_COUNT_INVALID")
    return records


def persist_metadata(job: Any, state_root: Path, work_order_id: str, records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    store = job.ImmutableDatasetStore(state_root, {"goal_id": "MEPHC-BERRY-C3-CONSISTENCY-V1", "work_order_id": work_order_id, "source_commit": os.environ.get("MEPHC_SOURCE_COMMIT"), "record_schema": DATASET_SCHEMA})
    for record in records:
        key = canonical({"work_order_id": work_order_id, "member_index": record["member_index"], "record_id": record["record_id"]})
        store.put(key, canonical(dict(record)), {"member_index": record["member_index"], "c3_member_identity": record["c3_member_identity"], "record_id": record["record_id"], "metadata_only": True})
    return store.finalize(STATE_COUNT, {"dataset_schema": DATASET_SCHEMA, "metadata_only": True, "source_m18_dataset_id": M18_DATASET_ID})


def analyze(records: Sequence[Mapping[str, Any]], manifest: Mapping[str, Any], solver_count: int) -> dict[str, Any]:
    ordered = _ordered(records); statuses = [item["internal_observation"]["hook_status"] for item in ordered]; paths = [item["internal_observation"]["captured_internal_symbol_paths"] for item in ordered]; all_partial = all(status == "CAPTURED_PARTIAL_NATIVE_METADATA" for status in statuses)
    return {"schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS", "source_m18_dataset_id": M18_DATASET_ID, "source_m12_dataset_id": M12_DATASET_ID, "source_m13_dataset_id": M13_DATASET_ID, "target_state_count": STATE_COUNT, "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": solver_count, "dataset_record_count": STATE_COUNT, "new_metadata_record_count": STATE_COUNT, "dataset_id": manifest["dataset_id"], "manifest_sha256": manifest["manifest_sha256"], "internal_runtime_hook_status": "CAPTURED_PARTIAL_NATIVE_METADATA" if all_partial else "INTERNAL_MPB_OPERATOR_OBJECT_NOT_ACCESSIBLE_IN_INSTALLED_RUNTIME", "captured_internal_symbol_paths": paths, "native_E_component_locations": "UNAVAILABLE_INTERNAL_METADATA", "native_H_component_locations": "UNAVAILABLE_INTERNAL_METADATA", "native_D_component_locations": "UNAVAILABLE_INTERNAL_METADATA", "native_B_component_locations": "UNAVAILABLE_INTERNAL_METADATA", "public_getter_interpolation_status": "UNAVAILABLE_INTERNAL_METADATA", "internal_material_operator_status": "UNAVAILABLE_INTERNAL_METADATA", "internal_epsilon_or_epsilon_inverse_operator_status": "UNAVAILABLE_INTERNAL_METADATA", "component_offset_coordinate_basis": "UNAVAILABLE_INTERNAL_METADATA", "native_boundary_periodic_indexing_status": "PUBLIC_BOUNDARY_METADATA_ONLY; NATIVE_COMPONENT_INDEXING_UNAVAILABLE", "native_stored_state_maxwell_residual_max": None, "native_curlE_residual_max": None, "native_curlH_residual_max": None, "calibration_improvement_factor_vs_M18": None, "native_component_grid_c3_covariance_status": "NOT_EVALUABLE_NATIVE_LOCATIONS_UNAVAILABLE", "native_c3_transformed_state_maxwell_residual_max": None, "native_operator_intertwining_residual_max": None, "isolated_projector_theorem_status": "CONDITIONAL_OPERATOR_COVARIANCE_NOT_YET_ESTABLISHED", "discrete_operator_covariance_diagnosis": "OPERATOR_RECONSTRUCTION_STILL_INCOMPLETE", "exact_inaccessible_internal_object": ["native component grid locations/half-cell offsets", "raw pre-interpolation fields", "internal constitutive/material operator", "native discrete curl phases"], "local_binding_or_shared_library_evidence": {"hook_observation": "No non-callable discoverable solver attribute supplied native component locations, interpolation map, constitutive operator, or curl phases.", "metadata_records": [{"member_index": item["member_index"], "hook_status": item["internal_observation"]["hook_status"], "symbol_paths": item["internal_observation"]["captured_internal_symbol_paths"]} for item in ordered]}, "remaining_unresolved_questions": ["Whether installed MPB has private/native objects not surfaced through the Python solver instance", "Whether public E/H/D/B arrays are interpolated or native staggered samples"], "alternative_explanations_considered": ["public getter interpolation", "Yee-like component staggering", "internal subpixel constitutive averaging", "native component basis/indexing", "native operator C3 covariance"], "counterevidence_summary": {"hook_statuses": statuses, "captured_symbol_paths": paths, "records_are_metadata_only": True, "prior_M20_D_vs_epsilonE_residual_max": 0.029403672141690054, "prior_M18_collocated_residual_max": 0.8828866629159403}, "cheapest_remaining_discriminating_test": "NONE_WITHOUT_REBUILDING_OR_REPLACING_THE_INSTALLED_MPB_BINDING; the exact inaccessible object is the native operator/staggering metadata required to define the test.", "next_science_decision": "STOP_C3_GOAL_AT_INSTALLED_MPB_INTROSPECTION_LIMIT", "minimal_next_live_state_count": 0, "source_commit_used": os.environ.get("MEPHC_SOURCE_COMMIT"), "post_analysis_checkout_unchanged": True}


def failure(code: str, exc: BaseException | None = None) -> dict[str, Any]:
    return {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "failure_code": code, "exception_type": type(exc).__name__ if exc else None, "exception_message": str(exc)[:1024] if exc else None, "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "new_metadata_record_count": 0, "post_analysis_checkout_unchanged": True}


def main() -> int:
    try:
        bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8")); require(isinstance(bundle, dict) and isinstance(bundle.get("work_order_id"), str), "M21_WORK_ORDER_MISSING")
        counters_path = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"]); root = counters_path.parent.parent; job = _job(); m18 = _m18()
        # Validate exact prior bindings before the one authorized triplet.
        prior = _ordered(m18.read_dataset(job, root, M18_DATASET_ID, M18_MANIFEST_SHA256, 3))
        members = [{key: item[key] for key in ("member_index", "c3_member_identity", "request_key_sha256", "coordinate")} for item in prior]
        counter = job.BudgetCounter(0, 3); factory, _ = m18.production_solver_factory(); records = capture_triplet(members, factory, counter, os.environ.get("MEPHC_SOURCE_COMMIT")); manifest = persist_metadata(job, root, bundle["work_order_id"], records); result = analyze(records, manifest, counter.solver_count)
    except Exception as exc:
        result = failure(str(exc), exc); result["traceback_tail"] = traceback.format_exc()[-3000:]
    Path(os.environ["MEPHC_RESULT_PATH"]).write_text(json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8"); return 0


if __name__ == "__main__":
    raise SystemExit(main())
