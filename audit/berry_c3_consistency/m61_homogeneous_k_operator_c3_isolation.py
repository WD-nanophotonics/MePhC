"""M61: isolate the homogeneous reciprocal/operator control."""
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
SPEC = importlib.util.spec_from_file_location("m61_m54_reference", M54_PATH)
assert SPEC and SPEC.loader
m54 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m54)

RESULT_SCHEMA = "mephc-berry-c3-consistency-m61-homogeneous-k-operator-c3-isolation-v1"
DATASET_SCHEMA = "mephc-berry-c3-consistency-m61-homogeneous-frequency-dataset-v1"
M50_DATASET_ID = "9b560f99fa264905ee99cb68d4ccdf757446ffb7b3a0af0391d5760a9740861d"
M50_MANIFEST = "c009e68d08bd13084eb0320d95ecda5ceab57bdafa8fddef30ecc5b1177563ed"
M50_SCHEMA = "mephc-berry-c3-consistency-m50-r256-mesh1-c3-causal-control-dataset-v1"
M60_DATASET_ID = "4657c25e5443938a5bd3ffaa3f8bb5ea88c0fc9c1c17f008638aa52a43569b28"
M60_MANIFEST = "df22be7416f29e7ba40d7c03e2caf6f604d0a70050fb2ff6d074d9aa0b18d2e1"
M60_SCHEMA = "mephc-berry-c3-consistency-m60-canonical-primitive-frequency-dataset-v1"
MEMBERS = ("IDENTITY", "C3", "C3_SQUARED")
N_EFF = 2.7
D = np.asarray([[-1, 1], [-1, 0]], dtype=int)
A = np.asarray([[0.5, 0.5], [np.sqrt(3.0) / 2.0, -np.sqrt(3.0) / 2.0]], dtype=float)
B = np.linalg.inv(A).T


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
    raise ValueError(f"M61_UNSAFE_RESULT:{type(value).__name__}")


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, "M61_IMPORT_FAILED", str(path))
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


def _read_dataset(job: Any, root: Path, dataset_id: str, manifest: str, schema: str, count: int) -> list[dict[str, Any]]:
    verified = job.verify_dataset(root, dataset_id)
    require(verified.get("dataset_id") == dataset_id and verified.get("manifest_sha256") == manifest and verified.get("record_count") == count, "M61_DATASET_BINDING_INVALID", dataset_id)
    rows = []
    for key in verified["record_key_sha256"]:
        row = json.loads(job.resolve_dataset_record(root, dataset_id, manifest, key)["payload"].decode("utf-8"))
        require(isinstance(row, dict) and row.get("schema") == schema, "M61_DATASET_SCHEMA_INVALID", dataset_id); rows.append(row)
    return rows


def frequency_rows(records: list[dict[str, Any]]) -> dict[tuple[int, int, str], dict[str, Any]]:
    rows = {(int(row["vertex_index"]), int(row["repeat_index"]), str(row["c3_member_identity"])): row for row in records}
    require(len(rows) == 36 and set(rows) == {(v, r, member) for v in range(4) for r in range(3) for member in MEMBERS}, "M61_FREQUENCY_IDENTITY_SET_INVALID")
    return rows


def frequency_ledger(rows: Mapping[tuple[int, int, str], Mapping[str, Any]]) -> dict[str, Any]:
    failures, ledger = [], {}
    for vertex in range(4):
        for source, target in zip(MEMBERS, MEMBERS[1:] + MEMBERS[:1]):
            for band in range(4):
                left = np.asarray([float(rows[(vertex, repeat, source)]["frequencies_bands_1_to_4"][band]) for repeat in range(3)]); right = np.asarray([float(rows[(vertex, repeat, target)]["frequencies_bands_1_to_4"][band]) for repeat in range(3)])
                lm, rm = float(np.median(left)), float(np.median(right)); lu, ru = float(np.max(np.abs(left - lm))), float(np.max(np.abs(right - rm))); item = {"vertex": vertex, "band": band + 1, "source_member": source, "target_member": target, "source_median": lm, "target_median": rm, "source_repeat_uncertainty": lu, "target_repeat_uncertainty": ru, "residual": abs(lm - rm), "combined_repeat_uncertainty": lu + ru, "pass": abs(lm - rm) <= lu + ru}; ledger[f"v{vertex}:{source}_to_{target}:band{band + 1}"] = item
                if not item["pass"]: failures.append(item)
    return {"failure_set": failures, "failure_count": len(failures), "ledger": ledger}


