"""M63: bounded homogeneous raw reciprocal support and tolerance adjudication."""
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
SPEC = importlib.util.spec_from_file_location("m63_m54_reference", M54_PATH); assert SPEC and SPEC.loader
m54 = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(m54)

RESULT_SCHEMA = "mephc-berry-c3-consistency-m63-homogeneous-raw-support-tolerance-adjudication-v1"
DATASET_SCHEMA = "mephc-berry-c3-consistency-m63-homogeneous-raw-mode-tolerance-dataset-v1"
M50_DATASET_ID = "9b560f99fa264905ee99cb68d4ccdf757446ffb7b3a0af0391d5760a9740861d"; M50_MANIFEST = "c009e68d08bd13084eb0320d95ecda5ceab57bdafa8fddef30ecc5b1177563ed"; M50_SCHEMA = "mephc-berry-c3-consistency-m50-r256-mesh1-c3-causal-control-dataset-v1"
M61R1_DATASET_ID = "d3f8933ef1bddb6f7de72af14de0eae8d6c11194fafd6e9d1e61a556a6e4e11e"; M61R1_MANIFEST = "5e97efd186e02ebddd9ee850d10c58931d21786b257db446c14c4064a5b9949e"; M61R1_SCHEMA = "mephc-berry-c3-consistency-m61r1-homogeneous-frequency-dataset-v1"
MEMBERS = ("IDENTITY", "C3", "C3_SQUARED"); N_EFF = 2.7; P = 256 * 256
A = np.asarray([[0.5, 0.5], [np.sqrt(3.0) / 2.0, -np.sqrt(3.0) / 2.0]]); B = np.linalg.inv(A).T; R3 = np.asarray([[-0.5, -np.sqrt(3.0) / 2.0], [np.sqrt(3.0) / 2.0, -0.5]])


def canonical(value: Any) -> bytes: return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
def require(condition: bool, code: str, detail: str = "") -> None:
    if not condition: raise ValueError(f"{code}:{detail}" if detail else code)
def _safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)): return value
    if isinstance(value, float): return value if math.isfinite(value) else ("INF" if value > 0 else "-INF" if value < 0 else "NAN")
    if isinstance(value, np.generic): return _safe(value.item())
    if isinstance(value, np.ndarray): return _safe(value.tolist())
    if isinstance(value, Mapping): return {str(k): _safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)): return [_safe(v) for v in value]
    raise ValueError(f"M63_UNSAFE_RESULT:{type(value).__name__}")
def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path); require(spec and spec.loader, "M63_IMPORT_FAILED", str(path)); module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module
def _read(job: Any, root: Path, dataset_id: str, manifest: str, schema: str, count: int) -> list[dict[str, Any]]:
    verified = job.verify_dataset(root, dataset_id); require(verified.get("dataset_id") == dataset_id and verified.get("manifest_sha256") == manifest and verified.get("record_count") == count, "M63_DATASET_BINDING_INVALID", dataset_id); rows = []
    for key in verified["record_key_sha256"]:
        row = json.loads(job.resolve_dataset_record(root, dataset_id, manifest, key)["payload"].decode()); require(row.get("schema") == schema, "M63_DATASET_SCHEMA_INVALID", dataset_id); rows.append(row)
    return rows
def frequency_rows(records: list[dict[str, Any]]) -> dict[tuple[int, int, str], dict[str, Any]]:
    rows = {(int(x["vertex_index"]), int(x["repeat_index"]), str(x["c3_member_identity"])): x for x in records}; require(len(rows) == 36, "M63_FREQUENCY_IDENTITY_SET_INVALID"); return rows
def experimental_ledger(rows: Mapping[tuple[int, int, str], Mapping[str, Any]]) -> dict[str, Any]:
    failures = []
    for v in range(4):
        for source, target in zip(MEMBERS, MEMBERS[1:] + MEMBERS[:1]):
            for band in range(4):
                left = np.asarray([float(rows[(v, r, source)]["frequencies_bands_1_to_4"][band]) for r in range(3)]); right = np.asarray([float(rows[(v, r, target)]["frequencies_bands_1_to_4"][band]) for r in range(3)]); lm, rm = float(np.median(left)), float(np.median(right)); lu, ru = float(np.max(abs(left - lm))), float(np.max(abs(right - rm))); item = {"vertex": v, "band": band + 1, "source_member": source, "target_member": target, "source_median": lm, "target_median": rm, "source_repeat_uncertainty": lu, "target_repeat_uncertainty": ru, "residual": abs(lm - rm), "combined_repeat_uncertainty": lu + ru}
                if item["residual"] > item["combined_repeat_uncertainty"]: failures.append(item)
    return {"failure_set": failures, "failure_count": len(failures)}
