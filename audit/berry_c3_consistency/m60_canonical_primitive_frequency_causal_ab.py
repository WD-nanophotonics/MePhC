"""M60: canonical primitive frequency A/B with material context kept non-causal."""
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
SPEC = importlib.util.spec_from_file_location("m60_m54_reference", M54_PATH)
assert SPEC and SPEC.loader
m54 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m54)

RESULT_SCHEMA = "mephc-berry-c3-consistency-m60-canonical-primitive-frequency-causal-ab-v1"
DATASET_SCHEMA = "mephc-berry-c3-consistency-m60-canonical-primitive-frequency-dataset-v1"
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
    raise ValueError(f"M60_UNSAFE_RESULT:{type(value).__name__}")


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, "M60_IMPORT_FAILED", str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _read_dataset(job: Any, state_root: Path, dataset_id: str, manifest: str, schema: str, count: int) -> list[dict[str, Any]]:
    verified = job.verify_dataset(state_root, dataset_id)
    require(verified.get("dataset_id") == dataset_id and verified.get("manifest_sha256") == manifest and verified.get("record_count") == count, "M60_DATASET_BINDING_INVALID", dataset_id)
    rows = []
    for key in verified["record_key_sha256"]:
        value = json.loads(job.resolve_dataset_record(state_root, dataset_id, manifest, key)["payload"].decode("utf-8"))
        require(isinstance(value, dict) and value.get("schema") == schema, "M60_DATASET_SCHEMA_INVALID", dataset_id)
        rows.append(value)
    return rows


def frequency_rows(records: list[dict[str, Any]]) -> dict[tuple[int, int, str], dict[str, Any]]:
    rows = {(int(row["vertex_index"]), int(row["repeat_index"]), str(row["c3_member_identity"])): row for row in records}
    require(len(rows) == 36 and set(rows) == {(v, r, member) for v in range(4) for r in range(3) for member in MEMBERS}, "M60_FREQUENCY_IDENTITY_SET_INVALID")
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


def _center(obj: Any) -> np.ndarray:
    center = getattr(obj, "center", None); require(center is not None, "M60_FEATURE_CENTER_MISSING")
    return np.asarray([float(center.x), float(center.y)], dtype=float) % 1.0


def _material_signature(obj: Any) -> str:
    material = getattr(obj, "material", None)
    return type(material).__name__ + ":" + str(getattr(material, "epsilon", "unknown"))


def feature_descriptor(obj: Any) -> dict[str, Any]:
    require(type(obj).__name__ == "Cylinder", "M60_UNEXPECTED_FEATURE_TYPE", type(obj).__name__)
    return {"center": _center(obj).tolist(), "radius": float(obj.radius), "height": float(obj.height), "material": _material_signature(obj)}


def structural_guard(features: list[Mapping[str, Any]]) -> float:
    values = [float(v) for feature in features for v in (list(feature["center"]) + [feature["radius"], feature["height"]])]
    return 128.0 * np.finfo(float).eps * max(1.0, max(map(abs, values), default=1.0))


