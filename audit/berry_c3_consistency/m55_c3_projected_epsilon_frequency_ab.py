"""M55: projected mesh-1 epsilon versus the frozen frequency failure set.

This is the first bounded frequency A/B after M54R1 localized the defect to
the unsmoothed material grid.  The projected scalar epsilon is constructed by
the exact direct-grid C3 permutation and is admitted to the 36-state arm only
after an init-only public readback gate.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
from typing import Any, Mapping

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
M54R1_PATH = ROOT / "audit/berry_c3_consistency/m54r1_recover_material_grid_subpixel_c3_ab.py"
SPEC = importlib.util.spec_from_file_location("m55_m54r1_reference", M54R1_PATH)
assert SPEC and SPEC.loader
m54r1 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m54r1)
m54 = m54r1.m54

RESULT_SCHEMA = "mephc-berry-c3-consistency-m55-c3-projected-epsilon-frequency-ab-v1"
DATASET_SCHEMA = "mephc-berry-c3-consistency-m55-c3-projected-epsilon-frequency-dataset-v1"
MESH1_DATASET_ID = "9b560f99fa264905ee99cb68d4ccdf757446ffb7b3a0af0391d5760a9740861d"
MESH1_MANIFEST = "c009e68d08bd13084eb0320d95ecda5ceab57bdafa8fddef30ecc5b1177563ed"
MESH1_SCHEMA = "mephc-berry-c3-consistency-m50-r256-mesh1-c3-causal-control-dataset-v1"
M54R1_DATASET_ID = "f150ed53224492d2ba638b9ee074850e5757aa002a6be7e2039a09096b0eb7b7"
M54R1_MANIFEST = "3021651351dba3e61f9c27d32fce1c79e9ee67f13c11065a952f72ecef623604"
M54R1_SCHEMA = "mephc-berry-c3-consistency-m54r1-r256-material-grid-subpixel-readback-dataset-v1"
MEMBERS = ("IDENTITY", "C3", "C3_SQUARED")
MESHES = (1, 3, 5)


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
    raise ValueError(f"M55_UNSAFE_RESULT:{type(value).__name__}")


def _read_dataset(job: Any, state_root: Path, dataset_id: str, manifest: str, schema: str, count: int) -> list[dict[str, Any]]:
    verified = job.verify_dataset(state_root, dataset_id)
    require(verified.get("dataset_id") == dataset_id and verified.get("manifest_sha256") == manifest and verified.get("record_count") == count, "M55_DATASET_BINDING_INVALID", dataset_id)
    records = []
    for key in verified["record_key_sha256"]:
        payload = job.resolve_dataset_record(state_root, dataset_id, manifest, key)["payload"]
        value = json.loads(payload.decode("utf-8"))
        require(isinstance(value, dict) and value.get("schema") == schema, "M55_DATASET_SCHEMA_INVALID", dataset_id)
        records.append(value)
    return records


def _frequency_rows(records: list[dict[str, Any]]) -> dict[tuple[int, int, str], dict[str, Any]]:
    result = {}
    for record in records:
        result[(int(record["vertex_index"]), int(record["repeat_index"]), str(record["c3_member_identity"]))] = record
    require(len(result) == 36, "M55_FREQUENCY_COVERAGE_INVALID")
    return result


def frequency_ledger(rows: Mapping[tuple[int, int, str], Mapping[str, Any]]) -> dict[str, Any]:
    failures = []
    ledger = {}
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


def projected_epsilon(epsilon: Any, index_map: Any) -> tuple[np.ndarray, dict[str, Any]]:
    value = np.asarray(epsilon, dtype=float)
    require(value.shape == m54.SHAPE and np.all(np.isfinite(value)) and np.all(value > 0.0), "M55_EPSILON_INPUT_INVALID")
    second = m54.apply_grid(index_map, index_map)
    projected = (value + m54.apply_grid(value, index_map) + m54.apply_grid(value, second)) / 3.0
    guard = m54.identity_guard(projected)
    covariance = float(np.max(np.abs(projected - m54.apply_grid(projected, index_map))))
    mean_residual = abs(float(np.mean(projected) - np.mean(value)))
    require(covariance <= guard, "M55_PROJECTED_EPSILON_C3_INVALID", str(covariance))
    require(mean_residual <= guard, "M55_PROJECTED_EPSILON_MEAN_CHANGED", str(mean_residual))
    return projected, {"identity_guard": guard, "projected_c3_residual_max": covariance, "global_mean_residual": mean_residual, "projection_linf": float(np.max(np.abs(projected - value))), "projection_l1": float(np.sum(np.abs(projected - value))), "corrected_cell_count": int(np.count_nonzero(np.abs(projected - value) > guard))}


def _material_grid(mpb: Any, mp: Any, epsilon: np.ndarray) -> Any:
    material_grid_type = getattr(mpb, "MaterialGrid", None)
    require(callable(material_grid_type), "M55_PUBLIC_SCALAR_MATERIAL_GRID_UNAVAILABLE")
    low, high = float(np.min(epsilon)), float(np.max(epsilon))
    if abs(high - low) <= np.finfo(float).eps:
        high = low + 1.0
    weights = (epsilon - low) / (high - low)
    return material_grid_type(mp.Vector3(256, 256, 0), mp.Medium(epsilon=low), mp.Medium(epsilon=high), weights=weights, do_averaging=False)


def build_projected_solver(mp: Any, mpb: Any, band: Any, coordinate: Any, epsilon: np.ndarray) -> tuple[Any, Any]:
    """Build one public MaterialGrid solver; the caller performs the gate."""
    material = _material_grid(mpb, mp, epsilon)
    reciprocal = mp.cartesian_to_reciprocal(mp.Vector3(float(coordinate[0]), float(coordinate[1]), 0.0), band.geo_latt)
    solver = mpb.ModeSolver(geometry=[material], geometry_lattice=band.geo_latt, k_points=[reciprocal], resolution=256, num_bands=4, default_material=mp.air, tolerance=1e-9, deterministic=True, mesh_size=1)
    return solver, reciprocal


def readback_gate(solver: Any, projected: np.ndarray) -> dict[str, Any]:
    init = getattr(solver, "init_params", None)
    require(callable(init), "M55_INIT_PARAMS_UNAVAILABLE")
    # NO_PARITY is supplied by the caller as a bound attribute on the solver
    # factory's MP module; this helper is also directly mockable in tests.
    init(getattr(solver, "_m55_no_parity"), False)
    readback = np.asarray(solver.get_epsilon(), dtype=float).reshape(m54.SHAPE)
    guard = m54.identity_guard(projected)
    residual = float(np.max(np.abs(readback - projected)))
    covariance = float(np.max(np.abs(readback - m54.apply_grid(readback, m54.build_index_map()))))
    return {"readback_shape": list(readback.shape), "readback_identity_guard": guard, "readback_residual_max": residual, "readback_c3_residual_max": covariance, "readback_gate": bool(residual <= guard and covariance <= guard)}


def _make_gate_solver(mp: Any, mpb: Any, band: Any, coordinate: Any, epsilon: np.ndarray) -> tuple[Any, Any]:
    solver, reciprocal = build_projected_solver(mp, mpb, band, coordinate, epsilon)
    setattr(solver, "_m55_no_parity", getattr(mp, "NO_PARITY"))
    return solver, reciprocal


def _make_frequency_solver(mp: Any, mpb: Any, band: Any, coordinate: Any, epsilon: np.ndarray) -> Any:
    solver, _ = build_projected_solver(mp, mpb, band, coordinate, epsilon)
    return solver


def _record(spec: Mapping[str, Any], frequencies: Any, epsilon: np.ndarray, readback: Mapping[str, Any], source_commit: str) -> dict[str, Any]:
    value = {"schema": DATASET_SCHEMA, "record_id": None, "configuration_id": "R256_T1E9_M1_PROJECTED_EPSILON_C3", "member_index": int(spec["member_index"]), "c3_member_identity": spec["c3_member_identity"], "repeat_index": int(spec["repeat_index"]), "vertex_index": int(spec["vertex_index"]), "coordinate": list(spec["coordinate"]), "geometry_id": "G15", "resolution": 256, "tolerance": 1e-9, "mesh_size": 1, "deterministic": True, "polarization": "TE", "frequencies_bands_1_to_4": [float(v) for v in np.asarray(frequencies).reshape(-1)[:4]], "projected_epsilon_sha256": hashlib.sha256(epsilon.tobytes()).hexdigest(), "projected_epsilon_readback_sha256": readback.get("readback_sha256"), "readback_gate": dict(readback), "source_commit": source_commit}
    value["record_id"] = "MEPHC-M55-PROJECTED-FREQ-" + hashlib.sha256(canonical({k: v for k, v in value.items() if k != "record_id"})).hexdigest()
    return value


def patched_frequency_ledger(records: list[Mapping[str, Any]]) -> dict[str, Any]:
    return frequency_ledger(_frequency_rows(list(records)))


def classify(stock: Mapping[str, Any], patch: Mapping[str, Any]) -> tuple[str, str, dict[str, set[tuple[Any, ...]]]]:
    stock_set = {(item["vertex"], item["band"], item["source_member"], item["target_member"]) for item in stock["failure_set"]}
    patch_set = {(item["vertex"], item["band"], item["source_member"], item["target_member"]) for item in patch["failure_set"]}
    restored, persistent, new = stock_set - patch_set, stock_set & patch_set, patch_set - stock_set
    sets = {"restored": restored, "persistent": persistent, "new_failures": new}
    if not stock_set:
        return "R256_STOCK_MESH1_FREQUENCY_FAILURE_NOT_REPRODUCED", "R256_M5_FREQUENCY_SCALAR_REQUALIFICATION", sets
    if not patch_set and not new:
        return "R256_C3_PROJECTED_SCALAR_EPSILON_FULL_FREQUENCY_RESTORATION", "QUALIFY_PATCHED_SIMPLE_C3_LADDER_GAP_SCALAR_RANK2_BEFORE_BERRY", sets
    if restored and persistent and not new:
        return "R256_C3_PROJECTED_SCALAR_EPSILON_PARTIAL_FREQUENCY_RESTORATION", "IMPLEMENT_PROJECT_CONTAINED_C3_PROJECTED_SCALAR_EPSILON_FREQUENCY_REFINEMENT_AB", sets
    if new:
        return "R256_C3_PROJECTED_SCALAR_EPSILON_INTRODUCES_NEW_FAILURES", "REVIEW_PROJECTED_EPSILON_INPUT_AND_K_DEPENDENT_OPERATOR", sets
    return "R256_C3_PROJECTED_SCALAR_EPSILON_NO_FREQUENCY_RESTORATION", "MPB_K_DEPENDENT_DISCRETE_OPERATOR_C3_SOURCE_AUDIT", sets


def main() -> int:
    bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8")); source_commit = str(os.environ.get("MEPHC_SOURCE_COMMIT") or bundle.get("source_commit") or "")
    records: list[dict[str, Any]] = []
    try:
        job = m54.m52r1.m41r3._load(ROOT / "tools/mephc-flow/scientific_job.py", "m55_job"); counters = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"]); state_root = counters.parent.parent
        stock_records = _read_dataset(job, state_root, MESH1_DATASET_ID, MESH1_MANIFEST, MESH1_SCHEMA, 36); stock_rows = _frequency_rows(stock_records); stock = frequency_ledger(stock_rows)
        material_records = _read_dataset(job, state_root, M54R1_DATASET_ID, M54R1_MANIFEST, M54R1_SCHEMA, 3)
        mesh1 = next(item for item in material_records if int(item["mesh_size"]) == 1); epsilon = m54.decode_array(mesh1["epsilon_grid"]); index_map = m54.build_index_map(); projected, projection = projected_epsilon(epsilon, index_map)
        if not stock["failure_set"]:
            raise ValueError("M55_STOCK_MESH1_FREQUENCY_FAILURE_NOT_REPRODUCED")
        import meep as mp
        from meep import mpb
        from mephc.band import Band
        band = Band(a=400.0, r1=80.14335684352235, r2=75.13439704080221, n_eff=2.7, h=100.0, resolution=256, lattice_type="triangular", polarization="TE", structure_type="slab")
        gate_solver, _ = _make_gate_solver(mp, mpb, band, stock_rows[(0, 0, "IDENTITY")]["coordinate"], projected); gate = readback_gate(gate_solver, projected)
        readback = np.asarray(gate_solver.get_epsilon(), dtype=float).reshape(m54.SHAPE); gate["readback_sha256"] = hashlib.sha256(readback.tobytes()).hexdigest()
        require(gate["readback_gate"], "M55_PROJECTED_EPSILON_READBACK_MISMATCH")
        namespace = {"goal_id": "MEPHC-BERRY-C3-CONSISTENCY-V1", "work_order_id": bundle["work_order_id"], "source_commit": source_commit, "record_schema": DATASET_SCHEMA, "projected_epsilon_sha256": hashlib.sha256(projected.tobytes()).hexdigest()}; store = job.ImmutableDatasetStore(state_root, namespace)
        for member_index, member in enumerate(MEMBERS):
            for repeat in range(3):
                for vertex in range(4):
                    spec = stock_rows[(vertex, repeat, member)]; solver = _make_frequency_solver(mp, mpb, band, spec["coordinate"], projected); solver.run_parity(mp.TE, False); frequencies = np.asarray(solver.all_freqs, dtype=float); require(frequencies.reshape(-1)[:4].size == 4, "M55_PATCHED_FREQUENCY_LAYOUT_INVALID")
                    item = _record({"member_index": member_index, "c3_member_identity": member, "repeat_index": repeat, "vertex_index": vertex, "coordinate": spec["coordinate"]}, frequencies, projected, gate, source_commit); key = canonical({"work_order_id": bundle["work_order_id"], "member": member, "repeat": repeat, "vertex": vertex}); store.put(key, canonical(item), {"member": member, "repeat": repeat, "vertex": vertex, "record_id": item["record_id"]}); records.append(item)
        manifest = store.finalize(36, {"dataset_schema": DATASET_SCHEMA, "configuration_id": "R256_T1E9_M1_PROJECTED_EPSILON_C3", "source_parent_dataset_ids": [MESH1_DATASET_ID, M54R1_DATASET_ID]}); patch = patched_frequency_ledger(records); classification, decision, sets = classify(stock, patch)
        result = {"schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": 36, "dataset_record_count": 36, "dataset_write": True, "dataset_id": manifest.get("dataset_id"), "manifest_sha256": manifest.get("manifest_sha256"), "dataset_schema": DATASET_SCHEMA, "source_commit_used": source_commit, "stock_frequency": stock, "patched_frequency": patch, "failure_set_relations": {key: sorted(value) for key, value in sets.items()}, "projection": projection, "readback_gate": gate, "classification": classification, "causal_outcome": classification, "next_science_decision": decision, "common_mode_absolute_shifts_not_used": True, "fields_gaps_subspaces_wilson_berry_computed": False, "post_native_checkout_unchanged": True}
    except BaseException as exc:
        result = {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": len(records), "dataset_record_count": len(records), "dataset_write": bool(records), "failure_code": str(exc)[:1024], "failure_stage": "m55_projected_epsilon_frequency_ab", "exception_type": type(exc).__name__, "source_commit_used": source_commit, "completed_record_ids": [item["record_id"] for item in records], "post_native_checkout_unchanged": True}
    Path(os.environ["MEPHC_RESULT_PATH"]).write_text(json.dumps(_safe(result), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
