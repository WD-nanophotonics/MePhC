"""M44: high-resolution plateau extension at fixed T1E9/M3."""
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
M42_PATH = ROOT / "audit/berry_c3_consistency/m42_m41r3_corrected_uncertainty_cheapest_control_adjudication.py"
SPEC = importlib.util.spec_from_file_location("m44_m42_parent", M42_PATH)
assert SPEC and SPEC.loader
m42 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m42)
m41r3 = m42.m41r3

RESULT_SCHEMA = "mephc-berry-c3-consistency-m44-high-resolution-plateau-extension-v1"
DATASET_SCHEMA = "mephc-berry-c3-consistency-m44-high-resolution-plateau-vertex-dataset-v1"
M41R3_DATASET_ID = "a1edd5623ea1ed4413275a716d33258695d3d81c498a2d663b3608ab5355ed89"
M41R3_MANIFEST_SHA256 = "18dbf109891789d4e4c2f86753d4eae4c7b1ffcedb152459c26f6f9f1a8dbdab"
M41R3_SCHEMA = "mephc-berry-c3-consistency-m41r3-recovery-numerical-convergence-vertex-dataset-v1"
MEMBERS = m41r3.MEMBERS
SETTINGS = {"R128_T1E9_M3": {"resolution": 128, "tolerance": 1e-9, "mesh_size": 3}, "R160_T1E9_M3": {"resolution": 160, "tolerance": 1e-9, "mesh_size": 3}, "R192_T1E9_M3": {"resolution": 192, "tolerance": 1e-9, "mesh_size": 3}}


def _safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else ("INF" if value > 0 else "-INF" if value < 0 else "NAN")
    if isinstance(value, np.generic): return _safe(value.item())
    if isinstance(value, complex): return [_safe(float(value.real)), _safe(float(value.imag))]
    if isinstance(value, np.ndarray): return _safe(value.tolist())
    if isinstance(value, Mapping): return {str(k): _safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)): return [_safe(v) for v in value]
    raise ValueError(f"M44_UNSAFE_RESULT:{type(value).__name__}")