def deduplicate_periodic(features: list[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    normalized = [dict(feature, center=(np.asarray(feature["center"], dtype=float) % 1.0).tolist()) for feature in features]
    guard = structural_guard(normalized); unique, duplicates = [], []
    for index, feature in enumerate(normalized):
        found = None
        for unique_index, prior in enumerate(unique):
            delta = np.asarray(feature["center"]) - np.asarray(prior["center"]); delta -= np.round(delta)
            same_species = abs(float(feature["radius"]) - float(prior["radius"])) <= guard and abs(float(feature["height"]) - float(prior["height"])) <= guard and feature["material"] == prior["material"]
            if np.max(np.abs(delta)) <= guard and same_species:
                found = unique_index; break
        if found is None: unique.append(feature)
        else: duplicates.append({"raw_index": index, "unique_index": found, "reason": "periodic_torus_species_identity"})
    return unique, duplicates


def feature_c3_ledger(features: list[Mapping[str, Any]]) -> dict[str, Any]:
    unique, duplicates = deduplicate_periodic(features); guard = structural_guard(unique); rows = []; unmatched = height_mismatch = radius_mismatch = material_mismatch = 0
    for index, feature in enumerate(unique):
        target = D @ np.asarray(feature["center"], dtype=float) % 1.0; geometric, same = [], []
        for candidate_index, candidate in enumerate(unique):
            delta = target - np.asarray(candidate["center"]); delta -= np.round(delta)
            if np.max(np.abs(delta)) <= guard:
                geometric.append(candidate); same.append((candidate_index, candidate, float(np.max(np.abs(delta)))))
        same = [item for item in same if abs(float(item[1]["radius"]) - float(feature["radius"])) <= guard and abs(float(item[1]["height"]) - float(feature["height"])) <= guard and item[1]["material"] == feature["material"]]
        if len(same) != 1:
            unmatched += 1
            height_mismatch += int(bool(geometric) and all(abs(float(x["height"]) - float(feature["height"])) > guard for x in geometric))
            radius_mismatch += int(bool(geometric) and all(abs(float(x["radius"]) - float(feature["radius"])) > guard for x in geometric))
            material_mismatch += int(bool(geometric) and all(x["material"] != feature["material"] for x in geometric))
        rows.append({"source_index": index, "source_center": list(feature["center"]), "c3_target_center": target.tolist(), "matched_indices": [item[0] for item in same], "torus_residual": same[0][2] if same else None})
    return {"raw_feature_count": len(features), "unique_periodic_feature_count": len(unique), "periodic_duplicate_ledger": duplicates, "features": unique, "per_feature_ledger": rows, "unmatched_feature_count": unmatched, "height_mismatch_count": height_mismatch, "radius_mismatch_count": radius_mismatch, "material_mismatch_count": material_mismatch, "structural_guard": guard, "c3_action": D.tolist(), "c3_status": "PASS" if unmatched == 0 else "FAIL"}


def canonical_centers() -> dict[str, Any]:
    from mephc.bravais import BravaisLattice2D
    basis = BravaisLattice2D.triangular().direct_basis; reference_shift = np.asarray([0.5, 1.0 / (2.0 * np.sqrt(3.0))]); b = np.linalg.solve(basis, reference_shift); guard = 128.0 * np.finfo(float).eps * max(1.0, float(np.max(np.abs(b))))
    require(np.max(np.abs(b - np.asarray([2.0 / 3.0, 1.0 / 3.0]))) <= guard, "M60_CANONICAL_B_CENTER_INVALID")
    return {"a_fractional": [0.0, 0.0], "b_fractional": b.tolist(), "direct_basis": basis.tolist(), "reference_shift": reference_shift.tolist(), "expected_b_fractional": [2.0 / 3.0, 1.0 / 3.0], "identity_guard": guard}


def build_band():
    from mephc.band import Band
    return Band(a=400.0, r1=80.14335684352235, r2=75.13439704080221, n_eff=2.7, h=100.0, resolution=256, lattice_type="triangular", polarization="TE", structure_type="slab")


def canonical_geometry(mp: Any, band: Any) -> tuple[list[Any], dict[str, Any]]:
    centers = canonical_centers(); a = mp.Vector3(0.0, 0.0, 0.0); b = mp.Vector3(*centers["b_fractional"], 0.0)
    features = [mp.Cylinder(center=a, radius=band.r1 / band.a, material=mp.air, height=100.0), mp.Cylinder(center=b, radius=band.r2 / band.a, material=mp.air, height=100.0)]
    descriptors = [feature_descriptor(feature) for feature in features]; proof = feature_c3_ledger(descriptors); require(proof["c3_status"] == "PASS", "M60_CANONICAL_CONTINUOUS_C3_FAILED")
    return band.create_material_block() + features, {"derivation": centers, "feature_ledger": proof, "geometry_hash": hashlib.sha256(canonical(descriptors)).hexdigest()}


def build_solver(mp: Any, mpb: Any, band: Any, coordinate: Any, geometry: list[Any]) -> Any:
    reciprocal = mp.cartesian_to_reciprocal(mp.Vector3(float(coordinate[0]), float(coordinate[1]), 0.0), band.geo_latt)
    return mpb.ModeSolver(geometry=geometry, geometry_lattice=band.geo_latt, k_points=[reciprocal], resolution=256, num_bands=4, default_material=mp.air, tolerance=1e-9, deterministic=True, mesh_size=1)


def material_context(solver: Any, mp: Any) -> dict[str, Any]:
    require(callable(getattr(solver, "init_params", None)) and getattr(mp, "NO_PARITY", None) is not None, "M60_INIT_PARAMS_UNAVAILABLE")
    solver.init_params(mp.NO_PARITY, False); epsilon = np.asarray(solver.get_epsilon(), dtype=float).reshape(SHAPE); mapping = m54.build_index_map(); guard = m54.identity_guard(epsilon); scalar_residual = float(np.max(np.abs(epsilon - m54.apply_grid(epsilon, mapping)))); tensor = np.empty((*SHAPE, 3, 3), dtype=np.complex128); getter = getattr(solver, "get_epsilon_inverse_tensor_point", None); require(callable(getter), "M60_INVERSE_TENSOR_GETTER_UNAVAILABLE")
    for i in range(SHAPE[0]):
        for j in range(SHAPE[1]): tensor[i, j] = m54._tensor(getter(mp.Vector3(float(i) / SHAPE[0], float(j) / SHAPE[1], 0.0)))
    covariance = m54.material_covariance(epsilon, tensor, mapping)
    return {"epsilon_shape": list(epsilon.shape), "epsilon_sha256": hashlib.sha256(epsilon.tobytes()).hexdigest(), "scalar_c3_residual_max": scalar_residual, "scalar_identity_guard": guard, "scalar_c3_status": "PASS" if scalar_residual <= guard else "FAIL", "tensor_sha256": hashlib.sha256(tensor.tobytes()).hexdigest(), "tensor_c3_residual_fro_max": covariance["tensor_c3_residual_fro_max"], "tensor_identity_guard": covariance["tensor_identity_guard"], "tensor_c3_status": covariance["tensor_c3_status"], "operator_gate": scalar_residual <= guard and covariance["tensor_c3_status"] == "PASS"}


def classify(stock: Mapping[str, Any], canonical_result: Mapping[str, Any]) -> tuple[str, str, dict[str, set[tuple[Any, ...]]]]:
    stock_set = {(x["vertex"], x["band"], x["source_member"], x["target_member"]) for x in stock["failure_set"]}; canonical_set = {(x["vertex"], x["band"], x["source_member"], x["target_member"]) for x in canonical_result["failure_set"]}; restored, persistent, new = stock_set - canonical_set, stock_set & canonical_set, canonical_set - stock_set; relations = {"restored": restored, "persistent": persistent, "new_failures": new}
    if not canonical_set: return "R256_CANONICAL_PRIMITIVE_FULL_FREQUENCY_RESTORATION", "PATCH_PRODUCTION_G15_PRIMITIVE_GEOMETRY_AND_RUN_SIMPLE_C3_LADDER", relations
    if new: return "R256_CANONICAL_PRIMITIVE_INTRODUCES_NEW_FAILURES", "CANONICAL_GEOMETRY_PHYSICAL_EQUIVALENCE_AND_OPERATOR_ADJUDICATION", relations
    if restored and persistent: return "R256_CANONICAL_PRIMITIVE_PARTIAL_FREQUENCY_RESTORATION", "PATCH_PRODUCTION_G15_PRIMITIVE_GEOMETRY_AND_THEN_VENDORED_MPB_EXACT_MATERIAL_AB", relations
    return "R256_CANONICAL_PRIMITIVE_NO_FREQUENCY_RESTORATION", "VENDORED_MPB_EXACT_EPSILON_NATIVE_SOURCE_PATCH_AND_FREQUENCY_AB", relations


def route_frequency_after_geometry(stock: Mapping[str, Any], canonical_proof: Mapping[str, Any], material: Mapping[str, Any]) -> dict[str, Any]:
    """The material context is explanatory only; continuous C3 gates frequency."""
    require(canonical_proof.get("c3_status") == "PASS", "M60_CANONICAL_CONTINUOUS_C3_FAILED")
    require("failure_set" in stock and len(stock["failure_set"]) > 0, "M60_F_STOCK_EMPTY")
    return {"authorize_frequency": True, "material_operator_gate_context": bool(material.get("operator_gate", False)), "reason": "nonempty_F_stock_and_continuous_c3"}


def main() -> int:
    bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8")); source_commit = str(os.environ.get("MEPHC_SOURCE_COMMIT") or bundle.get("source_commit") or ""); records: list[dict[str, Any]] = []
    try:
        job = _load(ROOT / "tools/mephc-flow/scientific_job.py", "m60_science_job"); state_root = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"]).parent.parent; stock = frequency_ledger(frequency_rows(_read_dataset(job, state_root, MESH1_DATASET_ID, MESH1_MANIFEST, MESH1_SCHEMA, 36))); material_rows = _read_dataset(job, state_root, M54R1_DATASET_ID, M54R1_MANIFEST, M54R1_SCHEMA, 3); require(any(int(row["mesh_size"]) == 1 for row in material_rows), "M60_M54R1_MESH1_CONTEXT_MISSING")
        result = {"schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "dataset_write": False, "dataset_schema": DATASET_SCHEMA, "source_commit_used": source_commit, "stock_frequency": stock, "fields_gaps_subspaces_wilson_berry_computed": False, "post_native_checkout_unchanged": True}
        if not stock["failure_set"]:
            result.update({"classification": "R256_STOCK_MESH1_FREQUENCY_FAILURE_NOT_REPRODUCED", "causal_outcome": "R256_STOCK_MESH1_FREQUENCY_FAILURE_NOT_REPRODUCED", "next_science_decision": "R256_MESH1_FREQUENCY_SCALAR_REQUALIFICATION", "zero_solver_reason": "F_stock_empty"})
        else:
            import meep as mp
            from meep import mpb
            band = build_band(); geometry, proof_wrapper = canonical_geometry(mp, band); proof = proof_wrapper["feature_ledger"]; solver = build_solver(mp, mpb, band, [0.0, 0.0], geometry); context = material_context(solver, mp); result["canonical_continuous_proof"] = proof_wrapper; result["canonical_material_context"] = context
            require(proof["c3_status"] == "PASS", "M60_CANONICAL_CONTINUOUS_C3_FAILED")
            namespace = {"goal_id": "MEPHC-BERRY-C3-CONSISTENCY-V1", "work_order_id": bundle["work_order_id"], "source_commit": source_commit, "record_schema": DATASET_SCHEMA}; store = job.ImmutableDatasetStore(state_root, namespace); stock_rows = frequency_rows(_read_dataset(job, state_root, MESH1_DATASET_ID, MESH1_MANIFEST, MESH1_SCHEMA, 36))
            for member_index, member in enumerate(MEMBERS):
                for repeat in range(3):
                    for vertex in range(4):
                        spec = stock_rows[(vertex, repeat, member)]; state_solver = build_solver(mp, mpb, band, spec["coordinate"], geometry); state_solver.run_parity(mp.TE, False); frequencies = np.asarray(state_solver.all_freqs, dtype=float).reshape(-1)[:4]; require(frequencies.size == 4, "M60_FREQUENCY_LAYOUT_INVALID"); item = {"schema": DATASET_SCHEMA, "record_id": None, "member_index": member_index, "c3_member_identity": member, "repeat_index": repeat, "vertex_index": vertex, "coordinate": list(spec["coordinate"]), "geometry_id": "G15", "resolution": 256, "tolerance": 1e-9, "mesh_size": 1, "deterministic": True, "polarization": "TE", "frequencies_bands_1_to_4": [float(v) for v in frequencies], "canonical_geometry_sha256": proof_wrapper["geometry_hash"], "continuous_c3_proof_sha256": hashlib.sha256(canonical(proof_wrapper)).hexdigest(), "canonical_material_context_sha256": hashlib.sha256(canonical(context)).hexdigest(), "source_commit": source_commit}; item["record_id"] = "MEPHC-M60-CANONICAL-FREQ-" + hashlib.sha256(canonical({k: v for k, v in item.items() if k != "record_id"})).hexdigest(); store.put(canonical({"work_order_id": bundle["work_order_id"], "member": member, "repeat": repeat, "vertex": vertex}), canonical(item), {"member": member, "repeat": repeat, "vertex": vertex, "record_id": item["record_id"]}); records.append(item)
            manifest = store.finalize(36, {"dataset_schema": DATASET_SCHEMA, "source_parent_dataset_ids": [MESH1_DATASET_ID, M54R1_DATASET_ID], "canonical_geometry_sha256": proof_wrapper["geometry_hash"]}); canonical_result = frequency_ledger(frequency_rows(records)); classification, decision, relations = classify(stock, canonical_result); result.update({"solver_execution_count": 36, "dataset_record_count": 36, "dataset_write": True, "dataset_id": manifest.get("dataset_id"), "manifest_sha256": manifest.get("manifest_sha256"), "canonical_frequency": canonical_result, "failure_set_relations": {key: sorted(value) for key, value in relations.items()}, "classification": classification, "causal_outcome": classification, "next_science_decision": decision})
    except BaseException as exc:
        result = {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": len(records), "dataset_record_count": len(records), "dataset_write": bool(records), "failure_code": str(exc)[:1024], "failure_stage": "m60_canonical_primitive_frequency_causal_ab", "exception_type": type(exc).__name__, "source_commit_used": source_commit, "completed_record_ids": [row["record_id"] for row in records], "post_native_checkout_unchanged": True}
    Path(os.environ["MEPHC_RESULT_PATH"]).write_text(json.dumps(_safe(result), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8"); return 0


if __name__ == "__main__":
    raise SystemExit(main())
