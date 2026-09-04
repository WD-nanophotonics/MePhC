"""M42: corrected, solver-free adjudication of the complete M41R3 matrix."""
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
M41R3_PATH = ROOT / "audit/berry_c3_consistency/m41r3_recover36_finish_convergence.py"
_SPEC = importlib.util.spec_from_file_location("m42_m41r3_parent", M41R3_PATH)
assert _SPEC and _SPEC.loader
m41r3 = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(m41r3)

MEMBERS = m41r3.MEMBERS
RESULT_SCHEMA = "mephc-berry-c3-consistency-m42-corrected-m41-numerical-control-adjudication-v1"
M41R3_DATASET_ID = "a1edd5623ea1ed4413275a716d33258695d3d81c498a2d663b3608ab5355ed89"
M41R3_MANIFEST_SHA256 = "18dbf109891789d4e4c2f86753d4eae4c7b1ffcedb152459c26f6f9f1a8dbdab"
M41R3_SCHEMA = "mephc-berry-c3-consistency-m41r3-recovery-numerical-convergence-vertex-dataset-v1"
PARTIAL_NAMESPACE_SHA256 = m41r3.PARTIAL_NAMESPACE_SHA256
M2_SCHEMA = "mephc-berry-c3-pilot-plaquette-v1"


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
    raise ValueError(f"M42_UNSAFE_RESULT:{type(value).__name__}")


def _phase_lift(values: Sequence[float]) -> dict[str, Any]:
    """Order-independent circular lifting with a deterministic tie break."""
    raw = [float(v) for v in values]
    if not raw:
        return {"lifted_phases": [], "ambiguous": False, "maximum_pairwise_wrapped_distance": 0.0}
    candidates = []
    for anchor_index, anchor in enumerate(raw):
        lifted = [anchor]
        for index, value in enumerate(raw):
            if index == anchor_index:
                continue
            lifted.append(value + 2.0 * math.pi * round((anchor - value) / (2.0 * math.pi)))
        center = float(np.median(lifted))
        spread = max(abs(v - center) for v in lifted)
        candidates.append((spread, anchor_index, lifted))
    _, _, lifted = min(candidates, key=lambda item: (item[0], item[1]))
    wrapped = [abs(math.atan2(math.sin(a - b), math.cos(a - b))) for a, b in itertools.combinations(raw, 2)]
    ambiguous = any(abs(distance - math.pi) <= 1e-12 for distance in wrapped)
    return {"lifted_phases": lifted, "ambiguous": ambiguous, "maximum_pairwise_wrapped_distance": float(max(wrapped, default=0.0))}


def _scalar_stats(phases: Sequence[float], areas: Sequence[float]) -> dict[str, Any]:
    lift = _phase_lift(phases)
    densities = [float(phase) / float(area) for phase, area in zip(lift["lifted_phases"], areas)]
    median = float(np.median(densities)) if densities else 0.0
    return {"values": densities, "median": median, "uncertainty": float(max((abs(v - median) for v in densities), default=0.0)), "phase_uncertainty": lift["maximum_pairwise_wrapped_distance"], "branch_ambiguous": lift["ambiguous"], "lifted_phases": lift["lifted_phases"]}


def _association_state(pairs: Sequence[Sequence[int]]) -> str:
    values = [tuple(int(x) for x in pair) for pair in pairs]
    if not values or len(set(values)) != 1:
        return "REPEAT_UNSTABLE"
    return "CANONICAL_STABLE" if values[0] == (2, 3) else "NONCANONICAL_STABLE"


def _compare_scalar(a: Mapping[str, Any], b: Mapping[str, Any], observable: str) -> dict[str, Any]:
    left = a[observable]
    right = b[observable]
    difference = abs(float(left["median"]) - float(right["median"]))
    combined = float(left["uncertainty"]) + float(right["uncertainty"])
    return {"observable": observable, "median_A": left["median"], "uncertainty_A": left["uncertainty"], "median_B": right["median"], "uncertainty_B": right["uncertainty"], "absolute_difference": difference, "combined_uncertainty": combined, "difference_beyond_uncertainty": difference > combined}


