"""M55R1: public scalar-epsilon input discovery and bounded frequency A/B.

The M55 failure only established that one ``meep.mpb.MaterialGrid`` lookup
was unavailable.  This corrective arm first adjudicates the persisted scalar
and inverse-tensor material separately, then probes only documented public
binding paths.  A candidate is frozen only after an init-only epsilon
readback gate; failed candidates never reach an eigensolver.
"""
from __future__ import annotations

import hashlib
import importlib.util
import inspect
import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
M54_PATH = ROOT / "audit/berry_c3_consistency/m54_r256_material_grid_subpixel_c3_readback_ab.py"
SPEC = importlib.util.spec_from_file_location("m55r1_m54_reference", M54_PATH)
assert SPEC and SPEC.loader
m54 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m54)

RESULT_SCHEMA = "mephc-berry-c3-consistency-m55r1-public-epsilon-input-frequency-ab-v1"
DATASET_SCHEMA = "mephc-berry-c3-consistency-m55r1-public-epsilon-input-frequency-dataset-v1"
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
    raise ValueError(f"M55R1_UNSAFE_RESULT:{type(value).__name__}")


def _read_dataset(job: Any, state_root: Path, dataset_id: str, manifest: str, schema: str, count: int) -> list[dict[str, Any]]:
    verified = job.verify_dataset(state_root, dataset_id)
    require(verified.get("dataset_id") == dataset_id, "M55R1_DATASET_ID_INVALID", dataset_id)
    require(verified.get("manifest_sha256") == manifest and verified.get("record_count") == count, "M55R1_DATASET_BINDING_INVALID", dataset_id)
    records = []
    for key in verified["record_key_sha256"]:
        payload = job.resolve_dataset_record(state_root, dataset_id, manifest, key)["payload"]
        value = json.loads(payload.decode("utf-8"))
        require(isinstance(value, dict) and value.get("schema") == schema, "M55R1_DATASET_SCHEMA_INVALID", dataset_id)
        records.append(value)
    return records


def _frequency_rows(records: list[dict[str, Any]]) -> dict[tuple[int, int, str], dict[str, Any]]:
    rows = {(int(row["vertex_index"]), int(row["repeat_index"]), str(row["c3_member_identity"])): row for row in records}
    require(len(rows) == 36, "M55R1_FREQUENCY_COVERAGE_INVALID")
    require(set(rows) == {(v, r, m) for v in range(4) for r in range(3) for m in MEMBERS}, "M55R1_FREQUENCY_IDENTITY_SET_INVALID")
    return rows


def frequency_ledger(rows: Mapping[tuple[int, int, str], Mapping[str, Any]]) -> dict[str, Any]:
    failures, ledger = [], {}
    for vertex in range(4):
        for source, target in zip(MEMBERS, MEMBERS[1:] + MEMBERS[:1]):
            for band in range(4):
                left = np.asarray([float(rows[(vertex, repeat, source)]["frequencies_bands_1_to_4"][band]) for repeat in range(3)])
                right = np.asarray([float(rows[(vertex, repeat, target)]["frequencies_bands_1_to_4"][band]) for repeat in range(3)])
                lm, rm = float(np.median(left)), float(np.median(right))
                lu, ru = float(np.max(np.abs(left - lm))), float(np.max(np.abs(right - rm)))
                item = {"vertex": vertex, "band": band + 1, "source_member": source, "target_member": target, "source_median": lm, "target_median": rm, "source_repeat_uncertainty": lu, "target_repeat_uncertainty": ru, "residual": abs(lm - rm), "combined_repeat_uncertainty": lu + ru, "pass": abs(lm - rm) <= lu + ru}
                ledger[f"v{vertex}:{source}_to_{target}:band{band + 1}"] = item
                if not item["pass"]:
                    failures.append(item)
    return {"failure_set": failures, "failure_count": len(failures), "ledger": ledger}


def scalar_patch_needed(covariance: Mapping[str, Any]) -> bool:
    return covariance["scalar_c3_status"] == "FAIL" and float(covariance["scalar_projection_linf"]) > float(covariance["scalar_identity_guard"])