def reciprocal_spectrum(coordinate: Any, window: int, count: int = 4) -> list[float]:
    k = np.asarray([float(coordinate[0]), float(coordinate[1])], dtype=float); values = [float(np.linalg.norm(k - B @ np.asarray([i, j], dtype=float)) / N_EFF) for i in range(-window, window + 1) for j in range(-window, window + 1)]
    return sorted(values)[:count]


def analytic_reference(rows: Mapping[tuple[int, int, str], Mapping[str, Any]]) -> dict[str, Any]:
    unique = {}; convergence = {}
    for vertex in range(4):
        for member in MEMBERS:
            coordinate = rows[(vertex, 0, member)]["coordinate"]; low = reciprocal_spectrum(coordinate, 4); high = reciprocal_spectrum(coordinate, 6); guard = 128.0 * np.finfo(float).eps * max(1.0, max(map(abs, low + high))); stable = bool(np.max(np.abs(np.asarray(low) - np.asarray(high))) <= guard); key = f"v{vertex}:{member}"; unique[key] = {"coordinate": list(coordinate), "first_four": low, "identity_guard": guard}; convergence[key] = {"stable_L4_L6": stable, "max_residual": float(np.max(np.abs(np.asarray(low) - np.asarray(high))))}
    require(all(item["stable_L4_L6"] for item in convergence.values()), "M61_ANALYTIC_REFERENCE_NOT_CONVERGED")
    analytic_rows = {(vertex, repeat, member): {"frequencies_bands_1_to_4": list(unique[f"v{vertex}:{member}"]["first_four"])} for vertex in range(4) for repeat in range(3) for member in MEMBERS}
    ledger = frequency_ledger(analytic_rows); require(not ledger["failure_set"], "M61_ANALYTIC_REFERENCE_NOT_C3")
    return {"reciprocal_basis": B.tolist(), "direct_basis": A.tolist(), "window_L4_L6": convergence, "unique_state_spectra": unique, "c3_frequency": ledger, "c3_status": "PASS"}


def route_after_gates(stock: Mapping[str, Any], canonical: Mapping[str, Any], analytic: Mapping[str, Any], material: Mapping[str, Any]) -> dict[str, Any]:
    stock_set = {(x["vertex"], x["band"], x["source_member"], x["target_member"]) for x in stock["failure_set"]}; canonical_set = {(x["vertex"], x["band"], x["source_member"], x["target_member"]) for x in canonical["failure_set"]}; restored, new = stock_set - canonical_set, canonical_set - stock_set
    require(stock_set, "M61_F_STOCK_EMPTY"); require(not restored and not new, "M61_M60_RELATION_NOT_REPRODUCED"); require(analytic["c3_status"] == "PASS", "M61_ANALYTIC_REFERENCE_NOT_C3"); require(material["sanity_status"] == "PASS", "M61_CONSTANT_MATERIAL_SANITY_FAILED")
    return {"authorize_frequency": True, "reason": "M50_M60_no_restoration_relation_analytic_reference_and_constant_material_pass", "next_science_decision_if_empty": "R256_HOMOGENEOUS_K_OPERATOR_C3_PASS_PATTERNED_FAILURE_PERSISTS"}


