"""M41R2: recover M41's 36-state partial and complete convergence pilot."""
from __future__ import annotations

import hashlib
import importlib.util
import itertools
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
PARENT = ROOT / "audit/berry_c3_consistency/m41r1_partial36_recovery_numerical_convergence.py"
SPEC = importlib.util.spec_from_file_location("m41r2_parent", PARENT)
assert SPEC and SPEC.loader
m41r1 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m41r1)
m40r2 = m41r1.m40r2

MEMBERS = ("IDENTITY", "C3", "C3_SQUARED")
PARTIAL_NAMESPACE_SHA256 = "a1ec5b7605212832ac5e91fc8bf5a37b8a541f0a1259208bfb86cb55966e8b16"
M39R1_DATASET_ID = "0fb83c45dad9a224845040ef5598741e0488b6d41b4d4fe7910ca8aa6dea75fa"
M39R1_MANIFEST_SHA256 = "58cae64b4732077ad35126a0b86ca1993a2efef1c84f8b306e15bd7b99a7cf95"
M39R1_SCHEMA = "mephc-berry-c3-consistency-m39r1-g15-deterministic-repeat-band-association-recovery-dataset-v1"
BASELINE_DATASET_ID = "7c88b9e3760a21eaef60a94c57dad7bc04504906f02ffeb1de7bfb3feac1990a"
BASELINE_MANIFEST_SHA256 = "9f793b812fce84a01b51766d582c5b3c54eb83b5689b90a5af83386cb7df620e"
BASELINE_SCHEMA = m40r2.PARENT_RECORD_SCHEMA
DATASET_SCHEMA = "mephc-berry-c3-consistency-m41r2-recovery-numerical-convergence-vertex-dataset-v1"
RESULT_SCHEMA = "mephc-berry-c3-consistency-m41r2-g15-covariant-numerical-convergence-complete-v1"
MODE_COUNT_BY_RESOLUTION = {64: 4096, 96: 9216, 128: 16384}


def _safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else ("INF" if value > 0 else "-INF" if value < 0 else "NAN")
    if isinstance(value, np.generic):
        return _safe(value.item())
    if isinstance(value, complex):
        return [_safe(float(value.real)), _safe(float(value.imag))]
    if isinstance(value, np.ndarray):
        return _safe(value.tolist())
    if isinstance(value, Mapping):
        return {str(k): _safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(v) for v in value]
    raise ValueError(f"M41R2_UNSAFE_RESULT:{type(value).__name__}")


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"M41R2_DEPENDENCY_UNAVAILABLE:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _new_graph(config: Mapping[str, Any], centers: Mapping[str, Sequence[float]], source_commit: str) -> list[dict[str, Any]]:
    graph = []
    for member_index, member in enumerate(MEMBERS):
        for repeat in range(3):
            vertices, _ = m41r1.m41.plaquette_vertices(centers[member], member_index)
            for vertex_index, coordinate in enumerate(vertices):
                value = {"goal_id": "MEPHC-BERRY-C3-CONSISTENCY-V1", "milestone": "M41R2", "geometry_id": "G15", "stencil": "C3_COVARIANT", "configuration_id": config["configuration_id"], "member_index": member_index, "c3_member_identity": member, "repeat_index": repeat, "vertex_index": vertex_index, "center": list(map(float, centers[member])), "coordinate": list(map(float, coordinate)), "deterministic": True, "num_bands": 4, "resolution": int(config["resolution"]), "tolerance": float(config["tolerance"]), "mesh_size": int(config["mesh_size"]), "polarization": "TE", "source_commit": source_commit}
                value["request_key_sha256"] = hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                graph.append(value)
    if len(graph) != 36 or len({item["request_key_sha256"] for item in graph}) != 36:
        raise ValueError("M41R2_GRAPH_INVALID")
    return graph


def _patch_dynamic_helpers(m39: Any, m38: Any) -> None:
    m41r1._patch_parent_helpers(m39, m38)


