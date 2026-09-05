"""M59: continuous G15 feature-set audit and canonical primitive A/B."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
M54_PATH = ROOT / "audit/berry_c3_consistency/m54_r256_material_grid_subpixel_c3_readback_ab.py"
SPEC = importlib.util.spec_from_file_location("m59_m54_reference", M54_PATH)
assert SPEC and SPEC.loader
m54 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m54)

RESULT_SCHEMA = "mephc-berry-c3-consistency-m59-g15-continuous-geometry-c3-frequency-ab-v1"
DATASET_SCHEMA = "mephc-berry-c3-consistency-m59-canonical-primitive-g15-frequency-dataset-v1"
MESH1_DATASET_ID = "9b560f99fa264905ee99cb68d4ccdf757446ffb7b3a0af0391d5760a9740861d"
MESH1_MANIFEST = "c009e68d08bd13084eb0320d95ecda5ceab57bdafa8fddef30ecc5b1177563ed"
MESH1_SCHEMA = "mephc-berry-c3-consistency-m50-r256-mesh1-c3-causal-control-dataset-v1"
M54R1_DATASET_ID = "f150ed53224492d2ba638b9ee074850e5757aa002a6be7e2039a09096b0eb7b7"
M54R1_MANIFEST = "3021651351dba3e61f9c27d32fce1c79e9ee67f13c11065a952f72ecef623604"
M54R1_SCHEMA = "mephc-berry-c3-consistency-m54r1-r256-material-grid-subpixel-readback-dataset-v1"
MEMBERS = ("IDENTITY", "C3", "C3_SQUARED")
SHAPE = (256, 256)
D = np.asarray([[-1, 1], [-1, 0]], dtype=int)


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise ValueError(f"{code}:{detail}" if detail else code)


def _safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else ("INF" if value > 0 else "-INF" if value < 0 else "NAN")
    if isinstance(value, np.generic):
        return _safe(value.item())
    if isinstance(value, np.ndarray):
        return _safe(value.tolist())
    if isinstance(value, Mapping):
        return {str(k): _safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(v) for v in value]
    raise ValueError(f"M59_UNSAFE_RESULT:{type(value).__name__}")


def _read_dataset(job: Any, state_root: Path, dataset_id: str, manifest: str, schema: str, count: int) -> list[dict[str, Any]]:
    verified = job.verify_dataset(state_root, dataset_id); require(verified.get("dataset_id") == dataset_id and verified.get("manifest_sha256") == manifest and verified.get("record_count") == count, "M59_DATASET_BINDING_INVALID", dataset_id); rows = []
    for key in verified["record_key_sha256"]:
        value = json.loads(job.resolve_dataset_record(state_root, dataset_id, manifest, key)["payload"].decode("utf-8")); require(isinstance(value, dict) and value.get("schema") == schema, "M59_DATASET_SCHEMA_INVALID", dataset_id); rows.append(value)
    return rows


def _frequency_rows(records: list[dict[str, Any]]) -> dict[tuple[int, int, str], dict[str, Any]]:
    rows = {(int(row["vertex_index"]), int(row["repeat_index"]), str(row["c3_member_identity"])): row for row in records}; require(len(rows) == 36 and set(rows) == {(v, r, m) for v in range(4) for r in range(3) for m in MEMBERS}, "M59_FREQUENCY_IDENTITY_SET_INVALID"); return rows


def frequency_ledger(rows: Mapping[tuple[int, int, str], Mapping[str, Any]]) -> dict[str, Any]:
    failures, ledger = [], {}
    for vertex in range(4):
        for source, target in zip(MEMBERS, MEMBERS[1:] + MEMBERS[:1]):
            for band in range(4):
                left = np.asarray([float(rows[(vertex, repeat, source)]["frequencies_bands_1_to_4"][band]) for repeat in range(3)]); right = np.asarray([float(rows[(vertex, repeat, target)]["frequencies_bands_1_to_4"][band]) for repeat in range(3)]); lm, rm = float(np.median(left)), float(np.median(right)); lu, ru = float(np.max(np.abs(left - lm))), float(np.max(np.abs(right - rm))); item = {"vertex": vertex, "band": band + 1, "source_member": source, "target_member": target, "source_median": lm, "target_median": rm, "source_repeat_uncertainty": lu, "target_repeat_uncertainty": ru, "residual": abs(lm - rm), "combined_repeat_uncertainty": lu + ru, "pass": abs(lm - rm) <= lu + ru}; ledger[f"v{vertex}:{source}_to_{target}:band{band + 1}"] = item
                if not item["pass"]: failures.append(item)
    return {"failure_set": failures, "failure_count": len(failures), "ledger": ledger}


def scalar_patch_needed(covariance: Mapping[str, Any]) -> bool:
    return covariance["scalar_c3_status"] == "FAIL" and float(covariance["scalar_projection_linf"]) > float(covariance["scalar_identity_guard"])


def _center(obj: Any) -> np.ndarray:
    value = getattr(obj, "center", None); require(value is not None, "M59_FEATURE_CENTER_MISSING", type(obj).__name__); return np.asarray([float(value.x), float(value.y)], dtype=float) % 1.0


def _material_signature(obj: Any) -> str:
    material = getattr(obj, "material", None); return type(material).__name__ + ":" + str(getattr(material, "epsilon", "unknown"))


def _feature_descriptor(obj: Any) -> dict[str, Any]:
    require(type(obj).__name__ == "Cylinder", "M59_UNEXPECTED_FEATURE_TYPE", type(obj).__name__); center = _center(obj); radius = float(getattr(obj, "radius")); height = float(getattr(obj, "height")); return {"center": center.tolist(), "radius": radius, "height": height, "material": _material_signature(obj)}


def _structural_guard(features: list[Mapping[str, Any]]) -> float:
    values = [float(v) for feature in features for v in (feature["center"] + [feature["radius"]])]; return 128.0 * np.finfo(float).eps * max(1.0, max(map(abs, values), default=1.0))


def deduplicate_periodic(features: list[Mapping[str, Any]], guard: float | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    guard = _structural_guard(list(features)) if guard is None else float(guard); unique, duplicates = [], []
    for index, feature in enumerate(features):
        found = None
        for unique_index, prior in enumerate(unique):
            if np.max(np.abs(np.asarray(feature["center"]) - np.asarray(prior["center"]))) <= guard and abs(float(feature["radius"]) - float(prior["radius"])) <= guard and feature["material"] == prior["material"]:
                found = unique_index; break
        if found is None: unique.append(dict(feature))
        else: duplicates.append({"raw_index": index, "unique_index": found, "reason": "machine_identical_periodic_duplicate"})
    return unique, duplicates


def feature_c3_ledger(features: list[Mapping[str, Any]], action: np.ndarray = D) -> dict[str, Any]:
    unique, duplicates = deduplicate_periodic(list(features)); guard = _structural_guard(unique); rows = []; unmatched = radius_mismatch = material_mismatch = 0
    for index, feature in enumerate(unique):
        target = np.asarray(action, dtype=int) @ np.asarray(feature["center"], dtype=float) % 1.0; matches = []
        for candidate_index, candidate in enumerate(unique):
            residual = np.asarray(target) - np.asarray(candidate["center"]); residual -= np.round(residual)
            if np.max(np.abs(residual)) <= guard: matches.append((candidate_index, candidate, float(np.max(np.abs(residual)))))
        same = [match for match in matches if abs(float(match[1]["radius"]) - float(feature["radius"])) <= guard and match[1]["material"] == feature["material"]]
        if not same:
            unmatched += 1
            if matches:
                radius_mismatch += 1 if all(abs(float(match[1]["radius"]) - float(feature["radius"])) > guard for match in matches) else 0; material_mismatch += 1 if all(match[1]["material"] != feature["material"] for match in matches) else 0
        rows.append({"source_index": index, "source_center": list(feature["center"]), "c3_target_center": target.tolist(), "matched_indices": [match[0] for match in same], "torus_residual": same[0][2] if same else None})
    return {"raw_feature_count": len(features), "unique_periodic_feature_count": len(unique), "periodic_duplicate_ledger": duplicates, "features": unique, "per_feature_ledger": rows, "unmatched_feature_count": unmatched, "radius_mismatch_count": radius_mismatch, "material_mismatch_count": material_mismatch, "structural_guard": guard, "c3_action": action.tolist(), "c3_status": "PASS" if unmatched == 0 else "FAIL"}


def canonical_centers() -> dict[str, Any]:
    from mephc.bravais import BravaisLattice2D
    lattice = BravaisLattice2D.triangular(); basis = lattice.direct_basis; reference_shift = np.asarray([0.5, 1.0 / (2.0 * np.sqrt(3.0))]); b = np.linalg.solve(basis, reference_shift); guard = 128.0 * np.finfo(float).eps * max(1.0, float(np.max(np.abs(b)))); require(np.max(np.abs(b - np.asarray([2.0 / 3.0, 1.0 / 3.0]))) <= guard, "M59_CANONICAL_B_CENTER_INVALID")
    return {"direct_basis": basis.tolist(), "reference_shift": reference_shift.tolist(), "a_fractional": [0.0, 0.0], "b_fractional": b.tolist(), "identity_guard": guard, "expected_b_fractional": [2.0 / 3.0, 1.0 / 3.0]}


def projected_epsilon(epsilon: Any, index_map: Any) -> tuple[np.ndarray, dict[str, Any]]:
    value = np.asarray(epsilon, dtype=float); require(value.shape == SHAPE and np.all(np.isfinite(value)) and np.all(value > 0.0), "M59_EPSILON_INPUT_INVALID"); projected = (value + m54.apply_grid(value, index_map) + m54.apply_grid(value, m54.apply_grid(index_map, index_map))) / 3.0; guard = m54.identity_guard(projected); residual = float(np.max(np.abs(projected - m54.apply_grid(projected, index_map)))); mean = abs(float(np.mean(projected) - np.mean(value))); require(residual <= guard and mean <= guard, "M59_PROJECTED_EPSILON_INVARIANT_INVALID"); return projected, {"identity_guard": guard, "projected_c3_residual_max": residual, "global_mean_residual": mean, "projection_linf": float(np.max(np.abs(projected - value)))}


def build_band():
    from mephc.band import Band
    return Band(a=400.0, r1=80.14335684352235, r2=75.13439704080221, n_eff=2.7, h=100.0, resolution=256, lattice_type="triangular", polarization="TE", structure_type="slab")


def canonical_geometry(mp: Any, band: Any) -> tuple[list[Any], dict[str, Any]]:
    centers = canonical_centers(); a = mp.Vector3(0.0, 0.0, 0.0); b = mp.Vector3(float(centers["b_fractional"][0]), float(centers["b_fractional"][1]), 0.0); features = [mp.Cylinder(center=a, radius=band.r1 / band.a, material=mp.air, height=band.h), mp.Cylinder(center=b, radius=band.r2 / band.a, material=mp.air, height=band.h)]; descriptors = [_feature_descriptor(feature) for feature in features]; proof = feature_c3_ledger(descriptors); require(proof["c3_status"] == "PASS", "M59_CANONICAL_CONTINUOUS_C3_FAILED"); return band.create_material_block() + features, {"derivation": centers, "feature_ledger": proof, "geometry_hash": hashlib.sha256(canonical(descriptors)).hexdigest()}


def synthetic_geometry(mp: Any, band: Any) -> tuple[list[Any], dict[str, Any]]:
    seed = np.asarray([0.25, 0.0]); centers = [seed % 1.0, D @ seed % 1.0, D @ (D @ seed) % 1.0]; features = [mp.Cylinder(center=mp.Vector3(float(center[0]), float(center[1]), 0.0), radius=band.r2 / band.a, material=mp.air, height=band.h) for center in centers]; descriptors = [_feature_descriptor(feature) for feature in features]; proof = feature_c3_ledger(descriptors); require(proof["c3_status"] == "PASS", "M59_SYNTHETIC_CONTINUOUS_C3_FAILED"); return band.create_material_block() + features, {"seed_fractional": seed.tolist(), "feature_ledger": proof, "geometry_hash": hashlib.sha256(canonical(descriptors)).hexdigest()}


def stock_geometry(mp: Any, band: Any) -> tuple[list[Any], dict[str, Any]]:
    pattern = band.create_unitcell(15, 0.0, 15, 60.0, show=False); features = band.convert_ndarray_to_meep_geo(pattern, rectify=True); descriptors = [_feature_descriptor(feature) for feature in features]; proof = feature_c3_ledger(descriptors); return band.create_material_block() + features, proof


def build_solver(mp: Any, mpb: Any, band: Any, coordinate: Any, geometry: list[Any]) -> Any:
    reciprocal = mp.cartesian_to_reciprocal(mp.Vector3(float(coordinate[0]), float(coordinate[1]), 0.0), band.geo_latt); return mpb.ModeSolver(geometry=geometry, geometry_lattice=band.geo_latt, k_points=[reciprocal], resolution=256, num_bands=4, default_material=mp.air, tolerance=1e-9, deterministic=True, mesh_size=1)


def material_gate(solver: Any, mp: Any) -> dict[str, Any]:
    init = getattr(solver, "init_params", None); parity = getattr(mp, "NO_PARITY", None); require(callable(init) and parity is not None, "M59_INIT_PARAMS_UNAVAILABLE"); init(parity, False); epsilon = np.asarray(solver.get_epsilon(), dtype=float).reshape(SHAPE); mapping = m54.build_index_map(); guard = m54.identity_guard(epsilon); scalar = float(np.max(np.abs(epsilon - m54.apply_grid(epsilon, mapping)))); gate = {"epsilon_shape": list(epsilon.shape), "epsilon_sha256": hashlib.sha256(epsilon.tobytes()).hexdigest(), "scalar_c3_residual_max": scalar, "scalar_identity_guard": guard, "scalar_c3_status": "PASS" if scalar <= guard else "FAIL"}; getter = getattr(solver, "get_epsilon_inverse_tensor_point", None); require(callable(getter), "M59_INVERSE_TENSOR_GETTER_UNAVAILABLE"); tensor = np.empty((*SHAPE, 3, 3), dtype=np.complex128)
    for i in range(SHAPE[0]):
        for j in range(SHAPE[1]): tensor[i, j] = m54._tensor(getter(mp.Vector3(float(i) / SHAPE[0], float(j) / SHAPE[1], 0.0)))
    covariance = m54.material_covariance(epsilon, tensor, mapping); gate.update({"tensor_sha256": hashlib.sha256(tensor.tobytes()).hexdigest(), "tensor_c3_residual_fro_max": covariance["tensor_c3_residual_fro_max"], "tensor_identity_guard": covariance["tensor_identity_guard"], "tensor_c3_status": covariance["tensor_c3_status"], "operator_gate": gate["scalar_c3_status"] == "PASS" and covariance["tensor_c3_status"] == "PASS"}); return gate


def classify(stock: Mapping[str, Any], patch: Mapping[str, Any]) -> tuple[str, str, dict[str, set[tuple[Any, ...]]]]:
    stock_set = {(x["vertex"], x["band"], x["source_member"], x["target_member"]) for x in stock["failure_set"]}; patch_set = {(x["vertex"], x["band"], x["source_member"], x["target_member"]) for x in patch["failure_set"]}; restored, persistent, new = stock_set - patch_set, stock_set & patch_set, patch_set - stock_set; sets = {"restored": restored, "persistent": persistent, "new_failures": new}
    if not stock_set: return "R256_STOCK_MESH1_FREQUENCY_FAILURE_NOT_REPRODUCED", "R256_MESH1_FREQUENCY_SCALAR_REQUALIFICATION", sets
    if not patch_set: return "R256_CANONICAL_PRIMITIVE_FULL_FREQUENCY_RESTORATION", "PATCH_PRODUCTION_G15_PRIMITIVE_GEOMETRY_AND_RUN_SIMPLE_C3_LADDER", sets
    if restored and persistent and not new: return "R256_CANONICAL_PRIMITIVE_PARTIAL_FREQUENCY_RESTORATION", "PATCH_PRODUCTION_G15_PRIMITIVE_GEOMETRY_PLUS_K_DEPENDENT_OPERATOR_AUDIT", sets
    if new: return "R256_CANONICAL_PRIMITIVE_INTRODUCES_NEW_FAILURES", "CANONICAL_GEOMETRY_EQUIVALENCE_AND_OPERATOR_ADJUDICATION", sets
    return "R256_CANONICAL_PRIMITIVE_NO_FREQUENCY_RESTORATION", "MPB_K_DEPENDENT_DISCRETE_OPERATOR_C3_SOURCE_AUDIT_WITH_GEOMETRY_FIX", sets


def _base(bundle: Mapping[str, Any], source_commit: str, stock: Mapping[str, Any], base: Mapping[str, Any]) -> dict[str, Any]:
    return {"schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "dataset_write": False, "dataset_schema": DATASET_SCHEMA, "source_commit_used": source_commit, "stock_frequency": stock, "scalar_tensor_base_status": {key: base[key] for key in ("scalar_c3_status", "tensor_c3_status", "scalar_c3_residual_max", "tensor_c3_residual_fro_max", "scalar_identity_guard", "tensor_identity_guard")}, "fields_gaps_subspaces_wilson_berry_computed": False, "post_native_checkout_unchanged": True}


def main() -> int:
    bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8")); source_commit = str(os.environ.get("MEPHC_SOURCE_COMMIT") or bundle.get("source_commit") or ""); records: list[dict[str, Any]] = []
    try:
        job = m54.m52r1.m41r3._load(ROOT / "tools/mephc-flow/scientific_job.py", "m59_job"); state_root = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"]).parent.parent; stock_records = _read_dataset(job, state_root, MESH1_DATASET_ID, MESH1_MANIFEST, MESH1_SCHEMA, 36); stock_rows = _frequency_rows(stock_records); stock = frequency_ledger(stock_rows); material_records = _read_dataset(job, state_root, M54R1_DATASET_ID, M54R1_MANIFEST, M54R1_SCHEMA, 3); mesh1 = next(row for row in material_records if int(row["mesh_size"]) == 1); epsilon = m54.decode_array(mesh1["epsilon_grid"]); tensor = m54.decode_array(mesh1["inverse_epsilon_tensor_grid"]); mapping = m54.build_index_map(); base = m54.material_covariance(epsilon, tensor, mapping); projected, projection = projected_epsilon(epsilon, mapping); result = _base(bundle, source_commit, stock, base); result["projection"] = projection
        if not stock["failure_set"]: result.update({"classification": "R256_STOCK_MESH1_FREQUENCY_FAILURE_NOT_REPRODUCED", "causal_outcome": "R256_STOCK_MESH1_FREQUENCY_FAILURE_NOT_REPRODUCED", "next_science_decision": "R256_MESH1_FREQUENCY_SCALAR_REQUALIFICATION", "zero_solver_reason": "F_stock_empty"})
        elif base["scalar_c3_status"] == "PASS" and base["tensor_c3_status"] == "PASS": result.update({"classification": "R256_M54R1_MATERIAL_C3_FAILURE_NOT_REPRODUCED", "causal_outcome": "R256_M54R1_MATERIAL_C3_FAILURE_NOT_REPRODUCED", "next_science_decision": "R256_MATERIAL_SCALAR_LADDER_REQUALIFICATION", "zero_solver_reason": "independent_stock_material_readback_is_C3"})
        else:
            import meep as mp
            from meep import mpb
            band = build_band(); stock_geo, stock_proof = stock_geometry(mp, band); canonical_geo, canonical_proof = canonical_geometry(mp, band); synthetic_geo, synthetic_proof = synthetic_geometry(mp, band); result.update({"stock_continuous_geometry": stock_proof, "canonical_primitive": canonical_proof, "synthetic_control": synthetic_proof})
            stock_gate = material_gate(build_solver(mp, mpb, band, stock_rows[(0, 0, "IDENTITY")]["coordinate"], stock_geo), mp); canonical_gate = material_gate(build_solver(mp, mpb, band, stock_rows[(0, 0, "IDENTITY")]["coordinate"], canonical_geo), mp); synthetic_gate = material_gate(build_solver(mp, mpb, band, stock_rows[(0, 0, "IDENTITY")]["coordinate"], synthetic_geo), mp); result.update({"stock_material_gate": stock_gate, "canonical_material_gate": canonical_gate, "synthetic_material_gate": synthetic_gate})
            if stock_proof["c3_status"] == "PASS" and not stock_gate["operator_gate"]: result.update({"classification": "R256_STOCK_CONTINUOUS_G15_C3_PASS_BUT_RUNTIME_MATERIAL_BREAKS", "causal_outcome": "R256_STOCK_CONTINUOUS_G15_C3_PASS_BUT_RUNTIME_MATERIAL_BREAKS", "next_science_decision": "VENDORED_MPB_EXACT_EPSILON_NATIVE_SOURCE_PATCH", "zero_solver_reason": "stock_continuous_C3_but_runtime_material_not_C3"})
            elif not canonical_proof["c3_status"] == "PASS" or not canonical_gate["operator_gate"]: result.update({"classification": "R256_CANONICAL_PRIMITIVE_CONTINUOUS_C3_PASS_RUNTIME_MATERIAL_BREAKS", "causal_outcome": "R256_CANONICAL_PRIMITIVE_CONTINUOUS_C3_PASS_RUNTIME_MATERIAL_BREAKS", "next_science_decision": "VENDORED_MPB_EXACT_EPSILON_NATIVE_SOURCE_PATCH", "zero_solver_reason": "canonical_material_gate_failed"})
            else:
                namespace = {"goal_id": "MEPHC-BERRY-C3-CONSISTENCY-V1", "work_order_id": bundle["work_order_id"], "source_commit": source_commit, "record_schema": DATASET_SCHEMA}; store = job.ImmutableDatasetStore(state_root, namespace)
                for member_index, member in enumerate(MEMBERS):
                    for repeat in range(3):
                        for vertex in range(4):
                            spec = stock_rows[(vertex, repeat, member)]; solver = build_solver(mp, mpb, band, spec["coordinate"], canonical_geo); solver.run_parity(mp.TE, False); frequencies = np.asarray(solver.all_freqs, dtype=float); require(frequencies.reshape(-1)[:4].size == 4, "M59_FREQUENCY_LAYOUT_INVALID"); item = {"schema": DATASET_SCHEMA, "record_id": None, "member_index": member_index, "c3_member_identity": member, "repeat_index": repeat, "vertex_index": vertex, "coordinate": list(spec["coordinate"]), "geometry_id": "G15", "resolution": 256, "tolerance": 1e-9, "mesh_size": 1, "deterministic": True, "polarization": "TE", "frequencies_bands_1_to_4": [float(v) for v in frequencies.reshape(-1)[:4]], "canonical_geometry_sha256": canonical_proof["geometry_hash"], "canonical_scalar_material_sha256": canonical_gate["epsilon_sha256"], "canonical_tensor_material_sha256": canonical_gate["tensor_sha256"], "source_commit": source_commit}; item["record_id"] = "MEPHC-M59-CANONICAL-FREQ-" + hashlib.sha256(canonical({k: v for k, v in item.items() if k != "record_id"})).hexdigest(); store.put(canonical({"work_order_id": bundle["work_order_id"], "member": member, "repeat": repeat, "vertex": vertex}), canonical(item), {"member": member, "repeat": repeat, "vertex": vertex, "record_id": item["record_id"]}); records.append(item)
                manifest = store.finalize(36, {"dataset_schema": DATASET_SCHEMA, "source_parent_dataset_ids": [MESH1_DATASET_ID, M54R1_DATASET_ID], "canonical_geometry_sha256": canonical_proof["geometry_hash"]}); patch = frequency_ledger(_frequency_rows(records)); classification, decision, sets = classify(stock, patch); result.update({"solver_execution_count": 36, "dataset_record_count": 36, "dataset_write": True, "dataset_id": manifest.get("dataset_id"), "manifest_sha256": manifest.get("manifest_sha256"), "patched_frequency": patch, "failure_set_relations": {key: sorted(value) for key, value in sets.items()}, "classification": classification, "causal_outcome": classification, "next_science_decision": decision})
    except BaseException as exc:
        result = {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": len(records), "dataset_record_count": len(records), "dataset_write": bool(records), "failure_code": str(exc)[:1024], "failure_stage": "m59_g15_continuous_geometry_c3_frequency_ab", "exception_type": type(exc).__name__, "source_commit_used": source_commit, "completed_record_ids": [row["record_id"] for row in records], "post_native_checkout_unchanged": True}
    Path(os.environ["MEPHC_RESULT_PATH"]).write_text(json.dumps(_safe(result), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8"); return 0


if __name__ == "__main__":
    raise SystemExit(main())