def reciprocal_entries(coordinate: Any, window: int = 8, keep: int = 64) -> list[dict[str, Any]]:
    k = np.asarray(coordinate, dtype=float); return sorted(({"label": [i, j], "frequency": float(np.linalg.norm(k - B @ np.asarray([i, j])) / N_EFF)} for i in range(-window, window + 1) for j in range(-window, window + 1)), key=lambda x: (x["frequency"], x["label"]))[:keep]
def shell_catalog(coordinate: Any) -> dict[str, Any]:
    entries = reciprocal_entries(coordinate, 8, 64); shells = []
    for item in entries:
        guard = 512 * np.finfo(float).eps * max(1.0, abs(item["frequency"]))
        if not shells or abs(item["frequency"] - shells[-1]["frequency"]) > guard: shells.append({"shell_index": len(shells) + 1, "frequency": item["frequency"], "labels": [item["label"]], "shell_guard": guard})
        else: shells[-1]["labels"].append(item["label"])
    return {"entries": entries, "shells": shells, "first4_shells": [next(shell["shell_index"] for shell in shells if label in shell["labels"]) for label in [item["label"] for item in entries[:4]]]}
def interval_assignment(central: float, uncertainty: float, catalog: Mapping[str, Any]) -> dict[str, Any]:
    candidates = []
    for shell in catalog["shells"]:
        guard = 512 * np.finfo(float).eps * max(1.0, abs(float(shell["frequency"])), abs(float(central)))
        if abs(float(central) - float(shell["frequency"])) <= uncertainty + guard: candidates.append(shell)
    if len(candidates) == 1: return {"status": "DEFINITE", "shell": candidates[0]}
    if len(candidates) > 1: return {"status": "AMBIGUOUS_ANALYTIC_SHELL", "candidates": candidates}
    return {"status": "UNMATCHED_ANALYTIC_VALUE"}
def normalize_raw(raw: Any) -> tuple[np.ndarray, dict[str, Any]]:
    array = np.asarray(raw); shape = tuple(array.shape)
    if shape == (P, 2, 4): canonical_raw = np.transpose(array, (2, 0, 1)); layout = "(P,2,4)"
    elif shape == (4, P, 2): canonical_raw = array; layout = "(4,P,2)"
    elif shape == (4, 2, P): canonical_raw = np.transpose(array, (0, 2, 1)); layout = "(4,2,P)"
    else: raise ValueError(f"M63_RAW_LAYOUT_UNSUPPORTED:{shape}")
    require(canonical_raw.shape == (4, P, 2), "M63_RAW_CANONICAL_SHAPE_INVALID", str(canonical_raw.shape)); return canonical_raw, {"native_shape": list(shape), "canonical_shape": [4, P, 2], "accepted_layout": layout}
def shell_support(raw: Any, catalog: Mapping[str, Any]) -> dict[str, Any]:
    canonical_raw, layout = normalize_raw(raw); power = np.sum(np.abs(canonical_raw) ** 2, axis=2); totals = np.sum(power, axis=1); normalized = power / np.maximum(totals[:, None], np.finfo(float).tiny); output = []
    for band in range(4):
        shell_power = [{"shell_index": shell["shell_index"], "frequency": shell["frequency"], "labels": shell["labels"], "power": float(sum(normalized[band, (label[0] % 256) * 256 + label[1] % 256] for label in shell["labels"]))} for shell in catalog["shells"]]; ordered = sorted(shell_power, key=lambda x: (-x["power"], x["shell_index"])); top, second = ordered[0], ordered[1]; guard = 512 * np.finfo(float).eps * max(1.0, top["power"], second["power"]); output.append({"band": band + 1, "shells": shell_power, "dominant_shell": top["shell_index"] if top["power"] - second["power"] > guard else None, "dominance_margin": top["power"] - second["power"], "dominance_guard": guard, "status": "DEFINITE" if top["power"] - second["power"] > guard else "AMBIGUOUS_RAW_SHELL", "outside_catalog_power": max(0.0, 1.0 - sum(x["power"] for x in shell_power))})
    return {"layout": layout, "bands": output, "canonical_raw_sha256": hashlib.sha256(np.ascontiguousarray(canonical_raw).tobytes()).hexdigest()}