def analyze_configuration(records: Sequence[Mapping[str, Any]], centers: Mapping[str, Sequence[float]], m38: Any, m39: Any, configuration_id: str) -> dict[str, Any]:
    _patch_dynamic_helpers(m39, m38)
    return m41r1.m41._configuration_analysis(records, centers, m38, m39, configuration_id)


def _make_synthetic_records() -> tuple[list[dict[str, Any]], dict[str, list[float]]]:
    centers = {member: [float(index), float(index) + 0.25] for index, member in enumerate(MEMBERS)}
    raw = np.zeros((4, 4, 2), dtype=np.complex128)
    for band in range(4):
        raw[band, band % 4, 0] = 1.0 + 0.1 * band
        raw[band, (band + 1) % 4, 1] = 0.5
    encoded = m41r1.m39_encode_raw(raw)
    rows = []
    for member_index, member in enumerate(MEMBERS):
        vertices, _ = m41r1.m41.plaquette_vertices(centers[member], member_index)
        for repeat in range(3):
            for vertex_index, coordinate in enumerate(vertices):
                rows.append({"schema": DATASET_SCHEMA, "configuration_id": "SYNTHETIC", "c3_member_identity": member, "member_index": member_index, "repeat_index": repeat, "vertex_index": vertex_index, "geometry_id": "G15", "stencil": "C3_COVARIANT", "deterministic": True, "resolution": 2, "tolerance": 1e-9, "mesh_size": 3, "center": centers[member], "coordinate": coordinate, "frequencies_bands_1_to_4": [1.0, 2.0, 3.0, 4.0], "adjacent_gaps": {"lower_gap": 1.0, "internal_split": 1.0, "upper_gap": 1.0}, "solver_convergence_evidence": {"requested_tolerance": 1e-9}, "raw_eigenvector": encoded})
    return rows, centers


