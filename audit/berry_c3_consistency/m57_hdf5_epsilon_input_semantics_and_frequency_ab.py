"""M57: bounded HDF5 epsilon_input_file semantic probe and frequency A/B.

M56R1 proved that a single HDF5 dataset can be written and reopened locally,
but MPB's scalar readback did not match.  This arm tests one fixed, small
semantic matrix (dataset ``data``, direct/transposed axis order, and explicit
periodic cell shifts) using init-only material readback.  The first candidate
passing scalar, mean, scalar-C3, and full inverse-epsilon tensor-C3 gates is
frozen before any eigensolver is allowed.
"""
from __future__ import annotations

import hashlib
import importlib.util
import inspect
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
M54_PATH = ROOT / "audit/berry_c3_consistency/m54_r256_material_grid_subpixel_c3_readback_ab.py"
SPEC = importlib.util.spec_from_file_location("m57_m54_reference", M54_PATH)
assert SPEC and SPEC.loader
m54 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m54)

RESULT_SCHEMA = "mephc-berry-c3-consistency-m57-hdf5-input-semantics-frequency-ab-v1"
DATASET_SCHEMA = "mephc-berry-c3-consistency-m57-hdf5-semantics-frequency-dataset-v1"
MESH1_DATASET_ID = "9b560f99fa264905ee99cb68d4ccdf757446ffb7b3a0af0391d5760a9740861d"
MESH1_MANIFEST = "c009e68d08bd13084eb0320d95ecda5ceab57bdafa8fddef30ecc5b1177563ed"
MESH1_SCHEMA = "mephc-berry-c3-consistency-m50-r256-mesh1-c3-causal-control-dataset-v1"
M54R1_DATASET_ID = "f150ed53224492d2ba638b9ee074850e5757aa002a6be7e2039a09096b0eb7b7"
M54R1_MANIFEST = "3021651351dba3e61f9c27d32fce1c79e9ee67f13c11065a952f72ecef623604"
M54R1_SCHEMA = "mephc-berry-c3-consistency-m54r1-r256-material-grid-subpixel-readback-dataset-v1"
MEMBERS = ("IDENTITY", "C3", "C3_SQUARED")
SHAPE = (256, 256)


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise ValueError(f"{code}:{detail}" if detail else code)


def _safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if np.isfinite(value) else ("INF" if value > 0 else "-INF" if value < 0 else "NAN")
    if isinstance(value, np.generic):
        return _safe(value.item())
    if isinstance(value, np.ndarray):
        return _safe(value.tolist())
    if isinstance(value, Mapping):
        return {str(k): _safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(v) for v in value]
    raise ValueError(f"M57_UNSAFE_RESULT:{type(value).__name__}")


def _read_dataset(job: Any, state_root: Path, dataset_id: str, manifest: str, schema: str, count: int) -> list[dict[str, Any]]:
    verified = job.verify_dataset(state_root, dataset_id)
    require(verified.get("dataset_id") == dataset_id and verified.get("manifest_sha256") == manifest and verified.get("record_count") == count, "M57_DATASET_BINDING_INVALID", dataset_id)
    rows = []
    for key in verified["record_key_sha256"]:
        value = json.loads(job.resolve_dataset_record(state_root, dataset_id, manifest, key)["payload"].decode("utf-8"))
        require(isinstance(value, dict) and value.get("schema") == schema, "M57_DATASET_SCHEMA_INVALID", dataset_id)
        rows.append(value)
    return rows


def _frequency_rows(records: list[dict[str, Any]]) -> dict[tuple[int, int, str], dict[str, Any]]:
    rows = {(int(row["vertex_index"]), int(row["repeat_index"]), str(row["c3_member_identity"])): row for row in records}
    require(len(rows) == 36 and set(rows) == {(v, r, m) for v in range(4) for r in range(3) for m in MEMBERS}, "M57_FREQUENCY_IDENTITY_SET_INVALID")
    return rows