def projected_epsilon(epsilon: Any, index_map: Any) -> tuple[np.ndarray, dict[str, Any]]:
    value = np.asarray(epsilon, dtype=float)
    require(value.shape == SHAPE and np.all(np.isfinite(value)) and np.all(value > 0.0), "M55R1_EPSILON_INPUT_INVALID")
    second = m54.apply_grid(index_map, index_map)
    projected = (value + m54.apply_grid(value, index_map) + m54.apply_grid(value, second)) / 3.0
    guard = m54.identity_guard(projected)
    covariance = float(np.max(np.abs(projected - m54.apply_grid(projected, index_map))))
    mean_residual = abs(float(np.mean(projected) - np.mean(value)))
    require(covariance <= guard, "M55R1_PROJECTED_EPSILON_C3_INVALID", str(covariance))
    require(mean_residual <= guard, "M55R1_PROJECTED_EPSILON_MEAN_CHANGED", str(mean_residual))
    return projected, {"identity_guard": guard, "projected_c3_residual_max": covariance, "global_mean_residual": mean_residual, "projection_linf": float(np.max(np.abs(projected - value))), "projection_l1": float(np.sum(np.abs(projected - value))), "projection_l2": float(np.linalg.norm(projected - value)), "corrected_cell_count": int(np.count_nonzero(np.abs(projected - value) > guard))}


def _inspect_public(value: Any) -> dict[str, Any]:
    if value is None:
        return {"available": False, "callable": False}
    try:
        signature = str(inspect.signature(value))
    except (TypeError, ValueError):
        signature = "UNAVAILABLE"
    doc = inspect.getdoc(value) or ""
    return {"available": True, "callable": callable(value), "signature": signature[:512], "doc_first_line": doc.splitlines()[0][:256] if doc else "", "public": not getattr(value, "__name__", "").startswith("_")}


def _grid_candidate(grid_type: Any, mp: Any, epsilon: np.ndarray) -> Any:
    low, high = float(np.min(epsilon)), float(np.max(epsilon))
    if abs(high - low) <= np.finfo(float).eps:
        high = low + 1.0
    weights = (epsilon - low) / (high - low)
    medium = getattr(mp, "Medium")
    return grid_type(mp.Vector3(256, 256, 0), medium(epsilon=low), medium(epsilon=high), weights=weights, do_averaging=False)


def _solver(mp: Any, mpb: Any, band: Any, coordinate: Any, material: Any, mode: str) -> Any:
    reciprocal = mp.cartesian_to_reciprocal(mp.Vector3(float(coordinate[0]), float(coordinate[1]), 0.0), band.geo_latt)
    if mode == "default_material":
        geometry = []
        default_material = material
    else:
        block = getattr(mp, "Block")
        full = getattr(mp, "inf", 1.0e9)
        geometry = [block(size=mp.Vector3(1, 1, full), material=material)]
        default_material = mp.air
    return mpb.ModeSolver(geometry=geometry, geometry_lattice=band.geo_latt, k_points=[reciprocal], resolution=256, num_bands=4, default_material=default_material, tolerance=1e-9, deterministic=True, mesh_size=1)


def _readback_gate(solver: Any, projected: np.ndarray, mp: Any) -> dict[str, Any]:
    init = getattr(solver, "init_params", None)
    parity = getattr(mp, "NO_PARITY", None)
    require(callable(init) and parity is not None, "M55R1_INIT_PARAMS_UNAVAILABLE")
    init(parity, False)
    readback = np.asarray(solver.get_epsilon(), dtype=float).reshape(SHAPE)
    guard = m54.identity_guard(projected)
    residual = float(np.max(np.abs(readback - projected)))
    covariance = float(np.max(np.abs(readback - m54.apply_grid(readback, m54.build_index_map()))))
    mean_residual = abs(float(np.mean(readback) - np.mean(projected)))
    return {"readback_shape": list(readback.shape), "readback_sha256": hashlib.sha256(readback.tobytes()).hexdigest(), "readback_identity_guard": guard, "readback_residual_max": residual, "readback_c3_residual_max": covariance, "readback_mean_residual": mean_residual, "readback_gate": bool(residual <= guard and covariance <= guard and mean_residual <= guard)}