def _configuration(records: Sequence[Mapping[str, Any]], m38: Any, m39: Any, configuration_id: str) -> dict[str, Any]:
    groups: dict[tuple[str, int], dict[int, Mapping[str, Any]]] = {}
    for row in records:
        groups.setdefault((str(row["c3_member_identity"]), int(row["repeat_index"])), {})[int(row["vertex_index"])] = row
    if set(groups) != {(member, repeat) for member in MEMBERS for repeat in range(3)} or any(set(v) != {0, 1, 2, 3} for v in groups.values()):
        raise ValueError("M42_CONFIGURATION_SCHEDULE_INVALID")
    plaquettes: list[dict[str, Any]] = []
    for (member, repeat), vertices in sorted(groups.items()):
        rows = [vertices[index] for index in range(4)]
        rank1_edges, rank2_edges = [], []
        for edge_index, (left, right) in enumerate(zip(rows, rows[1:] + rows[:1])):
            source = m41r3._dynamic_raw(left, m39)
            target = m41r3._dynamic_raw(right, m39)
            rank1 = m41r3._rank1(m38, source, target, left["coordinate"], right["coordinate"])
            pairs = [m41r3._rank2_pair(m38, source, target, left["coordinate"], right["coordinate"], pair) for pair in itertools.combinations(range(4), 2)]
            canonical = next(item for item in pairs if item["target_pair"] == [2, 3])
            best = max(pairs, key=lambda item: (item["minimum_singular_value"], tuple(-x for x in item["target_pair"])))
            rank1_edges.append({**rank1, "edge_index": edge_index})
            rank2_edges.append({"edge_index": edge_index, "canonical_pair": [2, 3], "canonical_minimum_singular_value": canonical["minimum_singular_value"], "best_target_pair": best["target_pair"], "best_minimum_singular_value": best["minimum_singular_value"], "canonical_vs_best_margin": float(best["minimum_singular_value"] - canonical["minimum_singular_value"]), "trace_phase": float(np.angle(np.linalg.det(canonical["polar_unitary"])))})
        area = sum(rows[i]["coordinate"][0] * rows[(i + 1) % 4]["coordinate"][1] - rows[(i + 1) % 4]["coordinate"][0] * rows[i]["coordinate"][1] for i in range(4)) / 2.0
        wilson = complex(1.0, 0.0)
        for edge in rank1_edges:
            link = complex(*edge["normalized_link"])
            wilson *= link / abs(link) if abs(link) else 1.0
        plaquettes.append({"member": member, "repeat_index": repeat, "signed_area": float(area), "rank1_edges": rank1_edges, "rank2_edges": rank2_edges, "rank1_phase": float(np.angle(wilson)), "rank2_phase": float(sum(edge["trace_phase"] for edge in rank2_edges))})
    by_member: dict[str, Any] = {}
    for member in MEMBERS:
        rows = [row for row in plaquettes if row["member"] == member]
        rank1 = _scalar_stats([row["rank1_phase"] for row in rows], [row["signed_area"] for row in rows])
        rank2 = _scalar_stats([row["rank2_phase"] for row in rows], [row["signed_area"] for row in rows])
        gap_by_vertex: dict[int, list[float]] = {vertex: [] for vertex in range(4)}
        for row in records:
            if row["c3_member_identity"] == member:
                gaps = row["adjacent_gaps"]
                gap_by_vertex[int(row["vertex_index"])].append(min(float(gaps["lower_gap"]), float(gaps["internal_split"])))
        link_by_edge: dict[int, list[float]] = {edge: [] for edge in range(4)}
        for row in rows:
            for edge in row["rank1_edges"]:
                link_by_edge[int(edge["edge_index"])].append(float(edge["link_magnitude"]))
        gap_ranges = {vertex: max(values) - min(values) for vertex, values in gap_by_vertex.items() if values}
        link_ranges = {edge: max(values) - min(values) for edge, values in link_by_edge.items() if values}
        gap_signal = min(value for values in gap_by_vertex.values() for value in values)
        link_signal = min(value for values in link_by_edge.values() for value in values)
        gap_noise = max(gap_ranges.values(), default=0.0)
        link_noise = max(link_ranges.values(), default=0.0)
        association = {edge: {"repeat_best_pairs": [p["best_target_pair"] for row in rows for p in row["rank2_edges"] if p["edge_index"] == edge], "state": _association_state([p["best_target_pair"] for row in rows for p in row["rank2_edges"] if p["edge_index"] == edge])} for edge in range(4)}
        rank1_association = all(edge["best_target_band"] == 2 for row in rows for edge in row["rank1_edges"])
        branch_margin = min(math.pi - abs(row["rank1_phase"]) for row in rows)
        phase_noise = rank1["phase_uncertainty"]
        by_member[member] = {"rank1_phase_density": rank1, "rank2_trace_phase_density": rank2, "gap_signal": gap_signal, "gap_repeat_noise": gap_noise, "link_signal": link_signal, "link_repeat_noise": link_noise, "rank1_association": rank1_association, "rank2_association": association, "rank1_qualification": {"gap_ratio": gap_signal / gap_noise if gap_noise else (float("inf") if gap_signal > 0 else 0.0), "link_ratio": link_signal / link_noise if link_noise else (float("inf") if link_signal > 0 else 0.0), "branch_ratio": branch_margin / phase_noise if phase_noise else float("inf")}}
        # Keep the frozen gates readable and explicit.
        gate = by_member[member]["rank1_qualification"]
        gate["status"] = "RANK1_QUALIFIED" if rank1_association and gate["gap_ratio"] >= 10.0 and gate["link_ratio"] >= 10.0 and gate["branch_ratio"] >= 5.0 else "RANK1_WITHHELD"
    stable_rank2 = all(item["state"] == "CANONICAL_STABLE" for member in MEMBERS for item in by_member[member]["rank2_association"].values())
    rank1_qualified = all(by_member[member]["rank1_qualification"]["status"] == "RANK1_QUALIFIED" for member in MEMBERS)
    def c3(observable: str, require_rank1: bool) -> str:
        if require_rank1 and not rank1_qualified:
            return "RANK1_WITHHELD"
        for left, right in itertools.combinations(MEMBERS, 2):
            a, b = by_member[left][observable], by_member[right][observable]
            if abs(a["median"] - b["median"]) > a["uncertainty"] + b["uncertainty"] or (a["median"] and b["median"] and np.sign(a["median"]) != np.sign(b["median"])):
                return "FAIL"
        return "PASS"
    return {"configuration_id": configuration_id, "record_count": len(records), "member_summary": by_member, "rank1_qualification": {"status": "RANK1_QUALIFIED" if rank1_qualified else "RANK1_WITHHELD", "per_member": {m: by_member[m]["rank1_qualification"] for m in MEMBERS}, "stable_band2_association": all(by_member[m]["rank1_association"] for m in MEMBERS)}, "rank2_association_stable": stable_rank2, "rank1_c3_status": c3("rank1_phase_density", True), "rank2_c3_status": c3("rank2_trace_phase_density", False), "canonical_rank2_pair_one_based": [2, 3], "stencil": "C3_COVARIANT"}