def frequency_ledger(rows: Mapping[tuple[int, int, str], Mapping[str, Any]]) -> dict[str, Any]:
    failures, ledger = [], {}
    for vertex in range(4):
        for source, target in zip(MEMBERS, MEMBERS[1:] + MEMBERS[:1]):
            for band in range(4):
                left = np.asarray([float(rows[(vertex, repeat, source)]["frequencies_bands_1_to_4"][band]) for repeat in range(3)])
                right = np.asarray([float(rows[(vertex, repeat, target)]["frequencies_bands_1_to_4"][band]) for repeat in range(3)])
                lm, rm = float(np.median(left)), float(np.median(right)); lu, ru = float(np.max(np.abs(left - lm))), float(np.max(np.abs(right - rm)))
                item = {"vertex": vertex, "band": band + 1, "source_member": source, "target_member": target, "source_median": lm, "target_median": rm, "source_repeat_uncertainty": lu, "target_repeat_uncertainty": ru, "residual": abs(lm - rm), "combined_repeat_uncertainty": lu + ru, "pass": abs(lm - rm) <= lu + ru}
                ledger[f"v{vertex}:{source}_to_{target}:band{band + 1}"] = item
                if not item["pass"]:
                    failures.append(item)
    return {"failure_set": failures, "failure_count": len(failures), "ledger": ledger}


def scalar_patch_needed(covariance: Mapping[str, Any]) -> bool:
    return covariance["scalar_c3_status"] == "FAIL" and float(covariance["scalar_projection_linf"]) > float(covariance["scalar_identity_guard"])


def projected_epsilon(epsilon: Any, index_map: Any) -> tuple[np.ndarray, dict[str, Any]]:
    value = np.asarray(epsilon, dtype=float); require(value.shape == SHAPE and np.all(np.isfinite(value)) and np.all(value > 0.0), "M57_EPSILON_INPUT_INVALID")
    projected = (value + m54.apply_grid(value, index_map) + m54.apply_grid(value, m54.apply_grid(index_map, index_map))) / 3.0; guard = m54.identity_guard(projected); covariance = float(np.max(np.abs(projected - m54.apply_grid(projected, index_map)))); mean_residual = abs(float(np.mean(projected) - np.mean(value)))
    require(covariance <= guard and mean_residual <= guard, "M57_PROJECTED_EPSILON_INVARIANT_INVALID")
    return projected, {"identity_guard": guard, "projected_c3_residual_max": covariance, "global_mean_residual": mean_residual, "projection_linf": float(np.max(np.abs(projected - value))), "projection_l1": float(np.sum(np.abs(projected - value))), "projection_l2": float(np.linalg.norm(projected - value)), "corrected_cell_count": int(np.count_nonzero(np.abs(projected - value) > guard))}


def hdf5_variant_values(projected: np.ndarray, axis_mode: str, shift: tuple[int, int]) -> np.ndarray:
    value = np.asarray(projected, dtype=np.float64)
    require(value.shape == SHAPE, "M57_HDF5_VARIANT_SHAPE_INVALID")
    encoded = value if axis_mode == "direct" else value.T if axis_mode == "transpose" else None
    require(encoded is not None, "M57_HDF5_AXIS_MODE_INVALID", axis_mode)
    return np.roll(encoded, shift=shift, axis=(0, 1))


def write_verify_hdf5(writer: Any, path: Path, values: np.ndarray) -> dict[str, Any]:
    value = np.asarray(values, dtype=np.float64); require(value.shape == SHAPE and np.all(np.isfinite(value)), "M57_HDF5_VALUES_INVALID")
    digest = hashlib.sha256(value.tobytes()).hexdigest()
    with writer.File(str(path), "w") as handle:
        handle.create_dataset("data", data=value)
    with writer.File(str(path), "r") as handle:
        names = []
        def visitor(name: str, node: Any) -> None:
            if hasattr(node, "shape"):
                names.append(name)
        handle.visititems(visitor); require(names == ["data"], "M57_HDF5_DATASET_SET_INVALID", str(names)); data = np.asarray(handle["data"], dtype=np.float64)
    actual = hashlib.sha256(data.tobytes()).hexdigest(); require(data.shape == SHAPE and np.array_equal(data, value) and actual == digest, "M57_HDF5_ROUNDTRIP_INVALID")
    return {"dataset_name": "data", "dataset_names": names, "shape": list(data.shape), "dtype": str(data.dtype), "value_sha256": actual, "roundtrip_verified": True}