def discover_public_input(mp: Any, mpb: Any, band: Any, coordinate: Any, projected: np.ndarray) -> tuple[str | None, Any | None, dict[str, Any]]:
    mode = getattr(mpb, "ModeSolver", None)
    mode_evidence = _inspect_public(mode)
    candidates: list[tuple[str, Any, str, dict[str, Any]]] = []
    supported_names = [name.strip() for name in mode_evidence.get("signature", "").replace("(", ",").replace(")", ",").split(",") if "epsilon" in name.lower() or "material_input" in name.lower()]
    candidates.append(("MODE_SOLVER_EXPLICIT_EPSILON_INPUT", mode, "explicit", {"mode_solver": mode_evidence, "supported_parameter_names": supported_names}))
    mp_grid = getattr(mp, "MaterialGrid", None)
    candidates.append(("MEEP_MATERIAL_GRID_DEFAULT_MATERIAL", mp_grid, "default_material", {"symbol": "meep.MaterialGrid", "binding": _inspect_public(mp_grid), "mode_solver": mode_evidence}))
    candidates.append(("MEEP_MATERIAL_GRID_FULL_CELL_BLOCK", mp_grid, "full_cell_block", {"symbol": "meep.MaterialGrid", "binding": _inspect_public(mp_grid), "block": _inspect_public(getattr(mp, "Block", None)), "mode_solver": mode_evidence}))
    mpb_grid = getattr(mpb, "MaterialGrid", None)
    candidates.append(("MPB_MATERIAL_GRID", mpb_grid, "default_material", {"symbol": "meep.mpb.MaterialGrid", "binding": _inspect_public(mpb_grid), "mode_solver": mode_evidence}))
    callback_names = [name for name in ("epsilon_func", "epsilon_callback", "material_callback") if name in mode_evidence.get("signature", "")]
    candidates.append(("EXPLICIT_PUBLIC_EPSILON_OR_MATERIAL_CALLBACK", mode, "callback", {"mode_solver": mode_evidence, "callback_parameter_names": callback_names}))
    attempts = []
    for mechanism, symbol, construction, evidence in candidates:
        item = {"mechanism_id": mechanism, "availability": bool(callable(symbol)), "construction_mode": construction, "binding_evidence": evidence}
        if not callable(symbol):
            item["construction_status"] = "UNAVAILABLE"
            attempts.append(item)
            continue
        if construction in ("explicit", "callback"):
            item["construction_status"] = "UNSUPPORTED_WITHOUT_EXPLICIT_DOCUMENTED_SEMANTICS"
            attempts.append(item)
            continue
        try:
            material = _grid_candidate(symbol, mp, projected)
            solver = _solver(mp, mpb, band, coordinate, material, construction)
            gate = _readback_gate(solver, projected, mp)
            item["construction_status"] = "BUILT"
            item["readback_gate"] = gate
            attempts.append(item)
            if gate["readback_gate"]:
                return mechanism, solver, {"attempts": attempts, "frozen_candidate": mechanism}
        except BaseException as exc:
            item["construction_status"] = "FAILED"
            item["failure_code"] = str(exc)[:512]
            attempts.append(item)
    return None, None, {"attempts": attempts, "frozen_candidate": None}


def classify(stock: Mapping[str, Any], patch: Mapping[str, Any]) -> tuple[str, str, dict[str, set[tuple[Any, ...]]]]:
    stock_set = {(x["vertex"], x["band"], x["source_member"], x["target_member"]) for x in stock["failure_set"]}
    patch_set = {(x["vertex"], x["band"], x["source_member"], x["target_member"]) for x in patch["failure_set"]}
    restored, persistent, new = stock_set - patch_set, stock_set & patch_set, patch_set - stock_set
    sets = {"restored": restored, "persistent": persistent, "new_failures": new}
    if not stock_set:
        return "R256_STOCK_MESH1_FREQUENCY_FAILURE_NOT_REPRODUCED", "R256_MESH1_FREQUENCY_SCALAR_REQUALIFICATION", sets
    if not patch_set and not new:
        return "R256_PROJECTED_EPSILON_FULL_FREQUENCY_RESTORATION", "PATCHED_M7_SIMPLE_C3_LADDER_GAP_SCALAR_RANK2_REQUALIFICATION", sets
    if restored and persistent and not new:
        return "R256_PROJECTED_EPSILON_PARTIAL_FREQUENCY_RESTORATION", "MPB_K_DEPENDENT_OPERATOR_C3_AUDIT_WITH_SCALAR_RASTER_CONTRIBUTOR", sets
    if new:
        return "R256_PROJECTED_EPSILON_INTRODUCES_NEW_FAILURES", "PROJECTED_MATERIAL_INPUT_OR_TENSOR_CONSTITUTIVE_ADJUDICATION", sets
    return "R256_PROJECTED_EPSILON_NO_FREQUENCY_RESTORATION", "MPB_K_DEPENDENT_DISCRETE_OPERATOR_C3_SOURCE_AUDIT", sets