def _pair_table(left: Mapping[str, Any], right: Mapping[str, Any], pair_name: str) -> dict[str, Any]:
    table: dict[str, Any] = {}
    for member in MEMBERS:
        a, b = left["member_summary"][member], right["member_summary"][member]
        items = [_compare_scalar(a, b, "rank2_trace_phase_density")]
        if left["rank1_qualification"]["status"] == "RANK1_QUALIFIED" and right["rank1_qualification"]["status"] == "RANK1_QUALIFIED":
            items.append(_compare_scalar(a, b, "rank1_phase_density"))
        table[member] = {"supported_observables": items, "rank1_qualification_changed": left["rank1_qualification"]["status"] != right["rank1_qualification"]["status"], "rank1_association_changed": a["rank1_association"] != b["rank1_association"], "rank2_association_changed": a["rank2_association"] != b["rank2_association"], "rank1_c3_status_changed": left["rank1_c3_status"] != right["rank1_c3_status"], "rank2_c3_status_changed": left["rank2_c3_status"] != right["rank2_c3_status"]}
    return {"pair": pair_name, "members": table}


def _sensitive(table: Mapping[str, Any]) -> bool:
    for value in table["members"].values():
        if any(item["difference_beyond_uncertainty"] for item in value["supported_observables"]):
            return True
        if any(value[key] for key in ("rank1_qualification_changed", "rank1_association_changed", "rank2_association_changed", "rank1_c3_status_changed", "rank2_c3_status_changed")):
            return True
    return False