def binding_evidence(mode_solver: Any) -> dict[str, Any]:
    try:
        signature = str(inspect.signature(mode_solver))
    except (TypeError, ValueError):
        signature = "UNAVAILABLE"
    doc = inspect.getdoc(mode_solver) or ""
    try:
        source = inspect.getsource(mode_solver); source_hash = hashlib.sha256(source.encode("utf-8")).hexdigest(); source_available = True
    except (OSError, TypeError):
        source = ""; source_hash = None; source_available = False
    text = (signature + " " + doc + " " + source).lower()
    return {"symbol": "meep.mpb.ModeSolver", "signature": signature[:512], "doc_first_line": doc.splitlines()[0][:256] if doc else "", "source_available": source_available, "source_excerpt_sha256": source_hash, "epsilon_input_file_exposed": "epsilon_input_file" in text, "hdf5_or_first_dataset_evidence": any(token in text for token in ("hdf5", "first dataset", "dataset"))}


def semantic_candidates() -> list[dict[str, Any]]:
    # This is intentionally finite and declared, not an optimization search.
    return [{"dataset_name": "data", "axis_mode": axis, "periodic_shift": list(shift), "candidate_id": f"DATA_{axis.upper()}_SHIFT_{shift[0]}_{shift[1]}"} for axis in ("direct", "transpose") for shift in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1))]


def build_solver(mp: Any, mpb: Any, band: Any, coordinate: Any, hdf5_path: Path) -> Any:
    reciprocal = mp.cartesian_to_reciprocal(mp.Vector3(float(coordinate[0]), float(coordinate[1]), 0.0), band.geo_latt)
    return mpb.ModeSolver(geometry=[], geometry_lattice=band.geo_latt, k_points=[reciprocal], resolution=256, num_bands=4, default_material=mp.air, tolerance=1e-9, deterministic=True, mesh_size=1, epsilon_input_file=str(hdf5_path))


def material_gate(solver: Any, projected: np.ndarray, mp: Any) -> dict[str, Any]:
    init = getattr(solver, "init_params", None); parity = getattr(mp, "NO_PARITY", None); require(callable(init) and parity is not None, "M57_INIT_PARAMS_UNAVAILABLE"); init(parity, False)
    epsilon = np.asarray(solver.get_epsilon(), dtype=float).reshape(SHAPE); index_map = m54.build_index_map(); guard = m54.identity_guard(projected); scalar_residual = float(np.max(np.abs(epsilon - projected))); scalar_c3 = float(np.max(np.abs(epsilon - m54.apply_grid(epsilon, index_map)))); mean_residual = abs(float(np.mean(epsilon) - np.mean(projected)))
    gate = {"scalar_readback_sha256": hashlib.sha256(epsilon.tobytes()).hexdigest(), "scalar_readback_residual_max": scalar_residual, "scalar_readback_c3_residual_max": scalar_c3, "scalar_readback_mean_residual": mean_residual, "scalar_readback_guard": guard, "scalar_readback_gate": bool(scalar_residual <= guard and scalar_c3 <= guard and mean_residual <= guard)}
    if not gate["scalar_readback_gate"]:
        gate.update({"tensor_readback_gate": False, "operator_gate": False}); return gate
    getter = getattr(solver, "get_epsilon_inverse_tensor_point", None); require(callable(getter), "M57_INVERSE_TENSOR_GETTER_UNAVAILABLE"); tensor = np.empty((*SHAPE, 3, 3), dtype=np.complex128)
    for i in range(SHAPE[0]):
        for j in range(SHAPE[1]):
            tensor[i, j] = m54._tensor(getter(mp.Vector3(float(i) / SHAPE[0], float(j) / SHAPE[1], 0.0)))
    covariance = m54.material_covariance(epsilon, tensor, index_map); gate.update({"tensor_readback_sha256": hashlib.sha256(tensor.tobytes()).hexdigest(), "tensor_c3_residual_fro_max": covariance["tensor_c3_residual_fro_max"], "tensor_identity_guard": covariance["tensor_identity_guard"], "tensor_readback_c3_status": covariance["tensor_c3_status"], "tensor_readback_gate": covariance["tensor_c3_status"] == "PASS", "operator_gate": covariance["tensor_c3_status"] == "PASS"}); return gate