def _record(spec: Mapping[str, Any], frequencies: Any, epsilon: np.ndarray, gate: Mapping[str, Any], mechanism: str, source_commit: str) -> dict[str, Any]:
    value = {"schema": DATASET_SCHEMA, "record_id": None, "configuration_id": "R256_T1E9_M1_PROJECTED_EPSILON_C3", "member_index": int(spec["member_index"]), "c3_member_identity": spec["c3_member_identity"], "repeat_index": int(spec["repeat_index"]), "vertex_index": int(spec["vertex_index"]), "coordinate": list(spec["coordinate"]), "geometry_id": "G15", "resolution": 256, "tolerance": 1e-9, "mesh_size": 1, "deterministic": True, "polarization": "TE", "frequencies_bands_1_to_4": [float(v) for v in np.asarray(frequencies).reshape(-1)[:4]], "projected_epsilon_sha256": hashlib.sha256(epsilon.tobytes()).hexdigest(), "projected_epsilon_readback_sha256": gate["readback_sha256"], "input_mechanism_id": mechanism, "readback_gate": dict(gate), "source_commit": source_commit}
    value["record_id"] = "MEPHC-M55R1-PROJECTED-FREQ-" + hashlib.sha256(canonical({k: v for k, v in value.items() if k != "record_id"})).hexdigest()
    return value