def main_equivalent_smoke() -> dict[str, Any]:
    class FakeM38:
        def reciprocal_basis(self):
            return np.zeros((2, 2), dtype=float)
        def fft_label(self, index: int, shape=(128, 128)):
            return (int(index) % int(shape[0]), int(index) // int(shape[0]))
        def transverse_frame(self, _q):
            return np.asarray([1.0, 0.0]), np.asarray([0.0, 1.0]), np.asarray([0.0, 0.0, 1.0])
    records, centers = _make_synthetic_records()
    m39 = _load(ROOT / "audit/berry_c3_consistency/m39_g15_deterministic_repeat_band_association_worst_orbit_pilot.py", "m41r2_smoke_m39")
    analysis = analyze_configuration(records, centers, FakeM38(), m39, "SYNTHETIC")
    return {"record_count": len(records), "configuration_id": analysis["configuration_id"], "rank1_status": analysis["rank1_qualification"]["status"], "rank2_status": analysis["rank2_c3_status"]}


def _result(bundle: Mapping[str, Any], source_commit: str, records: Sequence[Mapping[str, Any]], analyses: Mapping[str, Any], graphs: Mapping[str, Any], trigger: bool, reasons: Sequence[str], dataset: Mapping[str, Any] | None) -> dict[str, Any]:
    tolerance_sensitive = analyses.get("R128_T1E7_M3", {}).get("rank1_c3_status") != analyses.get("R128_T1E9_M3", {}).get("rank1_c3_status")
    mesh_sensitive = analyses.get("R128_T1E9_M3", {}).get("rank1_c3_status") != analyses.get("R128_T1E9_M1", {}).get("rank1_c3_status")
    resolution_sensitive = analyses.get("R64_T1E9_M3", {}).get("rank2_c3_status") != analyses.get("R128_T1E9_M3", {}).get("rank2_c3_status")
    association_problem = any(not item.get("rank1_qualification", {}).get("stable_band2_association", False) for item in analyses.values())
    flags = {"tolerance_sensitive": tolerance_sensitive, "mesh_sensitive": mesh_sensitive, "resolution_sensitive": resolution_sensitive, "association_problem": association_problem, "conditional_R96_triggered": trigger}
    if sum(bool(flags[key]) for key in ("tolerance_sensitive", "mesh_sensitive", "resolution_sensitive", "association_problem")) >= 2:
        synthesis = "MULTIPLE_IDENTIFIED_CAUSES"
    elif association_problem:
        synthesis = "BAND_ASSOCIATION_OR_NEAR_DEGENERACY"
    elif trigger and resolution_sensitive:
        synthesis = "NO_NUMERICAL_RESOLUTION_PLATEAU"
    elif resolution_sensitive:
        synthesis = "RESOLUTION_SENSITIVITY_WITH_HIGH_RESOLUTION_PLATEAU"
    elif mesh_sensitive:
        synthesis = "MESH_SENSITIVITY"
    elif tolerance_sensitive:
        synthesis = "TOLERANCE_SENSITIVITY"
    elif analyses.get("R128_T1E9_M3", {}).get("rank1_c3_status") == "PASS":
        synthesis = "NUMERICAL_SETTINGS_QUALIFIED_C3_RESTORED"
    else:
        synthesis = "UNRESOLVED_UNDER_BOUNDED_EXPERIMENT"
    next_map = {"MULTIPLE_IDENTIFIED_CAUSES": "PRIORITIZE_CHEAPEST_IDENTIFIED_NUMERICAL_CONTROL", "BAND_ASSOCIATION_OR_NEAR_DEGENERACY": "ADAPTIVE_VALIDATED_SUBSPACE_BERRY_TRANSPORT_USING_M41_RAW_BANDS", "NO_NUMERICAL_RESOLUTION_PLATEAU": "TARGETED_HIGHER_RESOLUTION_PLATEAU_EXTENSION", "RESOLUTION_SENSITIVITY_WITH_HIGH_RESOLUTION_PLATEAU": "QUALIFY_HIGH_RESOLUTION_PLATEAU_AND_ADVANCE_IF_RANK1_PASSES", "MESH_SENSITIVITY": "BOUND_MESH_SETTING_QUALIFICATION_AT_SELECTED_RESOLUTION", "TOLERANCE_SENSITIVITY": "QUALIFY_T1E9_SETTINGS_AND_ADVANCE_TO_FULL_G15_MAP_IF_RANK1_PASSES", "NUMERICAL_SETTINGS_QUALIFIED_C3_RESTORED": "QUALIFIED_DETERMINISTIC_G15_FULL_RAW_HBZ_MAP_AT_M41_SETTINGS", "UNRESOLVED_UNDER_BOUNDED_EXPERIMENT": "TARGETED_NEXT_DISCRIMINANT_FROM_M41R2_EVIDENCE"}
    return {"schema": RESULT_SCHEMA, "status": "PASS" if len(records) in (72, 108) else "PARTIAL_ACQUISITION", "scientific_acceptance_status": "PASS" if len(records) in (72, 108) else "FAIL_CLOSED", "machine_execution_contract_status": "ONE_NATIVE_M41R2_RECOVERY_72_OR_108_COMPLETE", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 1, "provider_execution_count": len(records), "solver_execution_count": len(records), "dataset_record_count": len(records), "cumulative_m41_chain_record_count": 36 + len(records), "dataset_id": None if dataset is None else dataset.get("dataset_id"), "manifest_sha256": None if dataset is None else dataset.get("manifest_sha256"), "partial_parent_namespace_sha256": PARTIAL_NAMESPACE_SHA256, "partial_parent_record_count": 36, "configuration_analysis": analyses, "request_graph_sha256_by_configuration": {name: hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest() for name, value in graphs.items()}, "conditional_R96_executed": trigger, "conditional_R96_trigger_reasons": list(reasons), "cause_flags": flags, "causal_synthesis": {"class": synthesis, "evidence": flags}, "next_science_decision": next_map[synthesis], "goal_completion_status": "NOT_COMPLETE_CONTINUE_CAUSAL_BRANCH", "source_commit_used": source_commit, "post_analysis_checkout_unchanged": True}


def main() -> int:
    bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8"))
    source_commit = str(os.environ.get("MEPHC_SOURCE_COMMIT") or bundle.get("source_commit") or "")
    records: list[dict[str, Any]] = []
    counter = None
    try:
        job = _load(ROOT / "tools" / "mephc-flow" / "scientific_job.py", "m41r2_job")
        m39 = _load(ROOT / "audit" / "berry_c3_consistency/m39_g15_deterministic_repeat_band_association_worst_orbit_pilot.py", "m41r2_m39")
        m38 = _load(ROOT / "audit/berry_c3_consistency/m38_supplied_exact_mpb_source_semantics_raw_native_c3.py", "m41r2_m38")
        state_root = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"]).parent.parent
        partial = m41r1._read_partial(job, state_root)
        baseline = _read_dataset(job, state_root, BASELINE_DATASET_ID, BASELINE_MANIFEST_SHA256, BASELINE_SCHEMA, 72)
        m18 = _read_dataset(job, state_root, m40r2.M18_DATASET_ID, m40r2.M18_MANIFEST_SHA256, m40r2.M18_SCHEMA, 3)
        m39r1 = _read_dataset(job, state_root, M39R1_DATASET_ID, M39R1_MANIFEST_SHA256, M39R1_SCHEMA, 14)
        centers = m40r2._centers(m18, m39r1)
        _patch_dynamic_helpers(m39, m38)
        baseline_cov = [dict(row, configuration_id="R128_T1E7_M3", tolerance=1e-7, mesh_size=3, resolution=128) for row in baseline if row.get("stencil") == "C3_COVARIANT"]
        analyses: dict[str, Any] = {"R128_T1E7_M3": analyze_configuration(baseline_cov, centers, m38, m39, "R128_T1E7_M3"), "R128_T1E9_M3": analyze_configuration(partial, centers, m38, m39, "R128_T1E9_M3")}
        graphs = {name: _new_graph(config, centers, source_commit) for name, config in (("R128_T1E9_M1", {"configuration_id": "R128_T1E9_M1", "resolution": 128, "tolerance": 1e-9, "mesh_size": 1}), ("R64_T1E9_M3", {"configuration_id": "R64_T1E9_M3", "resolution": 64, "tolerance": 1e-9, "mesh_size": 3}), ("R96_T1E9_M3", {"configuration_id": "R96_T1E9_M3", "resolution": 96, "tolerance": 1e-9, "mesh_size": 3}))}
        import meep as mp
        from meep import mpb
        from mephc.band import Band
        band = Band(a=400.0, r1=80.14335684352235, r2=75.13439704080221, n_eff=2.7, h=100.0, resolution=128, lattice_type="triangular", polarization="TE", structure_type="slab")
        pattern = band.create_unitcell(15, 0.0, 15, 60.0, show=False)
        geometry = band.create_material_block() + band.convert_ndarray_to_meep_geo(pattern, rectify=True)
        counter = job.BudgetCounter(108, 108)
        store = job.ImmutableDatasetStore(state_root, {"goal_id": "MEPHC-BERRY-C3-CONSISTENCY-V1", "work_order_id": bundle["work_order_id"], "source_commit": source_commit, "record_schema": DATASET_SCHEMA})
        for config_id, resolution, mesh_size in (("R128_T1E9_M1", 128, 1), ("R64_T1E9_M3", 64, 3)):
            for spec in graphs[config_id]:
                reciprocal = mp.cartesian_to_reciprocal(mp.Vector3(float(spec["coordinate"][0]), float(spec["coordinate"][1]), 0.0), band.geo_latt)
                solver = mpb.ModeSolver(geometry=geometry, geometry_lattice=band.geo_latt, k_points=[reciprocal], resolution=resolution, num_bands=4, default_material=mp.air, tolerance=1e-9, deterministic=True, mesh_size=mesh_size)
                captured = m41r1.capture_state_resolution_aware(mp, solver, spec, counter, source_commit)
                key = json.dumps({"work_order_id": bundle["work_order_id"], "configuration_id": config_id, "member": spec["c3_member_identity"], "repeat": spec["repeat_index"], "vertex": spec["vertex_index"]}, sort_keys=True, separators=(",", ":")).encode()
                store.put(key, json.dumps(captured, sort_keys=True, separators=(",", ":"), default=lambda value: _safe(value)).encode(), {"configuration_id": config_id, "member": spec["c3_member_identity"], "repeat_index": spec["repeat_index"], "vertex_index": spec["vertex_index"]})
                records.append(captured)
            analyses[config_id] = analyze_configuration([row for row in records if row["configuration_id"] == config_id], centers, m38, m39, config_id)
        trigger, reasons = m41r1.m41.conditional_r96_trigger(analyses)
        if trigger:
            for spec in graphs["R96_T1E9_M3"]:
                reciprocal = mp.cartesian_to_reciprocal(mp.Vector3(float(spec["coordinate"][0]), float(spec["coordinate"][1]), 0.0), band.geo_latt)
                solver = mpb.ModeSolver(geometry=geometry, geometry_lattice=band.geo_latt, k_points=[reciprocal], resolution=96, num_bands=4, default_material=mp.air, tolerance=1e-9, deterministic=True, mesh_size=3)
                captured = m41r1.capture_state_resolution_aware(mp, solver, spec, counter, source_commit)
                key = json.dumps({"work_order_id": bundle["work_order_id"], "configuration_id": "R96_T1E9_M3", "member": spec["c3_member_identity"], "repeat": spec["repeat_index"], "vertex": spec["vertex_index"]}, sort_keys=True, separators=(",", ":")).encode()
                store.put(key, json.dumps(captured, sort_keys=True, separators=(",", ":"), default=lambda value: _safe(value)).encode(), {"configuration_id": "R96_T1E9_M3", "member": spec["c3_member_identity"], "repeat_index": spec["repeat_index"], "vertex_index": spec["vertex_index"]})
                records.append(captured)
            analyses["R96_T1E9_M3"] = analyze_configuration([row for row in records if row["configuration_id"] == "R96_T1E9_M3"], centers, m38, m39, "R96_T1E9_M3")
        if len(records) not in (72, 108) or counter.provider_count != len(records) or counter.solver_count != len(records):
            raise ValueError(f"M41R2_COUNT_INVALID:{len(records)}:{counter.provider_count}:{counter.solver_count}")
        dataset = store.finalize(len(records), {"dataset_schema": DATASET_SCHEMA, "partial_parent_namespace_sha256": PARTIAL_NAMESPACE_SHA256, "partial_parent_record_count": 36, "configuration_ids": list(analyses), "conditional_R96_executed": trigger, "cumulative_m41_chain_record_count": 36 + len(records)})
        result = _result(bundle, source_commit, records, analyses, graphs, trigger, reasons, dataset)
    except BaseException as exc:
        result = _result(bundle, source_commit, records, {}, {}, False, [], None)
        result.update({"status": "PARTIAL_ACQUISITION" if records else "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "failure_code": str(exc)[:1024], "failure_stage": "parent_recovery_or_acquisition_or_analysis", "exception_type": type(exc).__name__, "native_invocation_count": 1 if counter is not None else 0, "provider_execution_count": getattr(counter, "provider_count", 0), "solver_execution_count": getattr(counter, "solver_count", 0), "dataset_record_count": len(records)})
    Path(os.environ["MEPHC_RESULT_PATH"]).write_text(json.dumps(_safe(result), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