def classify(stock: Mapping[str, Any], patch: Mapping[str, Any]) -> tuple[str, str, dict[str, set[tuple[Any, ...]]]]:
    stock_set = {(x["vertex"], x["band"], x["source_member"], x["target_member"]) for x in stock["failure_set"]}; patch_set = {(x["vertex"], x["band"], x["source_member"], x["target_member"]) for x in patch["failure_set"]}; restored, persistent, new = stock_set - patch_set, stock_set & patch_set, patch_set - stock_set; sets = {"restored": restored, "persistent": persistent, "new_failures": new}
    if not stock_set: return "R256_STOCK_MESH1_FREQUENCY_FAILURE_NOT_REPRODUCED", "R256_MESH1_FREQUENCY_SCALAR_REQUALIFICATION", sets
    if not patch_set: return "R256_HDF5_SEMANTICS_FULL_FREQUENCY_RESTORATION", "PATCHED_SIMPLE_C3_LADDER_GAP_SCALAR_RANK2_REQUALIFICATION", sets
    if restored and persistent and not new: return "R256_HDF5_SEMANTICS_PARTIAL_FREQUENCY_RESTORATION", "MPB_K_DEPENDENT_OPERATOR_C3_AUDIT_WITH_SCALAR_RASTER_CONTRIBUTOR", sets
    if new: return "R256_HDF5_SEMANTICS_INTRODUCES_NEW_FAILURES", "HDF5_INPUT_OR_CONSTITUTIVE_OPERATOR_ADJUDICATION", sets
    return "R256_HDF5_SEMANTICS_NO_FREQUENCY_RESTORATION", "MPB_K_DEPENDENT_DISCRETE_OPERATOR_C3_SOURCE_AUDIT", sets