def high_resolution_graph(configuration_id: str, centers: Mapping[str, Any], source_commit: str) -> list[dict[str, Any]]:
    setting = SETTINGS[configuration_id]
    graph = []
    for member_index, member in enumerate(MEMBERS):
        vertices, _ = m41r3._plaquette_vertices(centers[member], member_index)
        for repeat in range(3):
            for vertex_index, coordinate in enumerate(vertices):
                row = {"goal_id": "MEPHC-BERRY-C3-CONSISTENCY-V1", "milestone": "M44", "geometry_id": "G15", "stencil": "C3_COVARIANT", "configuration_id": configuration_id, "member_index": member_index, "c3_member_identity": member, "repeat_index": repeat, "vertex_index": vertex_index, "center": list(map(float, centers[member])), "coordinate": list(map(float, coordinate)), "deterministic": True, "num_bands": 4, "resolution": setting["resolution"], "tolerance": setting["tolerance"], "mesh_size": setting["mesh_size"], "polarization": "TE", "source_commit": source_commit}
                row["request_key_sha256"] = hashlib.sha256(json.dumps(row, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                graph.append(row)
    if len(graph) != 36 or len({row["request_key_sha256"] for row in graph}) != 36:
        raise ValueError("M44_GRAPH_INVALID")
    return graph


def _pair(left: Mapping[str, Any], right: Mapping[str, Any], name: str) -> dict[str, Any]:
    return m42._pair_table(left, right, name)


def plateau(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    """Evaluate the high-resolution pair directly, never through R64."""
    return not m42._sensitive(_pair(left, right, "high_resolution"))


def r192_trigger(r128: Mapping[str, Any], r160: Mapping[str, Any]) -> tuple[bool, list[str]]:
    table = _pair(r128, r160, "R128_R160")
    reasons = []
    for member, value in table["members"].items():
        if any(item["difference_beyond_uncertainty"] for item in value["supported_observables"]): reasons.append(f"scalar_difference:{member}")
        if value["rank1_qualification_changed"]: reasons.append(f"rank1_qualification:{member}")
        if value["rank1_association_changed"] or value["rank2_association_changed"]: reasons.append(f"association:{member}")
        if value["rank1_c3_status_changed"]: reasons.append(f"rank1_c3:{member}")
        if value["rank2_c3_status_changed"]: reasons.append(f"rank2_c3:{member}")
    return bool(reasons), reasons


def select_plateau_control(r128: Mapping[str, Any], r160: Mapping[str, Any], r192: Mapping[str, Any] | None) -> dict[str, Any]:
    pairs = []
    if plateau(r128, r160): pairs.append(("R128_T1E9_M3", "R160_T1E9_M3"))
    if r192 is not None and plateau(r160, r192): pairs.append(("R160_T1E9_M3", "R192_T1E9_M3"))
    eligible = {name: value["rank1_qualification"]["status"] == "RANK1_QUALIFIED" and value["rank1_c3_status"] == "PASS" for name, value in (("R128_T1E9_M3", r128), ("R160_T1E9_M3", r160), ("R192_T1E9_M3", r192)) if value is not None}
    selected = None
    selected_pair = None
    for low, high in pairs:
        if eligible.get(low): selected, selected_pair = low, [low, high]; break
        if eligible.get(high): selected, selected_pair = high, [low, high]; break
    return {"R128_R160_plateau": plateau(r128, r160), "R160_R192_plateau": None if r192 is None else plateau(r160, r192), "established_plateau_pairs": [list(pair) for pair in pairs], "eligible_measured_settings": [name for name, value in eligible.items() if value], "selected_high_resolution_control": selected, "selected_plateau_pair": selected_pair}


def _capture(mp: Any, solver: Any, spec: Mapping[str, Any], counter: Any, source_commit: str) -> dict[str, Any]:
    value = m41r3._capture(mp, solver, spec, counter, source_commit)
    value["schema"] = DATASET_SCHEMA
    value["configuration_id"] = spec["configuration_id"]
    return value


def _result(bundle: Mapping[str, Any], source_commit: str, selection: Mapping[str, Any], analyses: Mapping[str, Any], trigger: bool, reasons: list[str], dataset: Mapping[str, Any] | None, counts: tuple[int, int, int, int], hashes: Mapping[str, str]) -> dict[str, Any]:
    selected = selection.get("selected_high_resolution_control")
    if selection.get("R128_R160_plateau") or selection.get("R160_R192_plateau"):
        outcome = "HIGH_RESOLUTION_PLATEAU_WITH_ADMISSIBLE_CONTROL" if selected else "HIGH_RESOLUTION_PLATEAU_WITH_PERSISTENT_C3_FAILURE"
        decision = "CROSS_ORBIT_QUALIFICATION_AT_SELECTED_HIGH_RESOLUTION_CONTROL" if selected else "BOUND_PLAQUETTE_STEP_CONVERGENCE_PILOT_AT_HIGH_RESOLUTION_CONTROL"
    else:
        outcome, decision = "NO_HIGH_RESOLUTION_PLATEAU", "TARGETED_NEXT_HIGHER_RESOLUTION_PLATEAU_EXTENSION"
    return {"schema": RESULT_SCHEMA, "status": "PASS" if counts[3] in (36, 72) else "FAIL_CLOSED", "scientific_acceptance_status": "PASS" if counts[3] in (36, 72) else "FAIL_CLOSED", "machine_execution_contract_status": "ONE_NATIVE_R160_PLUS_CONDITIONAL_R192_COMPLETE" if counts[0] else "M44_FAIL_CLOSED", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": counts[0], "provider_execution_count": counts[1], "solver_execution_count": counts[2], "dataset_record_count": counts[3], "executed_configurations": list(analyses), "conditional_R192_executed": "R192_T1E9_M3" in analyses, "conditional_R192_trigger": trigger, "conditional_R192_trigger_reasons": reasons, "graph_sha256_by_configuration": dict(hashes), "configuration_analysis": analyses, "plateau_selection": selection, "outcome": outcome, "next_science_decision": decision, "dataset_id": None if dataset is None else dataset.get("dataset_id"), "manifest_sha256": None if dataset is None else dataset.get("manifest_sha256"), "source_commit_used": source_commit, "post_analysis_checkout_unchanged": True}


def main() -> int:
    bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8"))
    source_commit = str(os.environ.get("MEPHC_SOURCE_COMMIT") or bundle.get("source_commit") or "")
    try:
        job = m41r3._load(ROOT / "tools/mephc-flow/scientific_job.py", "m44_job")
        m39 = m41r3._load(ROOT / "audit/berry_c3_consistency/m39_g15_deterministic_repeat_band_association_worst_orbit_pilot.py", "m44_m39")
        m38 = m41r3._load(ROOT / "audit/berry_c3_consistency/m38_supplied_exact_mpb_source_semantics_raw_native_c3.py", "m44_m38")
        state_root = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"]).parent.parent
        partial = m41r3._read_partial(job, state_root)
        new = m41r3._read_dataset(job, state_root, M41R3_DATASET_ID, M41R3_MANIFEST_SHA256, M41R3_SCHEMA, 108)
        m18 = m41r3._read_dataset(job, state_root, m41r3.M18_DATASET_ID, m41r3.M18_MANIFEST_SHA256, m41r3.M18_SCHEMA, 3)
        m39r1 = m41r3._read_dataset(job, state_root, m41r3.M39R1_DATASET_ID, m41r3.M39R1_MANIFEST_SHA256, m41r3.M39R1_SCHEMA, 14)
        centers = m41r3._centers(m18, m39r1)
        matrix = {"R128_T1E9_M3": partial, "R96_T1E9_M3": [row for row in new if row.get("configuration_id") == "R96_T1E9_M3"]}
        if len(matrix["R96_T1E9_M3"]) != 36: raise ValueError("M44_R96_REFERENCE_INVALID")
        analyses = {name: m42._configuration(rows, m38, m39, name) for name, rows in matrix.items()}
        graphs = {name: high_resolution_graph(name, centers, source_commit) for name in ("R160_T1E9_M3", "R192_T1E9_M3")}
        hashes = {name: hashlib.sha256(json.dumps(graph, sort_keys=True, separators=(",", ":")).encode()).hexdigest() for name, graph in graphs.items()}
        import meep as mp
        from meep import mpb
        from mephc.band import Band
        setting = SETTINGS["R160_T1E9_M3"]
        band = Band(a=400.0, r1=80.14335684352235, r2=75.13439704080221, n_eff=2.7, h=100.0, resolution=160, lattice_type="triangular", polarization="TE", structure_type="slab")
        pattern = band.create_unitcell(15, 0.0, 15, 60.0, show=False)
        geometry = band.create_material_block() + band.convert_ndarray_to_meep_geo(pattern, rectify=True)
        counter = job.BudgetCounter(72, 72)
        store = job.ImmutableDatasetStore(state_root, {"goal_id": "MEPHC-BERRY-C3-CONSISTENCY-V1", "work_order_id": bundle["work_order_id"], "source_commit": source_commit, "record_schema": DATASET_SCHEMA})
        records = []
        for spec in graphs["R160_T1E9_M3"]:
            reciprocal = mp.cartesian_to_reciprocal(mp.Vector3(float(spec["coordinate"][0]), float(spec["coordinate"][1]), 0.0), band.geo_latt)
            solver = mpb.ModeSolver(geometry=geometry, geometry_lattice=band.geo_latt, k_points=[reciprocal], resolution=160, num_bands=4, default_material=mp.air, tolerance=1e-9, deterministic=True, mesh_size=3)
            captured = _capture(mp, solver, spec, counter, source_commit)
            key = json.dumps({"work_order_id": bundle["work_order_id"], "configuration_id": "R160_T1E9_M3", "member": spec["c3_member_identity"], "repeat": spec["repeat_index"], "vertex": spec["vertex_index"]}, sort_keys=True, separators=(",", ":")).encode()
            store.put(key, json.dumps(captured, sort_keys=True, separators=(",", ":"), default=lambda value: _safe(value)).encode(), {"configuration_id": "R160_T1E9_M3", "member": spec["c3_member_identity"], "repeat_index": spec["repeat_index"], "vertex_index": spec["vertex_index"]})
            records.append(captured)
        analyses["R160_T1E9_M3"] = m42._configuration(records, m38, m39, "R160_T1E9_M3")
        trigger, reasons = r192_trigger(analyses["R128_T1E9_M3"], analyses["R160_T1E9_M3"])
        if trigger:
            setting = SETTINGS["R192_T1E9_M3"]
            for spec in graphs["R192_T1E9_M3"]:
                reciprocal = mp.cartesian_to_reciprocal(mp.Vector3(float(spec["coordinate"][0]), float(spec["coordinate"][1]), 0.0), band.geo_latt)
                solver = mpb.ModeSolver(geometry=geometry, geometry_lattice=band.geo_latt, k_points=[reciprocal], resolution=192, num_bands=4, default_material=mp.air, tolerance=1e-9, deterministic=True, mesh_size=3)
                captured = _capture(mp, solver, spec, counter, source_commit)
                key = json.dumps({"work_order_id": bundle["work_order_id"], "configuration_id": "R192_T1E9_M3", "member": spec["c3_member_identity"], "repeat": spec["repeat_index"], "vertex": spec["vertex_index"]}, sort_keys=True, separators=(",", ":")).encode()
                store.put(key, json.dumps(captured, sort_keys=True, separators=(",", ":"), default=lambda value: _safe(value)).encode(), {"configuration_id": "R192_T1E9_M3", "member": spec["c3_member_identity"], "repeat_index": spec["repeat_index"], "vertex_index": spec["vertex_index"]})
                records.append(captured)
            analyses["R192_T1E9_M3"] = m42._configuration([row for row in records if row["configuration_id"] == "R192_T1E9_M3"], m38, m39, "R192_T1E9_M3")
        selection = select_plateau_control(analyses["R128_T1E9_M3"], analyses["R160_T1E9_M3"], analyses.get("R192_T1E9_M3"))
        dataset = store.finalize(len(records), {"dataset_schema": DATASET_SCHEMA, "configuration_ids": list(analyses), "conditional_R192_trigger": trigger, "conditional_R192_reasons": reasons, "graph_sha256_by_configuration": hashes, "source_parent_namespace_sha256": m41r3.PARTIAL_NAMESPACE_SHA256})
        result = _result(bundle, source_commit, selection, analyses, trigger, reasons, dataset, (1, counter.provider_count, counter.solver_count, len(records)), hashes)
    except BaseException as exc:
        result = {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "machine_execution_contract_status": "M44_FAIL_CLOSED", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 0, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "failure_code": str(exc)[:1024], "failure_stage": "reference_or_high_resolution_acquisition", "exception_type": type(exc).__name__, "source_commit_used": source_commit}
    Path(os.environ["MEPHC_RESULT_PATH"]).write_text(json.dumps(_safe(result), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__": raise SystemExit(main())