def homogeneous_material_context(mp: Any, mpb: Any, band: Any) -> tuple[Any, dict[str, Any]]:
    material = mp.Medium(epsilon=N_EFF ** 2); solver = mpb.ModeSolver(geometry=[], geometry_lattice=band.geo_latt, k_points=[mp.Vector3(0, 0, 0)], resolution=256, num_bands=4, default_material=material, tolerance=1e-9, deterministic=True, mesh_size=1); solver.init_params(mp.NO_PARITY, False); epsilon = np.asarray(solver.get_epsilon(), dtype=float); guard = 128.0 * np.finfo(float).eps * max(1.0, N_EFF ** 2); scalar = float(np.max(np.abs(epsilon - N_EFF ** 2))); getter = getattr(solver, "get_epsilon_inverse_tensor_point", None); require(callable(getter), "M61_INVERSE_TENSOR_GETTER_UNAVAILABLE"); tensor = np.empty((256, 256, 3, 3), dtype=np.complex128)
    for i in range(256):
        for j in range(256): tensor[i, j] = m54._tensor(getter(mp.Vector3(i / 256.0, j / 256.0, 0.0)))
    expected = 1.0 / (N_EFF ** 2); isotropic = float(np.max(np.abs(tensor[..., :2, :2] - np.eye(2) * expected))) <= guard and float(np.max(np.abs(tensor[..., 2, 2] - expected))) <= guard and float(np.max(np.abs(tensor[..., 0, 1]))) <= guard and float(np.max(np.abs(tensor[..., 1, 0]))) <= guard; spatial = float(np.max(np.abs(tensor - tensor[0, 0]))) <= guard; status = "PASS" if scalar <= guard and isotropic and spatial else "FAIL"; return solver, {"scalar_c3_status": "PASS" if scalar <= guard else "FAIL", "scalar_residual_max": scalar, "scalar_identity_guard": guard, "tensor_spatial_status": "PASS" if spatial else "FAIL", "tensor_isotropic_status": "PASS" if isotropic else "FAIL", "tensor_sha256": hashlib.sha256(tensor.tobytes()).hexdigest(), "sanity_status": status, "operator_gate": status == "PASS"}


def classify(homogeneous: Mapping[str, Any]) -> tuple[str, str]:
    if not homogeneous["failure_set"]: return "R256_HOMOGENEOUS_K_OPERATOR_C3_PASS_PATTERNED_FAILURE_PERSISTS", "VENDORED_MPB_EXACT_MATERIAL_CONSTITUTIVE_PATCH_AND_FREQUENCY_AB"
    return "R256_HOMOGENEOUS_K_OPERATOR_C3_BREAKS", "VENDORED_MPB_K_DEPENDENT_PLANEWAVE_OPERATOR_C3_SOURCE_AUDIT_AND_PATCH"