def _base(bundle: Mapping[str, Any], source_commit: str, stock: Mapping[str, Any], base: Mapping[str, Any], projection: Mapping[str, Any]) -> dict[str, Any]:
    return {"schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "dataset_write": False, "dataset_schema": DATASET_SCHEMA, "source_commit_used": source_commit, "stock_frequency": stock, "scalar_tensor_base_status": {key: base[key] for key in ("scalar_c3_status", "tensor_c3_status", "scalar_c3_residual_max", "tensor_c3_residual_fro_max", "scalar_identity_guard", "tensor_identity_guard")}, "projection": projection, "fields_gaps_subspaces_wilson_berry_computed": False, "post_native_checkout_unchanged": True}


def main() -> int:
    bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8")); source_commit = str(os.environ.get("MEPHC_SOURCE_COMMIT") or bundle.get("source_commit") or ""); records: list[dict[str, Any]] = []
    try:
        job = m54.m52r1.m41r3._load(ROOT / "tools/mephc-flow/scientific_job.py", "m57_job"); state_root = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"]).parent.parent; stock_records = _read_dataset(job, state_root, MESH1_DATASET_ID, MESH1_MANIFEST, MESH1_SCHEMA, 36); stock_rows = _frequency_rows(stock_records); stock = frequency_ledger(stock_rows); material_records = _read_dataset(job, state_root, M54R1_DATASET_ID, M54R1_MANIFEST, M54R1_SCHEMA, 3); mesh1 = next(row for row in material_records if int(row["mesh_size"]) == 1); epsilon = m54.decode_array(mesh1["epsilon_grid"]); tensor = m54.decode_array(mesh1["inverse_epsilon_tensor_grid"]); index_map = m54.build_index_map(); base = m54.material_covariance(epsilon, tensor, index_map); projected, projection = projected_epsilon(epsilon, index_map)
        if not stock["failure_set"]:
            result = _base(bundle, source_commit, stock, base, projection); result.update({"classification": "R256_STOCK_MESH1_FREQUENCY_FAILURE_NOT_REPRODUCED", "causal_outcome": "R256_STOCK_MESH1_FREQUENCY_FAILURE_NOT_REPRODUCED", "next_science_decision": "R256_MESH1_FREQUENCY_SCALAR_REQUALIFICATION", "zero_solver_reason": "F_stock_empty"})
        elif not scalar_patch_needed(base):
            result = _base(bundle, source_commit, stock, base, projection); result.update({"classification": "R256_SCALAR_PATCH_NOT_REQUIRED_TENSOR_ONLY_BASE_DEFECT", "causal_outcome": "R256_SCALAR_PATCH_NOT_REQUIRED_TENSOR_ONLY_BASE_DEFECT", "next_science_decision": "MESH1_INVERSE_EPSILON_TENSOR_C3_PATCH_AND_FREQUENCY_AB", "zero_solver_reason": "scalar_projection_identity_within_machine_guard"})
        else:
            import meep as mp
            from meep import mpb
            from mephc.band import Band
            binding = binding_evidence(getattr(mpb, "ModeSolver", None)); audit = {"binding": binding, "candidate_order": semantic_candidates()}
            if not binding["epsilon_input_file_exposed"]:
                result = _base(bundle, source_commit, stock, base, projection); result.update({"classification": "R256_HDF5_INPUT_SEMANTICS_NOT_EXPOSED", "causal_outcome": "R256_HDF5_INPUT_SEMANTICS_NOT_EXPOSED", "next_science_decision": "IMPLEMENT_PROJECT_CONTAINED_OR_VENDORED_MPB_EXACT_EPSILON_INPUT_INTERFACE", "semantic_audit": audit, "zero_solver_reason": "epsilon_input_file_not_publicly_confirmed"})
            else:
                try:
                    import h5py
                except ImportError:
                    h5py = None
                if h5py is None:
                    result = _base(bundle, source_commit, stock, base, projection); result.update({"classification": "R256_HDF5_WRITER_UNAVAILABLE", "causal_outcome": "R256_HDF5_WRITER_UNAVAILABLE", "next_science_decision": "IMPLEMENT_PROJECT_CONTAINED_HDF5_EPSILON_INPUT_WRITER", "semantic_audit": audit, "zero_solver_reason": "h5py_not_installed"})
                else:
                    band = Band(a=400.0, r1=80.14335684352235, r2=75.13439704080221, n_eff=2.7, h=100.0, resolution=256, lattice_type="triangular", polarization="TE", structure_type="slab"); attempts = []; frozen = None; frozen_gate = None; frozen_hdf5 = None
                    for candidate in semantic_candidates():
                        handle = tempfile.NamedTemporaryFile(prefix="mephc_m57_semantics_", suffix=".h5", delete=False); path = Path(handle.name); handle.close(); values = hdf5_variant_values(projected, candidate["axis_mode"], tuple(candidate["periodic_shift"])); item = dict(candidate)
                        try:
                            hdf5 = write_verify_hdf5(h5py, path, values); solver = build_solver(mp, mpb, band, stock_rows[(0, 0, "IDENTITY")]["coordinate"], path); gate = material_gate(solver, projected, mp); item.update({"hdf5": hdf5, "material_gate": gate, "status": "PASS" if gate.get("operator_gate") else "GATE_FAILED"}); attempts.append(item)
                            if gate.get("operator_gate"):
                                frozen, frozen_gate, frozen_hdf5 = candidate, gate, hdf5; frozen_hdf5["path"] = str(path); break
                        except BaseException as exc:
                            item.update({"status": "FAILED", "failure_code": str(exc)[:512]}); attempts.append(item)
                    audit["attempts"] = attempts
                    if frozen is None:
                        scalar_passed = any(item.get("material_gate", {}).get("scalar_readback_gate") for item in attempts); result = _base(bundle, source_commit, stock, base, projection); result.update({"classification": "R256_HDF5_SEMANTICS_SCALAR_READBACK_FAILED" if not scalar_passed else "R256_HDF5_SEMANTICS_TENSOR_OPERATOR_C3_FAILED", "causal_outcome": "R256_HDF5_SEMANTICS_SCALAR_READBACK_FAILED" if not scalar_passed else "R256_HDF5_SEMANTICS_TENSOR_OPERATOR_C3_FAILED", "next_science_decision": "IMPLEMENT_PROJECT_CONTAINED_OR_VENDORED_MPB_EXACT_EPSILON_INPUT_INTERFACE" if not scalar_passed else "IMPLEMENT_C3_COVARIANT_INVERSE_EPSILON_OPERATOR_PATCH_AND_FREQUENCY_AB", "semantic_audit": audit, "zero_solver_reason": "no_candidate_passed_material_operator_gates"})
                    else:
                        namespace = {"goal_id": "MEPHC-BERRY-C3-CONSISTENCY-V1", "work_order_id": bundle["work_order_id"], "source_commit": source_commit, "record_schema": DATASET_SCHEMA}; store = job.ImmutableDatasetStore(state_root, namespace); path = Path(frozen_hdf5["path"])
                        for member_index, member in enumerate(MEMBERS):
                            for repeat in range(3):
                                for vertex in range(4):
                                    spec = stock_rows[(vertex, repeat, member)]; solver = build_solver(mp, mpb, band, spec["coordinate"], path); solver.run_parity(mp.TE, False); frequencies = np.asarray(solver.all_freqs, dtype=float); require(frequencies.reshape(-1)[:4].size == 4, "M57_FREQUENCY_LAYOUT_INVALID"); item = {"schema": DATASET_SCHEMA, "record_id": None, "member_index": member_index, "c3_member_identity": member, "repeat_index": repeat, "vertex_index": vertex, "coordinate": list(spec["coordinate"]), "geometry_id": "G15", "resolution": 256, "tolerance": 1e-9, "mesh_size": 1, "deterministic": True, "polarization": "TE", "frequencies_bands_1_to_4": [float(v) for v in frequencies.reshape(-1)[:4]], "hdf5_semantic_candidate_id": frozen["candidate_id"], "hdf5_dataset_sha256": frozen_hdf5["value_sha256"], "projected_epsilon_sha256": hashlib.sha256(projected.tobytes()).hexdigest(), "scalar_readback_sha256": frozen_gate["scalar_readback_sha256"], "tensor_readback_sha256": frozen_gate["tensor_readback_sha256"], "source_commit": source_commit}; item["record_id"] = "MEPHC-M57-HDF5-FREQ-" + hashlib.sha256(canonical({k: v for k, v in item.items() if k != "record_id"})).hexdigest(); store.put(canonical({"work_order_id": bundle["work_order_id"], "member": member, "repeat": repeat, "vertex": vertex}), canonical(item), {"member": member, "repeat": repeat, "vertex": vertex, "record_id": item["record_id"]}); records.append(item)
                        manifest = store.finalize(36, {"dataset_schema": DATASET_SCHEMA, "semantic_candidate_id": frozen["candidate_id"], "source_parent_dataset_ids": [MESH1_DATASET_ID, M54R1_DATASET_ID]}); patch = frequency_ledger(_frequency_rows(records)); classification, decision, sets = classify(stock, patch); result = _base(bundle, source_commit, stock, base, projection); result.update({"solver_execution_count": 36, "dataset_record_count": 36, "dataset_write": True, "dataset_id": manifest.get("dataset_id"), "manifest_sha256": manifest.get("manifest_sha256"), "semantic_audit": audit, "selected_semantics": frozen, "material_operator_gate": frozen_gate, "patched_frequency": patch, "failure_set_relations": {key: sorted(value) for key, value in sets.items()}, "classification": classification, "causal_outcome": classification, "next_science_decision": decision})
    except BaseException as exc:
        result = {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": len(records), "dataset_record_count": len(records), "dataset_write": bool(records), "failure_code": str(exc)[:1024], "failure_stage": "m57_hdf5_epsilon_input_semantics_and_frequency_ab", "exception_type": type(exc).__name__, "source_commit_used": source_commit, "completed_record_ids": [row["record_id"] for row in records], "post_native_checkout_unchanged": True}
    Path(os.environ["MEPHC_RESULT_PATH"]).write_text(json.dumps(_safe(result), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8"); return 0


if __name__ == "__main__":
    raise SystemExit(main())