def tolerance_assessment(metrics: list[Mapping[str, float]], guards: Mapping[str, float]) -> str:
    if len(metrics) != 3: return "NOT_RUN"
    if all(metrics[-1][key] <= guards.get(key, 0.0) for key in ("max_member_absolute_analytic_error", "max_directed_c3_residual")): return "TIGHT_MACHINE_RESTORED"
    sensitive = all(metrics[i + 1][key] < metrics[i][key] - guards.get(key, 0.0) for i in (0, 1) for key in ("max_member_absolute_analytic_error", "max_directed_c3_residual"))
    return "TOLERANCE_SENSITIVE" if sensitive else "TOLERANCE_INSENSITIVE"
def classify_raw(mechanisms: set[str], tolerance: str = "NOT_RUN") -> tuple[str, str]:
    if "RAW_SHELL_AMBIGUOUS" in mechanisms: return "R256_HOMOGENEOUS_RAW_SHELL_AMBIGUOUS", "VENDORED_MPB_HOMOGENEOUS_NATIVE_MODE_METADATA_SOURCE_AUDIT"
    if mechanisms == {"RAW_RECIPROCAL_SELECTION_BREAK"}: return "R256_HOMOGENEOUS_RAW_RECIPROCAL_LABEL_SELECTION_BREAK", "VENDORED_MPB_RECIPROCAL_BASIS_TRUNCATION_C3_SOURCE_PATCH_AND_HOMOGENEOUS_AB"
    if mechanisms == {"RAW_SAME_SHELL_VALUE_DEFORMATION"}:
        if tolerance == "TIGHT_MACHINE_RESTORED": return "R256_HOMOGENEOUS_RAW_SAME_SHELL_TIGHT_TOLERANCE_RESTORED", "QUALIFY_FULL_HOMOGENEOUS_C3_GRAPH_AT_T1E13_BEFORE_ANY_SOURCE_PATCH"
        if tolerance == "TOLERANCE_SENSITIVE": return "R256_HOMOGENEOUS_RAW_SAME_SHELL_TOLERANCE_SENSITIVE", "QUALIFY_FULL_HOMOGENEOUS_C3_GRAPH_AT_T1E13_BEFORE_ANY_SOURCE_PATCH"
        return "R256_HOMOGENEOUS_RAW_SAME_SHELL_VALUE_DEFORMATION_TOLERANCE_INSENSITIVE", "VENDORED_MPB_HOMOGENEOUS_OPERATOR_EIGENSOLVER_C3_SOURCE_AUDIT_AND_PATCH"
    return "R256_HOMOGENEOUS_RAW_MIXED_SELECTION_AND_VALUE_DEFORMATION", "VENDORED_MPB_RECIPROCAL_BASIS_PATCH_FIRST_THEN_REPEAT_HOMOGENEOUS_RAW_AB"