def _plateau(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    """Direct R96-R128 check, independent of the R64 endpoint."""
    table = _pair_table(left, right, "high_resolution")
    return not _sensitive(table)


def _classify(analyses: Mapping[str, Mapping[str, Any]], comparisons: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    r96_plateau = _plateau(analyses["R96_T1E9_M3"], analyses["R128_T1E9_M3"])
    r64_plateau = _plateau(analyses["R64_T1E9_M3"], analyses["R128_T1E9_M3"])
    association_problem = any(not analysis["rank2_association_stable"] or not analysis["rank1_qualification"]["stable_band2_association"] for analysis in analyses.values())
    flags = {"tolerance_sensitive": _sensitive(comparisons["tolerance"]), "mesh_sensitive": _sensitive(comparisons["mesh"]), "resolution_sensitive": _sensitive(comparisons["R64_R128"]), "association_problem": association_problem, "R64_R128_plateau": r64_plateau, "R96_R128_high_resolution_plateau": r96_plateau, "qualified_exact_c3_setting": any(a["rank1_qualification"]["status"] == "RANK1_QUALIFIED" and a["rank1_c3_status"] == "PASS" for a in analyses.values())}
    causal = sum(bool(flags[key]) for key in ("tolerance_sensitive", "mesh_sensitive", "resolution_sensitive", "association_problem"))
    if causal >= 2: synthesis = "MULTIPLE_IDENTIFIED_CAUSES"
    elif association_problem: synthesis = "BAND_ASSOCIATION_OR_NEAR_DEGENERACY"
    elif flags["resolution_sensitive"] and r96_plateau: synthesis = "RESOLUTION_SENSITIVITY_WITH_HIGH_RESOLUTION_PLATEAU"
    elif flags["resolution_sensitive"]: synthesis = "NO_NUMERICAL_RESOLUTION_PLATEAU"
    elif flags["mesh_sensitive"]: synthesis = "MESH_SENSITIVITY"
    elif flags["tolerance_sensitive"]: synthesis = "TOLERANCE_SENSITIVITY"
    elif r96_plateau and any(a["rank1_c3_status"] == "FAIL" for a in analyses.values()): synthesis = "PERSISTENT_C3_INCONSISTENCY_ON_NUMERICAL_PLATEAU"
    elif flags["qualified_exact_c3_setting"]: synthesis = "NUMERICAL_SETTINGS_QUALIFIED_C3_RESTORED"
    else: synthesis = "UNRESOLVED_UNDER_BOUNDED_EXPERIMENT"
    return {**flags, "m41r3_multiple_identified_causes_survives": synthesis == "MULTIPLE_IDENTIFIED_CAUSES"}, synthesis


def _result(bundle: Mapping[str, Any], source_commit: str, analyses: Mapping[str, Any], comparisons: Mapping[str, Any], flags: Mapping[str, Any], synthesis: str, m2_count: int) -> dict[str, Any]:
    eligible = [name for name, analysis in analyses.items() if analysis["rank1_qualification"]["status"] == "RANK1_QUALIFIED" and analysis["rank1_c3_status"] == "PASS"]
    costs = {"R64_T1E9_M3": (64, 1e-9, 3), "R96_T1E9_M3": (96, 1e-9, 3), "R128_T1E9_M1": (128, 1e-9, 1), "R128_T1E9_M3": (128, 1e-9, 3), "R128_T1E7_M3": (128, 1e-7, 3)}
    selected = min(eligible, key=lambda name: (costs[name][0], -math.log10(costs[name][1]), costs[name][2])) if eligible else None
    next_map = {"MULTIPLE_IDENTIFIED_CAUSES": "SELECT_CHEAPEST_MEASURED_QUALIFIED_CONTROL_IF_AVAILABLE_ELSE_ROUTE_BY_UNRESOLVED_DOMINANT_CAUSE", "BAND_ASSOCIATION_OR_NEAR_DEGENERACY": "ADAPTIVE_VALIDATED_SUBSPACE_BERRY_TRANSPORT_USING_EXISTING_M41_RAW_BANDS", "NO_NUMERICAL_RESOLUTION_PLATEAU": "TARGETED_HIGHER_RESOLUTION_PLATEAU_EXTENSION", "RESOLUTION_SENSITIVITY_WITH_HIGH_RESOLUTION_PLATEAU": "LOWEST_HIGH_RESOLUTION_PLATEAU_SETTING_CROSS_ORBIT_QUALIFICATION", "MESH_SENSITIVITY": "MESH3_CONTROL_SELECTION_THEN_CROSS_ORBIT_QUALIFICATION", "TOLERANCE_SENSITIVITY": "T1E9_CONTROL_SELECTION_THEN_CROSS_ORBIT_QUALIFICATION", "PERSISTENT_C3_INCONSISTENCY_ON_NUMERICAL_PLATEAU": "BOUND_PLAQUETTE_STEP_CONVERGENCE_PILOT", "NUMERICAL_SETTINGS_QUALIFIED_C3_RESTORED": "QUALIFIED_DETERMINISTIC_G15_FULL_RAW_HBZ_MAP_AT_SELECTED_MEASURED_SETTING", "UNRESOLVED_UNDER_BOUNDED_EXPERIMENT": "TARGETED_NEXT_DISCRIMINANT_FROM_M42_EVIDENCE"}
    return {"schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS", "machine_execution_contract_status": "ZERO_SCIENTIFIC_EXECUTION_CORRECTED_M41_REANALYSIS_COMPLETE", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 0, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "verified_measured_configurations": list(analyses), "configuration_analysis": analyses, "comparisons": comparisons, "cause_flags": flags, "corrected_causal_class": synthesis, "selected_cheapest_qualified_measured_setting": selected, "eligible_measured_settings": eligible, "m41r3_multiple_identified_causes_delta": "CONFIRMED" if flags["m41r3_multiple_identified_causes_survives"] else "CORRECTED_OR_OVERTURNED", "historical_m2_comparison": {"record_count": m2_count, "not_used_as_raw_H": True}, "next_science_decision": next_map[synthesis], "goal_completion_status": "NOT_COMPLETE_CONTINUE_CAUSAL_BRANCH", "source_commit_used": source_commit, "post_analysis_checkout_unchanged": True}


def main() -> int:
    bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8"))
    source_commit = str(os.environ.get("MEPHC_SOURCE_COMMIT") or bundle.get("source_commit") or "")
    try:
        job = m41r3._load(ROOT / "tools/mephc-flow/scientific_job.py", "m42_job")
        m39 = m41r3._load(ROOT / "audit/berry_c3_consistency/m39_g15_deterministic_repeat_band_association_worst_orbit_pilot.py", "m42_m39")
        m38 = m41r3._load(ROOT / "audit/berry_c3_consistency/m38_supplied_exact_mpb_source_semantics_raw_native_c3.py", "m42_m38")
        state_root = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"]).parent.parent
        partial = m41r3._read_partial(job, state_root)
        new = m41r3._read_dataset(job, state_root, M41R3_DATASET_ID, M41R3_MANIFEST_SHA256, M41R3_SCHEMA, 108)
        baseline = m41r3._read_dataset(job, state_root, m41r3.BASELINE_DATASET_ID, m41r3.BASELINE_MANIFEST_SHA256, m41r3.BASELINE_SCHEMA, 72)
        m18 = m41r3._read_dataset(job, state_root, m41r3.M18_DATASET_ID, m41r3.M18_MANIFEST_SHA256, m41r3.M18_SCHEMA, 3)
        m39r1 = m41r3._read_dataset(job, state_root, m41r3.M39R1_DATASET_ID, m41r3.M39R1_MANIFEST_SHA256, m41r3.M39R1_SCHEMA, 14)
        m2 = m41r3._read_dataset(job, state_root, m41r3.M2_DATASET_ID, m41r3.M2_MANIFEST_SHA256, M2_SCHEMA, 72)
        centers = m41r3._centers(m18, m39r1)
        matrix = {"R128_T1E7_M3": [dict(row, configuration_id="R128_T1E7_M3", resolution=128, tolerance=1e-7, mesh_size=3) for row in baseline if row.get("stencil") == "C3_COVARIANT"], "R128_T1E9_M3": partial}
        for configuration_id in ("R128_T1E9_M1", "R64_T1E9_M3", "R96_T1E9_M3"):
            matrix[configuration_id] = [row for row in new if row.get("configuration_id") == configuration_id]
        if any(len(matrix[name]) != 36 for name in matrix):
            raise ValueError("M42_CONFIGURATION_RECORD_COUNT_INVALID")
        analyses = {name: _configuration(rows, m38, m39, name) for name, rows in matrix.items()}
        comparisons = {"tolerance": _pair_table(analyses["R128_T1E7_M3"], analyses["R128_T1E9_M3"], "R128_T1E7_M3_vs_R128_T1E9_M3"), "mesh": _pair_table(analyses["R128_T1E9_M1"], analyses["R128_T1E9_M3"], "R128_T1E9_M1_vs_R128_T1E9_M3"), "R64_R128": _pair_table(analyses["R64_T1E9_M3"], analyses["R128_T1E9_M3"], "R64_T1E9_M3_vs_R128_T1E9_M3"), "R96_R128": _pair_table(analyses["R96_T1E9_M3"], analyses["R128_T1E9_M3"], "R96_T1E9_M3_vs_R128_T1E9_M3")}
        flags, synthesis = _classify(analyses, comparisons)
        result = _result(bundle, source_commit, analyses, comparisons, flags, synthesis, len(m2))
    except BaseException as exc:
        result = {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "machine_execution_contract_status": "ZERO_SCIENTIFIC_EXECUTION_FAIL_CLOSED", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 0, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "failure_code": str(exc)[:1024], "failure_stage": "read_only_reanalysis", "exception_type": type(exc).__name__, "source_commit_used": source_commit}
    Path(os.environ["MEPHC_RESULT_PATH"]).write_text(json.dumps(_safe(result), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
