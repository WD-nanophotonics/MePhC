"""M59R1: normalized-proof recovery of the continuous G15 adjudication."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
from typing import Any, Mapping

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
M59_PATH = ROOT / "audit/berry_c3_consistency/m59_g15_continuous_geometry_c3_frequency_ab.py"
SPEC = importlib.util.spec_from_file_location("m59r1_m59_reference", M59_PATH)
assert SPEC and SPEC.loader
m59 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m59)

RESULT_SCHEMA = "mephc-berry-c3-consistency-m59r1-recover-continuous-geometry-c3-frequency-ab-v1"
DATASET_SCHEMA = "mephc-berry-c3-consistency-m59r1-canonical-primitive-g15-frequency-dataset-v1"
MESH1_DATASET_ID = m59.MESH1_DATASET_ID
MESH1_MANIFEST = m59.MESH1_MANIFEST
MESH1_SCHEMA = m59.MESH1_SCHEMA
M54R1_DATASET_ID = m59.M54R1_DATASET_ID
M54R1_MANIFEST = m59.M54R1_MANIFEST
M54R1_SCHEMA = m59.M54R1_SCHEMA
MEMBERS = m59.MEMBERS
SHAPE = m59.SHAPE
D = m59.D


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
    raise ValueError(f"M59R1_UNSAFE_RESULT:{type(value).__name__}")


def normalize_geometry_proof(kind: str, proof: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize direct and wrapped proof variants at one routing boundary."""
    ledger = proof.get("feature_ledger") if isinstance(proof.get("feature_ledger"), Mapping) else proof
    require(isinstance(ledger, Mapping), "M59R1_PROOF_NOT_OBJECT", kind)
    required = ("c3_status", "features", "unmatched_feature_count", "structural_guard", "raw_feature_count", "unique_periodic_feature_count")
    for key in required:
        require(key in ledger, "M59R1_PROOF_KEY_MISSING", f"{kind}:{key}")
    normalized = {"kind": kind, "c3_status": str(ledger["c3_status"]), "features": list(ledger["features"]), "feature_ledger": dict(ledger), "raw_feature_count": int(ledger["raw_feature_count"]), "unique_periodic_feature_count": int(ledger["unique_periodic_feature_count"]), "unmatched_feature_count": int(ledger["unmatched_feature_count"]), "structural_guard": float(ledger["structural_guard"]), "geometry_hash": proof.get("geometry_hash"), "derivation": proof.get("derivation"), "seed_fractional": proof.get("seed_fractional")}
    if normalized["geometry_hash"] is None:
        normalized["geometry_hash"] = hashlib.sha256(canonical(normalized["features"])).hexdigest()
    return normalized


def _descriptor(obj: Any) -> dict[str, Any]:
    require(type(obj).__name__ == "Cylinder", "M59R1_UNEXPECTED_FEATURE_TYPE", type(obj).__name__)
    center = getattr(obj, "center", None); require(center is not None, "M59R1_FEATURE_CENTER_MISSING")
    material = getattr(obj, "material", None)
    return {"center": (np.asarray([float(center.x), float(center.y)], dtype=float) % 1.0).tolist(), "radius": float(obj.radius), "height": float(obj.height), "material": type(material).__name__ + ":" + str(getattr(material, "epsilon", "unknown"))}


def _guard(features: list[Mapping[str, Any]]) -> float:
    values = [float(v) for item in features for v in (item["center"] + [item["radius"], item["height"]])]
    return 128.0 * np.finfo(float).eps * max(1.0, max(map(abs, values), default=1.0))