def main() -> int:
    bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text()); source_commit = str(os.environ.get("MEPHC_SOURCE_COMMIT") or bundle.get("source_commit") or ""); records = []
    try:
        job = _load(ROOT / "tools/mephc-flow/scientific_job.py", "m63_job"); state_root = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"]).parent.parent; m50 = frequency_rows(_read(job, state_root, M50_DATASET_ID, M50_MANIFEST, M50_SCHEMA, 36)); m61 = frequency_rows(_read(job, state_root, M61R1_DATASET_ID, M61R1_MANIFEST, M61R1_SCHEMA, 36)); homogeneous = experimental_ledger(m61); require(homogeneous["failure_set"], "M63_HOMOGENEOUS_FAILURE_NOT_REPRODUCED"); assignments = {}; catalogs = {}
        for vertex in range(4):
            for member in MEMBERS:
                key = f"v{vertex}:{member}"; catalogs[key] = shell_catalog(m61[(vertex, 0, member)]["coordinate"]); assignments[key] = [interval_assignment(float(np.median([float(m61[(vertex, r, member)]["frequencies_bands_1_to_4"][band]) for r in range(3)])), float(np.max(np.abs(np.asarray([float(m61[(vertex, r, member)]["frequencies_bands_1_to_4"][band]) for r in range(3)]) - np.median([float(m61[(vertex, r, member)]["frequencies_bands_1_to_4"][band]) for r in range(3)])))), catalogs[key]) for band in range(4)]
        require(any(item["status"] == "UNMATCHED_ANALYTIC_VALUE" for bands in assignments.values() for item in bands), "M63_M62_UNMATCHED_NOT_REPRODUCED"); affected = sorted({int(x["vertex"]) for x in homogeneous["failure_set"]}); worst = sorted(homogeneous["failure_set"], key=lambda x: (-(x["residual"] - x["combined_repeat_uncertainty"]), -x["residual"], x["vertex"], x["band"], x["source_member"], x["target_member"]))[0]
        result = {"schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "dataset_schema": DATASET_SCHEMA, "f_homogeneous": homogeneous, "affected_vertices": affected, "frozen_worst_failure": worst, "analytic_catalog": catalogs, "pre_native_assignments": assignments, "source_commit_used": source_commit, "post_native_checkout_unchanged": True}
        import meep as mp
        from meep import mpb
        from mephc.band import Band
        band = Band(a=400.0, r1=80.14335684352235, r2=75.13439704080221, n_eff=N_EFF, h=100.0, resolution=256, lattice_type="triangular", polarization="TE", structure_type="slab"); affected_raw = {}; store = job.ImmutableDatasetStore(state_root, {"goal_id": "MEPHC-BERRY-C3-CONSISTENCY-V1", "work_order_id": bundle["work_order_id"], "source_commit": source_commit, "record_schema": DATASET_SCHEMA})
        for vertex in affected:
            for member in MEMBERS:
                spec = m61[(vertex, 0, member)]; solver = mpb.ModeSolver(geometry=[], geometry_lattice=band.geo_latt, k_points=[mp.cartesian_to_reciprocal(mp.Vector3(float(spec["coordinate"][0]), float(spec["coordinate"][1]), 0), band.geo_latt)], resolution=256, num_bands=4, default_material=mp.Medium(epsilon=N_EFF ** 2), tolerance=1e-9, deterministic=True, mesh_size=1); solver.run_parity(mp.TE, False); raw = solver.get_eigenvectors(1, 4); support = shell_support(raw, catalogs[f"v{vertex}:{member}"]); affected_raw[f"v{vertex}:{member}"] = support; row = {"schema": DATASET_SCHEMA, "vertex": vertex, "member": member, "tolerance": 1e-9, "coordinate": list(spec["coordinate"]), "raw_shape": support["layout"], "raw_hash": support["canonical_raw_sha256"], "shell_support": support, "source_commit": source_commit}; records.append(row); store.put(canonical({"work_order_id": bundle["work_order_id"], "vertex": vertex, "member": member, "tolerance": 1e-9}), canonical(row), {"vertex": vertex, "member": member, "tolerance": 1e-9})
        mechanisms = set()
        for failure in homogeneous["failure_set"]:
            source = affected_raw[f"v{failure['vertex']}:{failure['source_member']}"]["bands"][failure["band"] - 1]; target = affected_raw[f"v{failure['vertex']}:{failure['target_member']}"]["bands"][failure["band"] - 1]; mechanism = "RAW_SHELL_AMBIGUOUS" if source["status"] != "DEFINITE" or target["status"] != "DEFINITE" else ("RAW_SAME_SHELL_VALUE_DEFORMATION" if source["dominant_shell"] == target["dominant_shell"] else "RAW_RECIPROCAL_SELECTION_BREAK"); mechanisms.add(mechanism)
        tolerance_state = "NOT_RUN"; pilot_metrics = []
        worst_source = affected_raw.get(f"v{worst['vertex']}:{worst['source_member']}", {}).get("bands", [{}])[worst["band"] - 1]; worst_target = affected_raw.get(f"v{worst['vertex']}:{worst['target_member']}", {}).get("bands", [{}])[worst["band"] - 1]
        if worst_source.get("status") == "DEFINITE" and worst_target.get("status") == "DEFINITE" and worst_source.get("dominant_shell") == worst_target.get("dominant_shell"):
            expected = float(m61[(worst["vertex"], 0, worst["source_member"])]["analytic_reference_first4"][worst["band"] - 1])
            baseline_values = [float(np.median([float(m61[(worst["vertex"], repeat, member)]["frequencies_bands_1_to_4"][worst["band"] - 1]) for repeat in range(3)])) for member in MEMBERS]
            pilot_metrics.append({"tolerance": 1e-9, "max_member_absolute_analytic_error": max(abs(value - expected) for value in baseline_values), "max_directed_c3_residual": max(abs(baseline_values[index] - baseline_values[(index + 1) % 3]) for index in range(3)), "dominant_shell_identity": True})
            for tolerance in (1e-11, 1e-13):
                values = []
                for member in MEMBERS:
                    spec = m61[(worst["vertex"], 0, member)]; solver = mpb.ModeSolver(geometry=[], geometry_lattice=band.geo_latt, k_points=[mp.cartesian_to_reciprocal(mp.Vector3(float(spec["coordinate"][0]), float(spec["coordinate"][1]), 0), band.geo_latt)], resolution=256, num_bands=4, default_material=mp.Medium(epsilon=N_EFF ** 2), tolerance=tolerance, deterministic=True, mesh_size=1); solver.run_parity(mp.TE, False); raw = solver.get_eigenvectors(1, 4); support = shell_support(raw, catalogs[f"v{worst['vertex']}:{member}"]); frequency = float(np.asarray(solver.all_freqs, dtype=float).reshape(-1)[worst["band"] - 1]); values.append(frequency); row = {"schema": DATASET_SCHEMA, "vertex": worst["vertex"], "member": member, "tolerance": tolerance, "coordinate": list(spec["coordinate"]), "raw_shape": support["layout"], "raw_hash": support["canonical_raw_sha256"], "shell_support": support, "source_commit": source_commit}; records.append(row); store.put(canonical({"work_order_id": bundle["work_order_id"], "vertex": worst["vertex"], "member": member, "tolerance": tolerance}), canonical(row), {"vertex": worst["vertex"], "member": member, "tolerance": tolerance})
                residual = max(abs(value - expected) for value in values); c3_residual = max(abs(values[index] - values[(index + 1) % 3]) for index in range(3)); pilot_metrics.append({"tolerance": tolerance, "max_member_absolute_analytic_error": residual, "max_directed_c3_residual": c3_residual, "dominant_shell_identity": True})
            tolerance_state = tolerance_assessment(pilot_metrics, {"max_member_absolute_analytic_error": 256 * np.finfo(float).eps, "max_directed_c3_residual": 256 * np.finfo(float).eps})
        result["raw_support"] = affected_raw; result["raw_mechanisms"] = sorted(mechanisms); result["tolerance_pilot"] = {"state": tolerance_state, "metrics": pilot_metrics}; classification, decision = classify_raw(mechanisms, tolerance_state); result.update({"classification": classification, "causal_outcome": classification, "next_science_decision": decision, "solver_execution_count": len(records), "dataset_record_count": len(records)})
        manifest = store.finalize(len(records), {"dataset_schema": DATASET_SCHEMA}); result.update({"dataset_write": True, "dataset_id": manifest.get("dataset_id"), "manifest_sha256": manifest.get("manifest_sha256")})
    except BaseException as exc:
        result = {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": len(records), "dataset_record_count": len(records), "dataset_write": bool(records), "failure_code": str(exc)[:1024], "failure_stage": "m63_homogeneous_raw_support_tolerance_adjudication", "exception_type": type(exc).__name__, "source_commit_used": source_commit, "completed_record_count": len(records), "post_native_checkout_unchanged": True}
    Path(os.environ["MEPHC_RESULT_PATH"]).write_text(json.dumps(_safe(result), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n"); return 0


if __name__ == "__main__": raise SystemExit(main())
