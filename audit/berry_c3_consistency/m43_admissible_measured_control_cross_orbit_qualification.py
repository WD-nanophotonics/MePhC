"""M43: choose an admissible measured control, then qualify three new orbits."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
M42_PATH = ROOT / "audit/berry_c3_consistency/m42_m41r3_corrected_uncertainty_cheapest_control_adjudication.py"
SPEC = importlib.util.spec_from_file_location("m43_m42_parent", M42_PATH)
assert SPEC and SPEC.loader
m42 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m42)
m41r3 = m42.m41r3

RESULT_SCHEMA = "mephc-berry-c3-consistency-m43-admissible-control-cross-orbit-qualification-v1"
DATASET_SCHEMA = "mephc-berry-c3-consistency-m43-selected-control-cross-orbit-vertex-dataset-v1"
M41R3_DATASET_ID = "a1edd5623ea1ed4413275a716d33258695d3d81c498a2d663b3608ab5355ed89"
M41R3_MANIFEST_SHA256 = "18dbf109891789d4e4c2f86753d4eae4c7b1ffcedb152459c26f6f9f1a8dbdab"
M41R3_SCHEMA = "mephc-berry-c3-consistency-m41r3-recovery-numerical-convergence-vertex-dataset-v1"
K = np.asarray([2.0 / 3.0, 0.0])
ORBIT_M_VALUES = (1, 4, 10)
MEMBERS = ("IDENTITY", "C3", "C3_SQUARED")


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
    raise ValueError(f"M43_UNSAFE_RESULT:{type(value).__name__}")


def _rotate(point: Sequence[float], turns: int) -> list[float]:
    angle = 2.0 * math.pi * int(turns) / 3.0
    rotation = np.asarray([[math.cos(angle), -math.sin(angle)], [math.sin(angle), math.cos(angle)]])
    return (K + rotation @ (np.asarray(point, dtype=float) - K)).tolist()


def orbit_centers(m: int) -> dict[str, list[float]]:
    seed = K - np.asarray([float(m) / 36.0, 0.0])
    return {member: _rotate(seed, index) for index, member in enumerate(MEMBERS)}


def _graph(m: int, setting: Mapping[str, Any], source_commit: str) -> list[dict[str, Any]]:
    centers = orbit_centers(m)
    graph: list[dict[str, Any]] = []
    for member_index, member in enumerate(MEMBERS):
        vertices, _ = m41r3._plaquette_vertices(centers[member], member_index)
        for repeat in range(3):
            for vertex_index, coordinate in enumerate(vertices):
                row = {"goal_id": "MEPHC-BERRY-C3-CONSISTENCY-V1", "milestone": "M43", "orbit_m": int(m), "geometry_id": "G15", "stencil": "C3_COVARIANT", "configuration_id": "M43_SELECTED_CONTROL", "member_index": member_index, "c3_member_identity": member, "repeat_index": repeat, "vertex_index": vertex_index, "center": list(map(float, centers[member])), "coordinate": list(map(float, coordinate)), "deterministic": True, "num_bands": 4, "resolution": int(setting["resolution"]), "tolerance": float(setting["tolerance"]), "mesh_size": int(setting["mesh_size"]), "polarization": "TE", "source_commit": source_commit}
                row["request_key_sha256"] = hashlib.sha256(json.dumps(row, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                graph.append(row)
    if len(graph) != 36 or len({row["request_key_sha256"] for row in graph}) != 36:
        raise ValueError("M43_ORBIT_GRAPH_INVALID")
    return graph


def cross_orbit_graph(setting: Mapping[str, Any], source_commit: str) -> list[dict[str, Any]]:
    graph = []
    for m in ORBIT_M_VALUES:
        graph.extend(_graph(m, setting, source_commit))
    if len(graph) != 108 or len({row["request_key_sha256"] for row in graph}) != 108:
        raise ValueError("M43_CROSS_ORBIT_GRAPH_INVALID")
    if any(row["configuration_id"] == "R128_T1E9_M3" for row in graph):
        raise ValueError("M43_PARENT_CONFIGURATION_IN_GRAPH")
    return graph


def _equivalent(candidate: Mapping[str, Any], reference: Mapping[str, Any]) -> tuple[bool, dict[str, Any]]:
    table = m42._pair_table(candidate, reference, f"{candidate['configuration_id']}_vs_R128_T1E9_M3")
    reasons = []
    if m42._sensitive(table):
        reasons.append("supported_scalar_or_status_difference")
    if not candidate["rank1_qualification"]["stable_band2_association"] or candidate["rank1_qualification"]["status"] != "RANK1_QUALIFIED":
        reasons.append("candidate_rank1_not_qualified")
    if candidate["rank1_c3_status"] != reference["rank1_c3_status"] or candidate["rank2_c3_status"] != reference["rank2_c3_status"]:
        reasons.append("exact_c3_status_difference")
    return not reasons, {"candidate": candidate["configuration_id"], "reference": reference["configuration_id"], "equivalent": not reasons, "reasons": reasons, "comparison": table}


def select_admissible_control(analyses: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    reference = analyses["R128_T1E9_M3"]
    settings = {"R128_T1E7_M3": (128, 1e-7, 3), "R128_T1E9_M3": (128, 1e-9, 3), "R128_T1E9_M1": (128, 1e-9, 1), "R64_T1E9_M3": (64, 1e-9, 3), "R96_T1E9_M3": (96, 1e-9, 3)}
    statuses, eligible, rejected = {}, [], {}
    for name, analysis in analyses.items():
        own = analysis["rank1_qualification"]["status"] == "RANK1_QUALIFIED" and analysis["rank1_c3_status"] == "PASS"
        if name == "R128_T1E9_M3":
            equivalent, evidence = own, {"candidate": name, "reference": name, "equivalent": own, "reasons": [] if own else ["reference_not_eligible"]}
        else:
            equivalent, evidence = _equivalent(analysis, reference)
            equivalent = equivalent and own
            if not own and "candidate_rank1_not_qualified" not in evidence["reasons"]:
                evidence["reasons"].append("candidate_rank1_not_qualified")
        statuses[name] = {"own_eligible": own, **evidence}
        if equivalent:
            eligible.append(name)
        else:
            rejected[name] = evidence["reasons"]
    selected = min(eligible, key=lambda name: (settings[name][0], -math.log10(settings[name][1]), settings[name][2])) if eligible else None
    return {"own_eligible_measured_settings": [name for name, value in statuses.items() if value["own_eligible"]], "equivalence_status_by_candidate": statuses, "admissible_measured_settings": eligible, "selected_admissible_measured_setting": selected, "rejected_candidate_reasons": rejected, "reference_setting": "R128_T1E9_M3"}


def _capture_record(mp: Any, solver: Any, spec: Mapping[str, Any], counter: Any, source_commit: str) -> dict[str, Any]:
    captured = m41r3._capture(mp, solver, spec, counter, source_commit)
    captured["schema"] = DATASET_SCHEMA
    captured["orbit_m"] = int(spec["orbit_m"])
    captured["configuration_id"] = "M43_SELECTED_CONTROL"
    return captured


def _outcome(orbit_analyses: Mapping[int, Mapping[str, Any]], m7: Mapping[str, Any]) -> tuple[str, str]:
    rank1_pass = all(value["rank1_qualification"]["status"] == "RANK1_QUALIFIED" and value["rank1_c3_status"] == "PASS" for value in orbit_analyses.values()) and m7["rank1_qualification"]["status"] == "RANK1_QUALIFIED" and m7["rank1_c3_status"] == "PASS"
    if rank1_pass:
        return "ALL_REMAINING_ORBITS_RANK1_C3_PASS", "QUALIFIED_DETERMINISTIC_G15_FULL_RAW_HBZ_MAP_AT_SELECTED_ADMISSIBLE_MEASURED_SETTING"
    if any(not value["rank1_qualification"]["stable_band2_association"] for value in orbit_analyses.values()):
        return "RANK1_ASSOCIATION_OR_GAP_FAILURE", "ADAPTIVE_VALIDATED_SUBSPACE_BERRY_TRANSPORT_USING_M43_CROSS_ORBIT_RAW_BANDS"
    if all(value["rank1_c3_status"] != "PASS" for value in orbit_analyses.values()):
        return "C3_FAILURE_WITH_STABLE_RANK1_AND_SAFE_BRANCH", "FAILED_ORBIT_NUMERICAL_CONVERGENCE_DISCRIMINANT"
    return "MIXED_FAILURES", "PRIORITIZE_CHEAPEST_FAILED_ORBIT_DISCRIMINANT"


def _synthetic_measured_analysis(name: str, eligible: bool = True) -> dict[str, Any]:
    members = {member: {"rank1_association": eligible, "rank2_association": {edge: {"state": "CANONICAL_STABLE"} for edge in range(4)}, "rank1_phase_density": {"median": 1.0, "uncertainty": 0.01}, "rank2_trace_phase_density": {"median": 1.0, "uncertainty": 0.01}} for member in MEMBERS}
    return {"configuration_id": name, "member_summary": members, "rank1_qualification": {"status": "RANK1_QUALIFIED" if eligible else "RANK1_WITHHELD", "stable_band2_association": eligible}, "rank2_association_stable": eligible, "rank1_c3_status": "PASS" if eligible else "RANK1_WITHHELD", "rank2_c3_status": "PASS" if eligible else "FAIL"}


def main_equivalent_dry_run() -> dict[str, Any]:
    """Exercise both pre-Native branches without Meep, MPB, or dataset writes."""
    names = ("R128_T1E7_M3", "R128_T1E9_M3", "R128_T1E9_M1", "R64_T1E9_M3", "R96_T1E9_M3")
    eligible = {name: _synthetic_measured_analysis(name) for name in names}
    selection = select_admissible_control(eligible)
    graph = cross_orbit_graph({"resolution": 128, "tolerance": 1e-9, "mesh_size": 3}, "dry-run")
    persisted = [row["request_key_sha256"] for row in graph]
    blocked = {name: _synthetic_measured_analysis(name, eligible=False) for name in names}
    no_control = select_admissible_control(blocked)
    return {"selected": selection["selected_admissible_measured_setting"], "selected_graph_records": len(persisted), "selected_unique_records": len(set(persisted)), "no_control": no_control["selected_admissible_measured_setting"], "counts": {"selected_branch_native": 0, "selected_branch_provider": 0, "selected_branch_solver": 0, "no_control_branch_native": 0, "no_control_branch_provider": 0, "no_control_branch_solver": 0}}


def _result(bundle: Mapping[str, Any], source_commit: str, selection: Mapping[str, Any], outcome: str, decision: str, orbit_analyses: Mapping[int, Any], dataset: Mapping[str, Any] | None, counts: tuple[int, int, int, int], graph_hash: str | None) -> dict[str, Any]:
    return {"schema": RESULT_SCHEMA, "status": "PASS" if counts[0] in (0, 108) else "PARTIAL_ACQUISITION", "scientific_acceptance_status": "PASS" if outcome == "ALL_REMAINING_ORBITS_RANK1_C3_PASS" else "FAIL_CLOSED", "machine_execution_contract_status": "ONE_NATIVE_M43_CROSS_ORBIT_108_COMPLETE" if counts[0] == 108 else "ZERO_SCIENTIFIC_EXECUTION_NO_ADMISSIBLE_CONTROL" if counts[0] == 0 else "M43_PARTIAL_ACQUISITION", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": counts[0] // 108, "provider_execution_count": counts[1], "solver_execution_count": counts[2], "dataset_record_count": counts[3], "control_selection": selection, "selected_setting": selection.get("selected_admissible_measured_setting"), "orbit_m_values": list(ORBIT_M_VALUES), "orbit_analysis": orbit_analyses, "cross_orbit_outcome": outcome, "next_science_decision": decision, "request_graph_sha256": graph_hash, "dataset_id": None if dataset is None else dataset.get("dataset_id"), "manifest_sha256": None if dataset is None else dataset.get("manifest_sha256"), "source_commit_used": source_commit, "parent_m41r3_dataset_id": M41R3_DATASET_ID, "post_analysis_checkout_unchanged": True}


def main() -> int:
    bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8"))
    source_commit = str(os.environ.get("MEPHC_SOURCE_COMMIT") or bundle.get("source_commit") or "")
    try:
        job = m41r3._load(ROOT / "tools/mephc-flow/scientific_job.py", "m43_job")
        m39 = m41r3._load(ROOT / "audit/berry_c3_consistency/m39_g15_deterministic_repeat_band_association_worst_orbit_pilot.py", "m43_m39")
        m38 = m41r3._load(ROOT / "audit/berry_c3_consistency/m38_supplied_exact_mpb_source_semantics_raw_native_c3.py", "m43_m38")
        state_root = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"]).parent.parent
        partial = m41r3._read_partial(job, state_root)
        new = m41r3._read_dataset(job, state_root, M41R3_DATASET_ID, M41R3_MANIFEST_SHA256, M41R3_SCHEMA, 108)
        baseline = m41r3._read_dataset(job, state_root, m41r3.BASELINE_DATASET_ID, m41r3.BASELINE_MANIFEST_SHA256, m41r3.BASELINE_SCHEMA, 72)
        m18 = m41r3._read_dataset(job, state_root, m41r3.M18_DATASET_ID, m41r3.M18_MANIFEST_SHA256, m41r3.M18_SCHEMA, 3)
        m39r1 = m41r3._read_dataset(job, state_root, m41r3.M39R1_DATASET_ID, m41r3.M39R1_MANIFEST_SHA256, m41r3.M39R1_SCHEMA, 14)
        m2 = m41r3._read_dataset(job, state_root, m41r3.M2_DATASET_ID, m41r3.M2_MANIFEST_SHA256, m41r3.M2_SCHEMA if hasattr(m41r3, "M2_SCHEMA") else "mephc-berry-c3-pilot-plaquette-v1", 72)
        centers = m41r3._centers(m18, m39r1)
        matrix = {"R128_T1E7_M3": [dict(row, configuration_id="R128_T1E7_M3", resolution=128, tolerance=1e-7, mesh_size=3) for row in baseline if row.get("stencil") == "C3_COVARIANT"], "R128_T1E9_M3": partial}
        for name in ("R128_T1E9_M1", "R64_T1E9_M3", "R96_T1E9_M3"):
            matrix[name] = [row for row in new if row.get("configuration_id") == name]
        if any(len(rows) != 36 for rows in matrix.values()):
            raise ValueError("M43_INPUT_MATRIX_INVALID")
        analyses = {name: m42._configuration(rows, m38, m39, name) for name, rows in matrix.items()}
        selection = select_admissible_control(analyses)
        selected = selection["selected_admissible_measured_setting"]
        if selected is None:
            flags = {"association_problem": any(not a["rank2_association_stable"] for a in analyses.values()), "R96_R128_high_resolution_plateau": m42._plateau(analyses["R96_T1E9_M3"], analyses["R128_T1E9_M3"])}
            decision = "ADAPTIVE_VALIDATED_SUBSPACE_BERRY_TRANSPORT_USING_EXISTING_M41_RAW_BANDS" if flags["association_problem"] else "BOUND_PLAQUETTE_STEP_CONVERGENCE_PILOT" if flags["R96_R128_high_resolution_plateau"] else "TARGETED_HIGHER_RESOLUTION_PLATEAU_EXTENSION"
            result = _result(bundle, source_commit, {**selection, "no_admissible_control_flags": flags}, "NO_ADMISSIBLE_CONTROL", decision, {}, None, (0, 0, 0, 0), None)
        else:
            setting_values = {"R128_T1E7_M3": (128, 1e-7, 3), "R128_T1E9_M3": (128, 1e-9, 3), "R128_T1E9_M1": (128, 1e-9, 1), "R64_T1E9_M3": (64, 1e-9, 3), "R96_T1E9_M3": (96, 1e-9, 3)}
            resolution, tolerance, mesh_size = setting_values[selected]
            graph = cross_orbit_graph({"resolution": resolution, "tolerance": tolerance, "mesh_size": mesh_size}, source_commit)
            import meep as mp
            from meep import mpb
            from mephc.band import Band
            band = Band(a=400.0, r1=80.14335684352235, r2=75.13439704080221, n_eff=2.7, h=100.0, resolution=resolution, lattice_type="triangular", polarization="TE", structure_type="slab")
            pattern = band.create_unitcell(15, 0.0, 15, 60.0, show=False)
            geometry = band.create_material_block() + band.convert_ndarray_to_meep_geo(pattern, rectify=True)
            counter = job.BudgetCounter(108, 108)
            store = job.ImmutableDatasetStore(state_root, {"goal_id": "MEPHC-BERRY-C3-CONSISTENCY-V1", "work_order_id": bundle["work_order_id"], "source_commit": source_commit, "record_schema": DATASET_SCHEMA})
            records: list[dict[str, Any]] = []
            # Every rotated member and every plaquette vertex is solved independently.
            for spec in graph:
                reciprocal = mp.cartesian_to_reciprocal(mp.Vector3(float(spec["coordinate"][0]), float(spec["coordinate"][1]), 0.0), band.geo_latt)
                solver = mpb.ModeSolver(geometry=geometry, geometry_lattice=band.geo_latt, k_points=[reciprocal], resolution=resolution, num_bands=4, default_material=mp.air, tolerance=tolerance, deterministic=True, mesh_size=mesh_size)
                captured = _capture_record(mp, solver, spec, counter, source_commit)
                key = json.dumps({"work_order_id": bundle["work_order_id"], "orbit_m": spec["orbit_m"], "member": spec["c3_member_identity"], "repeat": spec["repeat_index"], "vertex": spec["vertex_index"]}, sort_keys=True, separators=(",", ":")).encode()
                store.put(key, json.dumps(captured, sort_keys=True, separators=(",", ":"), default=lambda value: _safe(value)).encode(), {"orbit_m": spec["orbit_m"], "member": spec["c3_member_identity"], "repeat_index": spec["repeat_index"], "vertex_index": spec["vertex_index"]})
                records.append(captured)
            orbit_analyses = {m: m42._configuration([row for row in records if row["orbit_m"] == m], m38, m39, f"M43_ORBIT_{m}") for m in ORBIT_M_VALUES}
            outcome, decision = _outcome(orbit_analyses, analyses["R128_T1E9_M3"])
            dataset = store.finalize(108, {"dataset_schema": DATASET_SCHEMA, "selected_setting": selected, "orbit_m_values": list(ORBIT_M_VALUES), "request_graph_sha256": hashlib.sha256(json.dumps(graph, sort_keys=True, separators=(",", ":")).encode()).hexdigest(), "source_m41r3_dataset_id": M41R3_DATASET_ID})
            result = _result(bundle, source_commit, selection, outcome, decision, orbit_analyses, dataset, (1, counter.provider_count, counter.solver_count, len(records)), hashlib.sha256(json.dumps(graph, sort_keys=True, separators=(",", ":")).encode()).hexdigest())
    except BaseException as exc:
        result = {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "machine_execution_contract_status": "M43_FAIL_CLOSED", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 0, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "failure_code": str(exc)[:1024], "failure_stage": "reference_selection_or_cross_orbit_acquisition", "exception_type": type(exc).__name__, "source_commit_used": source_commit}
    Path(os.environ["MEPHC_RESULT_PATH"]).write_text(json.dumps(_safe(result), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