def main() -> int:
    bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8")); source_commit = str(os.environ.get("MEPHC_SOURCE_COMMIT") or bundle.get("source_commit") or ""); records: list[dict[str, Any]] = []
    try:
        job = _load(ROOT / "tools/mephc-flow/scientific_job.py", "m61_science_job"); state_root = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"]).parent.parent; m50_rows = frequency_rows(_read_dataset(job, state_root, M50_DATASET_ID, M50_MANIFEST, M50_SCHEMA, 36)); m60_rows = frequency_rows(_read_dataset(job, state_root, M60_DATASET_ID, M60_MANIFEST, M60_SCHEMA, 36)); stock = frequency_ledger(m50_rows); canonical_result = frequency_ledger(m60_rows); require(stock["failure_set"], "M61_F_STOCK_EMPTY"); stock_set = {(x["vertex"], x["band"], x["source_member"], x["target_member"]) for x in stock["failure_set"]}; canonical_set = {(x["vertex"], x["band"], x["source_member"], x["target_member"]) for x in canonical_result["failure_set"]}; require(not (stock_set - canonical_set) and not (canonical_set - stock_set), "M61_M60_RELATION_NOT_REPRODUCED")
        analytic = analytic_reference(m50_rows); result = {"schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "dataset_write": False, "dataset_schema": DATASET_SCHEMA, "source_commit_used": source_commit, "f_stock": stock, "f_canonical": canonical_result, "analytic_reference": analytic, "post_native_checkout_unchanged": True}
        import meep as mp
        from meep import mpb
        from mephc.band import Band
        band = Band(a=400.0, r1=80.14335684352235, r2=75.13439704080221, n_eff=N_EFF, h=100.0, resolution=256, lattice_type="triangular", polarization="TE", structure_type="slab"); context_solver, material = homogeneous_material_context(mp, mpb, band); route = route_after_gates(stock, canonical_result, analytic, material); result["homogeneous_material_context"] = material; result["routing"] = route
        store = job.ImmutableDatasetStore(state_root, {"goal_id": "MEPHC-BERRY-C3-CONSISTENCY-V1", "work_order_id": bundle["work_order_id"], "source_commit": source_commit, "record_schema": DATASET_SCHEMA})
        for member_index, member in enumerate(MEMBERS):
            for repeat in range(3):
                for vertex in range(4):
                    spec = m50_rows[(vertex, repeat, member)]; solver = mpb.ModeSolver(geometry=[], geometry_lattice=band.geo_latt, k_points=[mp.cartesian_to_reciprocal(mp.Vector3(float(spec["coordinate"][0]), float(spec["coordinate"][1]), 0), band.geo_latt)], resolution=256, num_bands=4, default_material=mp.Medium(epsilon=N_EFF ** 2), tolerance=1e-9, deterministic=True, mesh_size=1); solver.run_parity(mp.TE, False); frequencies = np.asarray(solver.all_freqs, dtype=float).reshape(-1)[:4]; require(frequencies.size == 4, "M61_FREQUENCY_LAYOUT_INVALID"); item = {"schema": DATASET_SCHEMA, "record_id": None, "member_index": member_index, "c3_member_identity": member, "repeat_index": repeat, "vertex_index": vertex, "coordinate": list(spec["coordinate"]), "geometry": [], "epsilon": N_EFF ** 2, "resolution": 256, "tolerance": 1e-9, "mesh_size": 1, "deterministic": True, "polarization": "TE", "frequencies_bands_1_to_4": [float(x) for x in frequencies], "analytic_reference_first4": analytic["unique_state_spectra"][f"v{vertex}:{member}"]["first_four"], "material_context_sha256": hashlib.sha256(canonical(material)).hexdigest(), "source_commit": source_commit}; item["record_id"] = "MEPHC-M61-HOMOGENEOUS-FREQ-" + hashlib.sha256(canonical({k: v for k, v in item.items() if k != "record_id"})).hexdigest(); store.put(canonical({"work_order_id": bundle["work_order_id"], "member": member, "repeat": repeat, "vertex": vertex}), canonical(item), {"member": member, "repeat": repeat, "vertex": vertex, "record_id": item["record_id"]}); records.append(item)
        manifest = store.finalize(36, {"dataset_schema": DATASET_SCHEMA, "source_parent_dataset_ids": [M50_DATASET_ID, M60_DATASET_ID]}); homogeneous = frequency_ledger(frequency_rows(records)); classification, decision = classify(homogeneous); result.update({"solver_execution_count": 36, "dataset_record_count": 36, "dataset_write": True, "dataset_id": manifest.get("dataset_id"), "manifest_sha256": manifest.get("manifest_sha256"), "f_homogeneous": homogeneous, "classification": classification, "causal_outcome": classification, "next_science_decision": decision})
    except BaseException as exc:
        result = {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": len(records), "dataset_record_count": len(records), "dataset_write": bool(records), "failure_code": str(exc)[:1024], "failure_stage": "m61_homogeneous_k_operator_c3_isolation", "exception_type": type(exc).__name__, "source_commit_used": source_commit, "completed_record_ids": [row["record_id"] for row in records], "post_native_checkout_unchanged": True}
    Path(os.environ["MEPHC_RESULT_PATH"]).write_text(json.dumps(_safe(result), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8"); return 0


if __name__ == "__main__":
    raise SystemExit(main())