def _result_base(bundle: Mapping[str, Any], source_commit: str, stock: Mapping[str, Any], base: Mapping[str, Any], projection: Mapping[str, Any]) -> dict[str, Any]:
    return {"schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "dataset_write": False, "dataset_schema": DATASET_SCHEMA, "source_commit_used": source_commit, "stock_frequency": stock, "scalar_tensor_base_status": {k: base[k] for k in ("scalar_c3_status", "tensor_c3_status", "scalar_c3_residual_max", "tensor_c3_residual_fro_max", "scalar_identity_guard", "tensor_identity_guard")}, "projection": projection, "fields_gaps_subspaces_wilson_berry_computed": False, "post_native_checkout_unchanged": True}


def main() -> int:
    bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8")); source_commit = str(os.environ.get("MEPHC_SOURCE_COMMIT") or bundle.get("source_commit") or "")
    records: list[dict[str, Any]] = []
    try:
        job = m54.m52r1.m41r3._load(ROOT / "tools/mephc-flow/scientific_job.py", "m55r1_job")
        state_root = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"]).parent.parent
        stock_records = _read_dataset(job, state_root, MESH1_DATASET_ID, MESH1_MANIFEST, MESH1_SCHEMA, 36)
        stock = frequency_ledger(_frequency_rows(stock_records))
        material_records = _read_dataset(job, state_root, M54R1_DATASET_ID, M54R1_MANIFEST, M54R1_SCHEMA, 3)
        mesh1 = next(record for record in material_records if int(record["mesh_size"]) == 1)
        epsilon = m54.decode_array(mesh1["epsilon_grid"]); tensor = m54.decode_array(mesh1["inverse_epsilon_tensor_grid"]); index_map = m54.build_index_map()
        base = m54.material_covariance(epsilon, tensor, index_map); projected, projection = projected_epsilon(epsilon, index_map)
        if not stock["failure_set"]:
            result = _result_base(bundle, source_commit, stock, base, projection); result.update({"classification": "R256_STOCK_MESH1_FREQUENCY_FAILURE_NOT_REPRODUCED", "causal_outcome": "R256_STOCK_MESH1_FREQUENCY_FAILURE_NOT_REPRODUCED", "next_science_decision": "R256_MESH1_FREQUENCY_SCALAR_REQUALIFICATION", "zero_patched_solver_reason": "F_stock_empty"})
        elif not scalar_patch_needed(base):
            result = _result_base(bundle, source_commit, stock, base, projection); result.update({"classification": "R256_MESH1_SCALAR_EPSILON_ALREADY_C3_TENSOR_ONLY_BASE_DEFECT", "causal_outcome": "R256_MESH1_SCALAR_EPSILON_ALREADY_C3_TENSOR_ONLY_BASE_DEFECT", "next_science_decision": "MESH1_INVERSE_EPSILON_TENSOR_C3_PATCH_AND_FREQUENCY_AB", "zero_patched_solver_reason": "scalar_identity_within_machine_guard"})
        else:
            import meep as mp
            from meep import mpb
            from mephc.band import Band
            band = Band(a=400.0, r1=80.14335684352235, r2=75.13439704080221, n_eff=2.7, h=100.0, resolution=256, lattice_type="triangular", polarization="TE", structure_type="slab")
            mechanism, gate_solver, probe = discover_public_input(mp, mpb, band, stock_records[0]["coordinate"], projected)
            if mechanism is None:
                result = _result_base(bundle, source_commit, stock, base, projection); result.update({"classification": "R256_PROJECTED_EPSILON_PUBLIC_INPUT_INTERFACE_UNAVAILABLE_AFTER_FULL_PROBE" if not any(x.get("availability") for x in probe["attempts"]) else "R256_PROJECTED_EPSILON_ALL_PUBLIC_READBACK_GATES_FAILED", "causal_outcome": "R256_PROJECTED_EPSILON_PUBLIC_INPUT_INTERFACE_UNAVAILABLE_AFTER_FULL_PROBE" if not any(x.get("availability") for x in probe["attempts"]) else "R256_PROJECTED_EPSILON_ALL_PUBLIC_READBACK_GATES_FAILED", "next_science_decision": "VENDOR_OR_PROJECT_CONTAINED_MPB_SCALAR_EPSILON_INPUT_REQUIRING_REMOTE_SOURCE_REVIEW" if not any(x.get("availability") for x in probe["attempts"]) else "MPB_PUBLIC_MATERIAL_INPUT_SEMANTICS_AND_TENSOR_OPERATOR_ADJUDICATION", "binding_probe": probe, "zero_patched_solver_reason": "no_candidate_passed_init_only_gate"})
            else:
                readback = np.asarray(gate_solver.get_epsilon(), dtype=float).reshape(SHAPE); gate = next(x["readback_gate"] for x in probe["attempts"] if x.get("mechanism_id") == mechanism); namespace = {"goal_id": "MEPHC-BERRY-C3-CONSISTENCY-V1", "work_order_id": bundle["work_order_id"], "source_commit": source_commit, "record_schema": DATASET_SCHEMA}; store = job.ImmutableDatasetStore(state_root, namespace)
                for member_index, member in enumerate(MEMBERS):
                    for repeat in range(3):
                        for vertex in range(4):
                            spec = _frequency_rows(stock_records)[(vertex, repeat, member)]
                            solver = _solver(mp, mpb, band, spec["coordinate"], _grid_candidate(getattr(mp if mechanism.startswith("MEEP") else mpb, "MaterialGrid"), mp, projected), "default_material" if mechanism != "MEEP_MATERIAL_GRID_FULL_CELL_BLOCK" else "full_cell_block")
                            solver.run_parity(mp.TE, False); frequencies = np.asarray(solver.all_freqs, dtype=float); require(frequencies.reshape(-1)[:4].size == 4, "M55R1_PATCHED_FREQUENCY_LAYOUT_INVALID")
                            item = _record({"member_index": member_index, "c3_member_identity": member, "repeat_index": repeat, "vertex_index": vertex, "coordinate": spec["coordinate"]}, frequencies, projected, gate, mechanism, source_commit); key = canonical({"work_order_id": bundle["work_order_id"], "member": member, "repeat": repeat, "vertex": vertex}); store.put(key, canonical(item), {"member": member, "repeat": repeat, "vertex": vertex, "record_id": item["record_id"]}); records.append(item)
                manifest = store.finalize(36, {"dataset_schema": DATASET_SCHEMA, "configuration_id": "R256_T1E9_M1_PROJECTED_EPSILON_C3", "source_parent_dataset_ids": [MESH1_DATASET_ID, M54R1_DATASET_ID], "input_mechanism_id": mechanism}); patch = frequency_ledger(_frequency_rows(records)); classification, decision, sets = classify(stock, patch); result = _result_base(bundle, source_commit, stock, base, projection); result.update({"solver_execution_count": 36, "dataset_record_count": 36, "dataset_write": True, "dataset_id": manifest.get("dataset_id"), "manifest_sha256": manifest.get("manifest_sha256"), "binding_probe": probe, "readback_gate": gate, "patched_frequency": patch, "failure_set_relations": {key: sorted(value) for key, value in sets.items()}, "classification": classification, "causal_outcome": classification, "next_science_decision": decision, "input_mechanism_id": mechanism, "readback_sha256": hashlib.sha256(readback.tobytes()).hexdigest()})
    except BaseException as exc:
        result = {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": len(records), "dataset_record_count": len(records), "dataset_write": bool(records), "failure_code": str(exc)[:1024], "failure_stage": "m55r1_public_epsilon_input_frequency_ab", "exception_type": type(exc).__name__, "source_commit_used": source_commit, "completed_record_ids": [record["record_id"] for record in records], "post_native_checkout_unchanged": True}
    Path(os.environ["MEPHC_RESULT_PATH"]).write_text(json.dumps(_safe(result), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