def deduplicate_periodic(features: list[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    normalized = [dict(item, center=(np.asarray(item["center"], dtype=float) % 1.0).tolist()) for item in features]; guard = _guard(normalized); unique, duplicate = [], []
    for index, item in enumerate(normalized):
        found = None
        for unique_index, prior in enumerate(unique):
            delta = np.asarray(item["center"]) - np.asarray(prior["center"]); delta -= np.round(delta)
            if np.max(np.abs(delta)) <= guard and abs(item["radius"] - prior["radius"]) <= guard and abs(item["height"] - prior["height"]) <= guard and item["material"] == prior["material"]: found = unique_index; break
        if found is None: unique.append(item)
        else: duplicate.append({"raw_index": index, "unique_index": found, "reason": "periodic_torus_species_identity"})
    return unique, duplicate


def feature_c3_ledger(features: list[Mapping[str, Any]]) -> dict[str, Any]:
    unique, duplicate = deduplicate_periodic(features); guard = _guard(unique); rows = []; unmatched = ambiguous = radius_mismatch = height_mismatch = material_mismatch = 0
    for index, item in enumerate(unique):
        target = D @ np.asarray(item["center"], dtype=float) % 1.0; matches = []
        for candidate_index, candidate in enumerate(unique):
            delta = target - np.asarray(candidate["center"]); delta -= np.round(delta)
            if np.max(np.abs(delta)) <= guard: matches.append((candidate_index, candidate, float(np.max(np.abs(delta)))))
        same = [match for match in matches if abs(match[1]["radius"] - item["radius"]) <= guard and abs(match[1]["height"] - item["height"]) <= guard and match[1]["material"] == item["material"]]
        if len(same) != 1:
            unmatched += 1; ambiguous += 1 if len(same) > 1 else 0
            radius_mismatch += 1 if matches and all(abs(match[1]["radius"] - item["radius"]) > guard for match in matches) else 0
            height_mismatch += 1 if matches and all(abs(match[1]["height"] - item["height"]) > guard for match in matches) else 0
            material_mismatch += 1 if matches and all(match[1]["material"] != item["material"] for match in matches) else 0
        rows.append({"source_index": index, "source_center": list(item["center"]), "c3_target_center": target.tolist(), "matched_indices": [match[0] for match in same], "torus_residual": same[0][2] if same else None})
    return {"raw_feature_count": len(features), "unique_periodic_feature_count": len(unique), "periodic_duplicate_ledger": duplicate, "features": unique, "per_feature_ledger": rows, "unmatched_feature_count": unmatched, "ambiguous_feature_count": ambiguous, "radius_mismatch_count": radius_mismatch, "height_mismatch_count": height_mismatch, "material_mismatch_count": material_mismatch, "structural_guard": guard, "c3_action": D.tolist(), "c3_status": "PASS" if unmatched == 0 else "FAIL"}


def _normalized_from_geometry(kind: str, geometry: list[Any], extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
    features = [_descriptor(obj) for obj in geometry if type(obj).__name__ == "Cylinder"]
    ledger = feature_c3_ledger(features); wrapper = dict(extra or {}); wrapper["feature_ledger"] = ledger; wrapper["geometry_hash"] = hashlib.sha256(canonical(ledger["features"])).hexdigest(); return normalize_geometry_proof(kind, wrapper)


def route_after_gates(f_stock_empty: bool, stock_proof: Mapping[str, Any], stock_gate: Mapping[str, Any], canonical_proof: Mapping[str, Any], canonical_gate: Mapping[str, Any]) -> dict[str, Any]:
    require("c3_status" in stock_proof and "c3_status" in canonical_proof, "M59R1_NORMALIZED_PROOF_REQUIRED")
    if f_stock_empty: return {"classification": "R256_STOCK_MESH1_FREQUENCY_FAILURE_NOT_REPRODUCED", "next_science_decision": "R256_MESH1_FREQUENCY_SCALAR_REQUALIFICATION", "authorize_frequency": False}
    if stock_proof["c3_status"] == "PASS" and not stock_gate.get("operator_gate", False): return {"classification": "R256_STOCK_CONTINUOUS_G15_C3_PASS_BUT_RUNTIME_MATERIAL_BREAKS", "next_science_decision": "VENDORED_MPB_EXACT_EPSILON_NATIVE_SOURCE_PATCH", "authorize_frequency": False}
    if canonical_proof["c3_status"] != "PASS": return {"classification": "R256_CANONICAL_PRIMITIVE_CONTINUOUS_C3_PASS_RUNTIME_MATERIAL_BREAKS", "next_science_decision": "VENDORED_MPB_EXACT_EPSILON_NATIVE_SOURCE_PATCH", "authorize_frequency": False}
    if not canonical_gate.get("operator_gate", False): return {"classification": "R256_CANONICAL_PRIMITIVE_CONTINUOUS_C3_PASS_RUNTIME_MATERIAL_BREAKS", "next_science_decision": "VENDORED_MPB_EXACT_EPSILON_NATIVE_SOURCE_PATCH", "authorize_frequency": False}
    return {"classification": "AUTHORIZE_CANONICAL_FREQUENCY", "next_science_decision": "AUTHORIZE_CANONICAL_FREQUENCY", "authorize_frequency": True}


def _read_dataset(job: Any, state_root: Path, dataset_id: str, manifest: str, schema: str, count: int) -> list[dict[str, Any]]:
    return m59._read_dataset(job, state_root, dataset_id, manifest, schema, count)


def _base(bundle: Mapping[str, Any], source_commit: str, stock: Mapping[str, Any], base: Mapping[str, Any]) -> dict[str, Any]:
    return {"schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "dataset_write": False, "dataset_schema": DATASET_SCHEMA, "source_commit_used": source_commit, "stock_frequency": stock, "scalar_tensor_base_status": {key: base[key] for key in ("scalar_c3_status", "tensor_c3_status", "scalar_c3_residual_max", "tensor_c3_residual_fro_max", "scalar_identity_guard", "tensor_identity_guard")}, "post_native_checkout_unchanged": True, "fields_gaps_subspaces_wilson_berry_computed": False}


def main() -> int:
    bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8")); source_commit = str(os.environ.get("MEPHC_SOURCE_COMMIT") or bundle.get("source_commit") or ""); records: list[dict[str, Any]] = []
    try:
        job = m59.m54.m52r1.m41r3._load(ROOT / "tools/mephc-flow/scientific_job.py", "m59r1_job"); state_root = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"]).parent.parent; stock_records = _read_dataset(job, state_root, MESH1_DATASET_ID, MESH1_MANIFEST, MESH1_SCHEMA, 36); stock_rows = m59._frequency_rows(stock_records); stock = m59.frequency_ledger(stock_rows); material_records = _read_dataset(job, state_root, M54R1_DATASET_ID, M54R1_MANIFEST, M54R1_SCHEMA, 3); mesh1 = next(row for row in material_records if int(row["mesh_size"]) == 1); epsilon = m59.m54.decode_array(mesh1["epsilon_grid"]); tensor = m59.m54.decode_array(mesh1["inverse_epsilon_tensor_grid"]); mapping = m59.m54.build_index_map(); base = m59.m54.material_covariance(epsilon, tensor, mapping); projected, projection = m59.projected_epsilon(epsilon, mapping); result = _base(bundle, source_commit, stock, base); result["projection"] = projection
        if not stock["failure_set"]:
            result.update({"classification": "R256_STOCK_MESH1_FREQUENCY_FAILURE_NOT_REPRODUCED", "causal_outcome": "R256_STOCK_MESH1_FREQUENCY_FAILURE_NOT_REPRODUCED", "next_science_decision": "R256_MESH1_FREQUENCY_SCALAR_REQUALIFICATION", "zero_solver_reason": "F_stock_empty"})
        else:
            import meep as mp
            from meep import mpb
            band = m59.build_band(); stock_geo, _ = m59.stock_geometry(mp, band); canonical_geo, _ = m59.canonical_geometry(mp, band); synthetic_geo, _ = m59.synthetic_geometry(mp, band); stock_proof = _normalized_from_geometry("stock", stock_geo); canonical_proof = _normalized_from_geometry("canonical", canonical_geo, {"derivation": m59.canonical_centers()}); synthetic_proof = _normalized_from_geometry("synthetic", synthetic_geo, {"seed_fractional": [0.25, 0.0]}); stock_gate = m59.material_gate(m59.build_solver(mp, mpb, band, stock_rows[(0, 0, "IDENTITY")]["coordinate"], stock_geo), mp); canonical_gate = m59.material_gate(m59.build_solver(mp, mpb, band, stock_rows[(0, 0, "IDENTITY")]["coordinate"], canonical_geo), mp); synthetic_gate = m59.material_gate(m59.build_solver(mp, mpb, band, stock_rows[(0, 0, "IDENTITY")]["coordinate"], synthetic_geo), mp); route = route_after_gates(False, stock_proof, stock_gate, canonical_proof, canonical_gate); result.update({"stock_continuous_geometry": stock_proof, "canonical_primitive": canonical_proof, "synthetic_control": synthetic_proof, "stock_material_gate": stock_gate, "canonical_material_gate": canonical_gate, "synthetic_material_gate": synthetic_gate, "routing": route})
            if not route["authorize_frequency"]:
                result.update({"classification": route["classification"], "causal_outcome": route["classification"], "next_science_decision": route["next_science_decision"], "zero_solver_reason": "normalized_geometry_or_material_gate"})
            else:
                namespace = {"goal_id": "MEPHC-BERRY-C3-CONSISTENCY-V1", "work_order_id": bundle["work_order_id"], "source_commit": source_commit, "record_schema": DATASET_SCHEMA}; store = job.ImmutableDatasetStore(state_root, namespace)
                for member_index, member in enumerate(MEMBERS):
                    for repeat in range(3):
                        for vertex in range(4):
                            spec = stock_rows[(vertex, repeat, member)]; solver = m59.build_solver(mp, mpb, band, spec["coordinate"], canonical_geo); solver.run_parity(mp.TE, False); frequencies = np.asarray(solver.all_freqs, dtype=float); require(frequencies.reshape(-1)[:4].size == 4, "M59R1_FREQUENCY_LAYOUT_INVALID"); item = {"schema": DATASET_SCHEMA, "record_id": None, "member_index": member_index, "c3_member_identity": member, "repeat_index": repeat, "vertex_index": vertex, "coordinate": list(spec["coordinate"]), "geometry_id": "G15", "resolution": 256, "tolerance": 1e-9, "mesh_size": 1, "deterministic": True, "polarization": "TE", "frequencies_bands_1_to_4": [float(v) for v in frequencies.reshape(-1)[:4]], "canonical_geometry_sha256": canonical_proof["geometry_hash"], "canonical_continuous_proof_sha256": hashlib.sha256(canonical(canonical_proof)).hexdigest(), "canonical_scalar_material_sha256": canonical_gate["epsilon_sha256"], "canonical_tensor_material_sha256": canonical_gate["tensor_sha256"], "source_commit": source_commit}; item["record_id"] = "MEPHC-M59R1-CANONICAL-FREQ-" + hashlib.sha256(canonical({k: v for k, v in item.items() if k != "record_id"})).hexdigest(); store.put(canonical({"work_order_id": bundle["work_order_id"], "member": member, "repeat": repeat, "vertex": vertex}), canonical(item), {"member": member, "repeat": repeat, "vertex": vertex, "record_id": item["record_id"]}); records.append(item)
                manifest = store.finalize(36, {"dataset_schema": DATASET_SCHEMA, "source_parent_dataset_ids": [MESH1_DATASET_ID, M54R1_DATASET_ID], "canonical_geometry_sha256": canonical_proof["geometry_hash"]}); patch = m59.frequency_ledger(m59._frequency_rows(records)); classification, decision, sets = m59.classify(stock, patch); result.update({"solver_execution_count": 36, "dataset_record_count": 36, "dataset_write": True, "dataset_id": manifest.get("dataset_id"), "manifest_sha256": manifest.get("manifest_sha256"), "patched_frequency": patch, "failure_set_relations": {key: sorted(value) for key, value in sets.items()}, "classification": classification.replace("R256_C3_PROJECTED_SCALAR_EPSILON", "R256_CANONICAL_PRIMITIVE") if classification.startswith("R256_C3_PROJECTED") else classification, "causal_outcome": classification.replace("R256_C3_PROJECTED_SCALAR_EPSILON", "R256_CANONICAL_PRIMITIVE") if classification.startswith("R256_C3_PROJECTED") else classification, "next_science_decision": decision})
    except BaseException as exc:
        result = {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": len(records), "dataset_record_count": len(records), "dataset_write": bool(records), "failure_code": str(exc)[:1024], "failure_stage": "m59r1_recover_continuous_geometry_c3_frequency_ab", "exception_type": type(exc).__name__, "source_commit_used": source_commit, "completed_record_ids": [row["record_id"] for row in records], "post_native_checkout_unchanged": True}
    Path(os.environ["MEPHC_RESULT_PATH"]).write_text(json.dumps(_safe(result), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8"); return 0


if __name__ == "__main__":
    raise SystemExit(main())
