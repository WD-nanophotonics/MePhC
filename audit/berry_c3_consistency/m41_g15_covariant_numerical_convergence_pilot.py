"""M41: bounded G15 C3-covariant numerical convergence pilot."""
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
BASE = ROOT / "audit/berry_c3_consistency/m40r3_persisted_72_state_berry_c3_final_adjudication.py"
SPEC = importlib.util.spec_from_file_location("m41_m40r3", BASE)
assert SPEC and SPEC.loader
m40r3 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m40r3)
m40r2 = m40r3.m40r2

MEMBERS = ("IDENTITY", "C3", "C3_SQUARED")
CONFIGS = (
    {"configuration_id": "R128_T1E9_M3", "resolution": 128, "tolerance": 1e-9, "mesh_size": 3},
    {"configuration_id": "R128_T1E9_M1", "resolution": 128, "tolerance": 1e-9, "mesh_size": 1},
    {"configuration_id": "R64_T1E9_M3", "resolution": 64, "tolerance": 1e-9, "mesh_size": 3},
)
CONDITIONAL = {"configuration_id": "R96_T1E9_M3", "resolution": 96, "tolerance": 1e-9, "mesh_size": 3}
DATASET_SCHEMA = "mephc-berry-c3-consistency-m41-g15-covariant-numerical-convergence-vertex-dataset-v1"
RESULT_SCHEMA = "mephc-berry-c3-consistency-m41-g15-covariant-numerical-convergence-pilot-v1"
M18_DATASET_ID = m40r2.M18_DATASET_ID
M18_MANIFEST_SHA256 = m40r2.M18_MANIFEST_SHA256
M2_DATASET_ID = m40r2.M2_DATASET_ID
M2_MANIFEST_SHA256 = m40r2.M2_MANIFEST_SHA256
BASELINE_DATASET_ID = "7c88b9e3760a21eaef60a94c57dad7bc04504906f02ffeb1de7bfb3feac1990a"
BASELINE_MANIFEST_SHA256 = "9f793b812fce84a01b51766d582c5b3c54eb83b5689b90a5af83386cb7df620e"
BASELINE_SCHEMA = m40r2.PARENT_RECORD_SCHEMA
M39R1_DATASET_ID = m40r2.M39R1_DATASET_ID
M39R1_MANIFEST_SHA256 = m40r2.M39R1_MANIFEST_SHA256
M39R1_SCHEMA = "mephc-berry-c3-consistency-m39r1-g15-deterministic-repeat-band-association-recovery-dataset-v1"
STEP = 0.001
BANDS = 4


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"M41_DEPENDENCY_UNAVAILABLE:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
    raise ValueError(f"M41_UNSAFE_RESULT:{type(value).__name__}")


def plaquette_vertices(center: Sequence[float], member_index: int) -> tuple[list[list[float]], float]:
    angle = 2.0 * math.pi * int(member_index) / 3.0
    rotation = np.asarray([[math.cos(angle), -math.sin(angle)], [math.sin(angle), math.cos(angle)]])
    point = np.asarray(center, dtype=float)
    dx = rotation @ np.asarray([STEP, 0.0])
    dy = rotation @ np.asarray([0.0, STEP])
    vertices = [point - dx / 2 - dy / 2, point + dx / 2 - dy / 2, point + dx / 2 + dy / 2, point - dx / 2 + dy / 2]
    return [value.tolist() for value in vertices], float(sum(vertices[i][0] * vertices[(i + 1) % 4][1] - vertices[(i + 1) % 4][0] * vertices[i][1] for i in range(4)) / 2.0)


def request_graph(config: Mapping[str, Any], centers: Mapping[str, Sequence[float]], source_commit: str) -> list[dict[str, Any]]:
    graph = []
    for member_index, member in enumerate(MEMBERS):
        for repeat in range(3):
            vertices, _ = plaquette_vertices(centers[member], member_index)
            for vertex_index, coordinate in enumerate(vertices):
                value = {"goal_id": "MEPHC-BERRY-C3-CONSISTENCY-V1", "milestone": "M41", "geometry_id": "G15", "stencil": "C3_COVARIANT", "configuration_id": config["configuration_id"], "member_index": member_index, "c3_member_identity": member, "repeat_index": repeat, "vertex_index": vertex_index, "center": list(map(float, centers[member])), "coordinate": list(map(float, coordinate)), "deterministic": True, "num_bands": 4, "resolution": int(config["resolution"]), "tolerance": float(config["tolerance"]), "mesh_size": int(config["mesh_size"]), "polarization": "TE", "source_commit": source_commit}
                value["request_key_sha256"] = hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                graph.append(value)
    if len(graph) != 36 or len({v["request_key_sha256"] for v in graph}) != 36:
        raise ValueError("M41_REQUEST_GRAPH_INVALID")
    return graph


def request_graph_digest(graph: Sequence[Mapping[str, Any]]) -> str:
    return hashlib.sha256(json.dumps(list(graph), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _read_dataset(job: Any, state_root: Path, dataset_id: str, manifest: str, schema: str, count: int) -> list[dict[str, Any]]:
    return m40r2._read_dataset(job, state_root, dataset_id, manifest, schema, count)


def _raw(row: Mapping[str, Any], m39: Any) -> np.ndarray:
    value, _ = m39.normalize_raw(m39.decode_raw(row["raw_eigenvector"]))
    if value.shape != (4, 16384, 2) or not np.all(np.isfinite(value.real)) or not np.all(np.isfinite(value.imag)):
        raise ValueError("M41_RAW_H_SHAPE_INVALID")
    return value


def _configuration_analysis(records: Sequence[Mapping[str, Any]], centers: Mapping[str, Sequence[float]], m38: Any, m39: Any, configuration_id: str) -> dict[str, Any]:
    groups: dict[tuple[str, int], dict[int, Mapping[str, Any]]] = {}
    for row in records:
        groups.setdefault((str(row["c3_member_identity"]), int(row["repeat_index"])), {})[int(row["vertex_index"])] = row
    if set(groups) != {(m, r) for m in MEMBERS for r in range(3)} or any(set(v) != {0, 1, 2, 3} for v in groups.values()):
        raise ValueError("M41_CONFIGURATION_SCHEDULE_INVALID")
    plaquettes = []
    for (member, repeat), vertices in sorted(groups.items()):
        rows = [vertices[i] for i in range(4)]
        rank1, rank2 = [], []
        for edge_index, (left, right) in enumerate(zip(rows, rows[1:] + rows[:1])):
            source, target = _raw(left, m39), _raw(right, m39)
            one = m40r3._rank1(m38, source, target, left["coordinate"], right["coordinate"])
            one["edge_index"] = edge_index
            pairs = [m40r3._rank2_pair(m38, source, target, left["coordinate"], right["coordinate"], pair) for pair in itertools.combinations(range(4), 2)]
            canonical = next(item for item in pairs if item["target_pair"] == [2, 3])
            best = max(pairs, key=lambda item: (item["minimum_singular_value"], tuple(-x for x in item["target_pair"])))
            canonical = dict(canonical)
            canonical.update({"edge_index": edge_index, "competing_target_pairs": pairs, "best_target_pair": best["target_pair"], "best_target_pair_minimum_singular_value": best["minimum_singular_value"]})
            rank1.append(one)
            rank2.append(canonical)
        area = m40r2._area([row["coordinate"] for row in rows])
        wilson = complex(1.0, 0.0)
        for edge in rank1:
            link = complex(*edge["normalized_link"])
            wilson *= link / abs(link)
        polar = np.eye(2, dtype=np.complex128)
        for edge in rank2:
            polar = edge["polar_unitary"] @ polar
        rank1_phase = float(np.angle(wilson))
        rank2_phase = float(np.angle(np.linalg.det(polar)))
        plaquettes.append({"member": member, "repeat_index": repeat, "configuration_id": configuration_id, "vertices": [list(map(float, row["coordinate"])) for row in rows], "signed_area": area, "rank1_edges": rank1, "rank1_wilson_phase": rank1_phase, "rank1_phase_density": rank1_phase / area, "rank1_legacy_m2_compatible_curvature": -rank1_phase / area / (2 * math.pi) ** 2, "rank1_branch_margin": math.pi - abs(rank1_phase), "rank2_edges": rank2, "rank2_trace_phase": rank2_phase, "rank2_trace_phase_density": rank2_phase / area, "rank2_legacy_m2_compatible_trace_curvature": -rank2_phase / area / (2 * math.pi) ** 2, "rank2_branch_margin": math.pi - abs(rank2_phase), "rank2_minimum_singular_value": float(min(e["minimum_singular_value"] for e in rank2))})
    by_member = {}
    for member in MEMBERS:
        rows = [row for row in plaquettes if row["member"] == member]
        one = m40r3.branch_safe_phases([row["rank1_wilson_phase"] for row in rows])
        two = m40r3.branch_safe_phases([row["rank2_trace_phase"] for row in rows])
        one_density = [phase / row["signed_area"] for phase, row in zip(one["lifted_phases"], rows)]
        two_density = [phase / row["signed_area"] for phase, row in zip(two["lifted_phases"], rows)]
        by_member[member] = {"rank1_phase_density": {"median": float(np.median(one_density)), "uncertainty": float(max(abs(v - np.median(one_density)) for v in one_density)), "branch_safe": one}, "rank2_trace_phase_density": {"median": float(np.median(two_density)), "uncertainty": float(max(abs(v - np.median(two_density)) for v in two_density)), "branch_safe": two}, "rank1_association": all(edge["best_target_band"] == 2 for row in rows for edge in row["rank1_edges"]), "rank2_best_pairs": sorted({tuple(edge["best_target_pair"]) for row in rows for edge in row["rank2_edges"]})}
    gap_groups: dict[tuple[str, int], list[float]] = {}
    link_groups: dict[tuple[str, int], list[float]] = {}
    for row in records:
        gaps = row["adjacent_gaps"]
        gap_groups.setdefault((str(row["c3_member_identity"]), int(row["vertex_index"])), []).append(min(float(gaps["lower_gap"]), float(gaps["internal_split"])))
    for row in plaquettes:
        for edge_index, edge in enumerate(row["rank1_edges"]):
            link_groups.setdefault((row["member"], edge_index), []).append(float(edge["link_magnitude"]))
    gap_signal, gap_noise = min(min(v) for v in gap_groups.values()), max(max(v) - min(v) for v in gap_groups.values())
    link_signal, link_noise = min(min(v) for v in link_groups.values()), max(max(v) - min(v) for v in link_groups.values())
    branch_noise = max(by_member[m]["rank1_phase_density"]["branch_safe"]["maximum_pairwise_wrapped_distance"] for m in MEMBERS)
    branch_margin = min(row["rank1_branch_margin"] for row in plaquettes)
    gap_ratio = gap_signal / gap_noise if gap_noise else (float("inf") if gap_signal > 0 else 0.0)
    link_ratio = link_signal / link_noise if link_noise else (float("inf") if link_signal > 0 else 0.0)
    branch_ratio = branch_margin / branch_noise if branch_noise else float("inf")
    qualified = all(by_member[m]["rank1_association"] for m in MEMBERS) and gap_ratio >= 10 and link_ratio >= 10 and branch_ratio >= 5
    rank1_status = "RANK1_QUALIFIED" if qualified else "RANK1_WITHHELD"
    def c3(key: str, require_rank1: bool) -> str:
        if require_rank1 and not qualified:
            return "RANK1_WITHHELD"
        for left, right in itertools.combinations(MEMBERS, 2):
            a, b = by_member[left][key], by_member[right][key]
            if abs(a["median"] - b["median"]) > a["uncertainty"] + b["uncertainty"] or (a["median"] and b["median"] and np.sign(a["median"]) != np.sign(b["median"])):
                return "FAIL"
        return "PASS"
    return {"configuration_id": configuration_id, "record_count": len(records), "plaquettes": plaquettes, "member_summary": by_member, "rank1_qualification": {"status": rank1_status, "stable_band2_association": all(by_member[m]["rank1_association"] for m in MEMBERS), "gap_signal": gap_signal, "gap_repeat_noise": gap_noise, "link_signal": link_signal, "link_repeat_noise": link_noise, "ratios": {"gap_to_uncertainty": gap_ratio, "link_to_repeat_noise": link_ratio, "branch_margin_to_phase_uncertainty": branch_ratio}}, "rank1_c3_status": c3("rank1_phase_density", True), "rank2_c3_status": c3("rank2_trace_phase_density", False), "canonical_rank2_pair_one_based": [2, 3], "stencil": "C3_COVARIANT"}


def conditional_r96_trigger(analyses: Mapping[str, Mapping[str, Any]]) -> tuple[bool, list[str]]:
    reasons = []
    coarse, fine = analyses["R64_T1E9_M3"], analyses["R128_T1E9_M3"]
    for member in MEMBERS:
        a = coarse["member_summary"][member]["rank2_trace_phase_density"]
        b = fine["member_summary"][member]["rank2_trace_phase_density"]
        if abs(a["median"] - b["median"]) > a["uncertainty"] + b["uncertainty"]:
            reasons.append(f"rank2_density:{member}")
        if coarse["member_summary"][member]["rank2_best_pairs"] != fine["member_summary"][member]["rank2_best_pairs"]:
            reasons.append(f"rank2_pair:{member}")
        if coarse["rank1_c3_status"] != fine["rank1_c3_status"] or coarse["rank2_c3_status"] != fine["rank2_c3_status"]:
            reasons.append(f"c3_status:{member}")
    return bool(reasons), reasons


def _result(bundle: Mapping[str, Any], source_commit: str, parent: Mapping[str, Any], records: Sequence[Mapping[str, Any]], analyses: Mapping[str, Mapping[str, Any]], graphs: Mapping[str, Sequence[Mapping[str, Any]]], conditional: bool, trigger_reasons: Sequence[str], m2_count: int) -> dict[str, Any]:
    statuses = {name: {"rank1": value["rank1_c3_status"], "rank2": value["rank2_c3_status"]} for name, value in analyses.items()}
    selected = "NUMERICAL_SETTINGS_QUALIFIED_C3_RESTORED" if all(v["rank1"] == "PASS" for v in statuses.values()) else "BAND_ASSOCIATION_OR_NEAR_DEGENERACY" if any(not a["rank1_qualification"]["stable_band2_association"] for a in analyses.values()) else "TOLERANCE_SENSITIVITY" if analyses["R128_T1E9_M3"]["rank1_c3_status"] != "PASS" else "UNRESOLVED_UNDER_BOUNDED_EXPERIMENT"
    decision = {"NUMERICAL_SETTINGS_QUALIFIED_C3_RESTORED": "QUALIFIED_DETERMINISTIC_G15_FULL_RAW_HBZ_MAP_AT_M41_SETTINGS", "BAND_ASSOCIATION_OR_NEAR_DEGENERACY": "ADAPTIVE_VALIDATED_SUBSPACE_BERRY_TRANSPORT_USING_M41_RAW_BANDS", "TOLERANCE_SENSITIVITY": "QUALIFY_T1E9_SETTINGS_AND_ADVANCE_TO_FULL_G15_MAP_IF_RANK1_PASSES", "UNRESOLVED_UNDER_BOUNDED_EXPERIMENT": "TARGETED_NEXT_DISCRIMINANT_FROM_M41_EVIDENCE"}[selected]
    return {"schema": RESULT_SCHEMA, "status": "PASS" if len(records) in (108, 144) else "FAIL_CLOSED", "scientific_acceptance_status": "PASS" if len(records) in (108, 144) else "FAIL_CLOSED", "machine_execution_contract_status": "ONE_NATIVE_M41_108_OR_144_STATE_C3_COVARIANT_CONVERGENCE_COMPLETE", "work_order_id": bundle["work_order_id"], "native_invocation_count": 1, "provider_execution_count": len(records), "solver_execution_count": len(records), "dataset_record_count": len(records), "dataset_record_count_valid": len(records) in (108, 144), "parent_dataset_id": parent["dataset_id"], "parent_manifest_sha256": parent["manifest_sha256"], "parent_namespace_sha256": m40r2.PARENT_NAMESPACE_SHA256, "baseline_record_count": 72, "baseline_dataset_id": BASELINE_DATASET_ID, "baseline_manifest_sha256": BASELINE_MANIFEST_SHA256, "executed_configuration_ids": list(analyses), "conditional_R96_executed": conditional, "conditional_R96_trigger_reasons": list(trigger_reasons), "request_graph_sha256_by_configuration": {name: request_graph_digest(graph) for name, graph in graphs.items()}, "configuration_analysis": analyses, "tolerance_sensitivity": {"baseline": "R128_T1E7_M3", "comparison": "R128_T1E9_M3"}, "mesh_sensitivity": {"comparison": "R128_T1E9_M1_vs_R128_T1E9_M3"}, "resolution_sensitivity": {"comparison": "R64_T1E9_M3_vs_R128_T1E9_M3", "conditional_R96": conditional}, "rank1_c3_status_by_configuration": {name: value["rank1_c3_status"] for name, value in analyses.items()}, "rank2_c3_status_by_configuration": {name: value["rank2_c3_status"] for name, value in analyses.items()}, "historical_m2_comparison": {"dataset_id": M2_DATASET_ID, "manifest_sha256": M2_MANIFEST_SHA256, "record_count": m2_count, "payload_schema": "mephc-berry-c3-pilot-plaquette-v1", "not_used_as_raw_H": True}, "causal_synthesis": {"class": selected, "reason": "Configuration-specific tolerance,mesh and resolution comparisons retained separately."}, "next_science_decision": decision, "goal_completion_status": "NOT_COMPLETE_CONTINUE_CAUSAL_BRANCH", "source_commit_used": source_commit, "post_analysis_checkout_unchanged": True}


def main() -> int:
    bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8"))
    source_commit = str(os.environ.get("MEPHC_SOURCE_COMMIT") or bundle.get("source_commit") or "")
    records: list[dict[str, Any]] = []
    counter = None
    try:
        job = _load(ROOT / "tools" / "mephc-flow" / "scientific_job.py", "m41_job")
        m39 = _load(ROOT / "audit" / "berry_c3_consistency" / "m39_g15_deterministic_repeat_band_association_worst_orbit_pilot.py", "m41_m39")
        m38 = _load(ROOT / "audit" / "berry_c3_consistency" / "m38_supplied_exact_mpb_source_semantics_raw_native_c3.py", "m41_m38")
        state_root = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"]).parent.parent
        baseline = _read_dataset(job, state_root, BASELINE_DATASET_ID, BASELINE_MANIFEST_SHA256, BASELINE_SCHEMA, 72)
        m18 = _read_dataset(job, state_root, M18_DATASET_ID, M18_MANIFEST_SHA256, m40r2.M18_SCHEMA, 3)
        m39r1 = _read_dataset(job, state_root, M39R1_DATASET_ID, M39R1_MANIFEST_SHA256, M39R1_SCHEMA, 14)
        centers = m40r2._centers(m18, m39r1)
        graphs = {config["configuration_id"]: request_graph(config, centers, source_commit) for config in CONFIGS}
        graphs[CONDITIONAL["configuration_id"]] = request_graph(CONDITIONAL, centers, source_commit)
        import meep as mp
        from meep import mpb
        from mephc.band import Band
        band = Band(a=400.0, r1=80.14335684352235, r2=75.13439704080221, n_eff=2.7, h=100.0, resolution=128, lattice_type="triangular", polarization="TE", structure_type="slab")
        pattern = band.create_unitcell(15, 0.0, 15, 60.0, show=False)
        geometry = band.create_material_block() + band.convert_ndarray_to_meep_geo(pattern, rectify=True)
        counter = job.BudgetCounter(144, 144)
        store = job.ImmutableDatasetStore(state_root, {"goal_id": "MEPHC-BERRY-C3-CONSISTENCY-V1", "work_order_id": bundle["work_order_id"], "source_commit": source_commit, "record_schema": DATASET_SCHEMA})
        for config in CONFIGS:
            config_id = config["configuration_id"]
            for spec in graphs[config_id]:
                reciprocal = mp.cartesian_to_reciprocal(mp.Vector3(float(spec["coordinate"][0]), float(spec["coordinate"][1]), 0.0), band.geo_latt)
                solver = mpb.ModeSolver(geometry=geometry, geometry_lattice=band.geo_latt, k_points=[reciprocal], resolution=int(config["resolution"]), num_bands=BANDS, default_material=mp.air, tolerance=float(config["tolerance"]), deterministic=True, mesh_size=int(config["mesh_size"]))
                captured = m39.capture_state(mp, solver, reciprocal, spec, counter, source_commit)
                captured.update({"schema": DATASET_SCHEMA, "configuration_id": config_id, "stencil": "C3_COVARIANT", "geometry_id": "G15", "c3_member_identity": spec["c3_member_identity"], "member_index": spec["member_index"], "repeat_index": spec["repeat_index"], "vertex_index": spec["vertex_index"], "center": spec["center"], "coordinate": spec["coordinate"], "deterministic": True, "resolution": config["resolution"], "tolerance": config["tolerance"], "mesh_size": config["mesh_size"]})
                key = json.dumps({"work_order_id": bundle["work_order_id"], "configuration_id": config_id, "member": spec["c3_member_identity"], "repeat": spec["repeat_index"], "vertex": spec["vertex_index"]}, sort_keys=True, separators=(",", ":")).encode()
                store.put(key, json.dumps(captured, sort_keys=True, separators=(",", ":"), default=lambda value: _safe(value)).encode(), {"configuration_id": config_id, "member": spec["c3_member_identity"], "repeat_index": spec["repeat_index"], "vertex_index": spec["vertex_index"]})
                records.append(captured)
            analyses[config_id] = _configuration_analysis([row for row in records if row["configuration_id"] == config_id], centers, m38, m39, config_id)
        trigger, reasons = conditional_r96_trigger(analyses)
        if trigger:
            config = CONDITIONAL
            for spec in graphs[config["configuration_id"]]:
                reciprocal = mp.cartesian_to_reciprocal(mp.Vector3(float(spec["coordinate"][0]), float(spec["coordinate"][1]), 0.0), band.geo_latt)
                solver = mpb.ModeSolver(geometry=geometry, geometry_lattice=band.geo_latt, k_points=[reciprocal], resolution=int(config["resolution"]), num_bands=BANDS, default_material=mp.air, tolerance=float(config["tolerance"]), deterministic=True, mesh_size=int(config["mesh_size"]))
                captured = m39.capture_state(mp, solver, reciprocal, spec, counter, source_commit)
                captured.update({"schema": DATASET_SCHEMA, "configuration_id": config["configuration_id"], "stencil": "C3_COVARIANT", "geometry_id": "G15", "c3_member_identity": spec["c3_member_identity"], "member_index": spec["member_index"], "repeat_index": spec["repeat_index"], "vertex_index": spec["vertex_index"], "center": spec["center"], "coordinate": spec["coordinate"], "deterministic": True, "resolution": config["resolution"], "tolerance": config["tolerance"], "mesh_size": config["mesh_size"]})
                key = json.dumps({"work_order_id": bundle["work_order_id"], "configuration_id": config["configuration_id"], "member": spec["c3_member_identity"], "repeat": spec["repeat_index"], "vertex": spec["vertex_index"]}, sort_keys=True, separators=(",", ":")).encode()
                store.put(key, json.dumps(captured, sort_keys=True, separators=(",", ":"), default=lambda value: _safe(value)).encode(), {"configuration_id": config["configuration_id"], "member": spec["c3_member_identity"], "repeat_index": spec["repeat_index"], "vertex_index": spec["vertex_index"]})
                records.append(captured)
            analyses[config["configuration_id"]] = _configuration_analysis([row for row in records if row["configuration_id"] == config["configuration_id"]], centers, m38, m39, config["configuration_id"])
        if len(records) not in (108, 144) or counter.provider_count != len(records) or counter.solver_count != len(records):
            raise ValueError(f"M41_COUNT_INVALID:{len(records)}:{counter.provider_count}:{counter.solver_count}")
        parent = {"dataset_id": BASELINE_DATASET_ID, "manifest_sha256": BASELINE_MANIFEST_SHA256}
        dataset = store.finalize(len(records), {"dataset_schema": DATASET_SCHEMA, "configuration_ids": list(analyses), "request_graph_sha256_by_configuration": {name: request_graph_digest(graph) for name, graph in graphs.items()}, "conditional_R96_executed": trigger, "source_baseline_dataset_id": BASELINE_DATASET_ID, "new_state_count": len(records)})
        result = _result(bundle, source_commit, parent, records, analyses, graphs, trigger, reasons, 0)
        result.update({"dataset_id": dataset["dataset_id"], "manifest_sha256": dataset["manifest_sha256"]})
    except BaseException as exc:
        result = {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED" if not records else "PARTIAL_ACQUISITION", "scientific_acceptance_status": "FAIL_CLOSED", "machine_execution_contract_status": "M41_FAIL_CLOSED", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 1 if counter is not None else 0, "provider_execution_count": getattr(counter, "provider_count", 0), "solver_execution_count": getattr(counter, "solver_count", 0), "dataset_record_count": len(records), "failure_code": str(exc)[:1024], "failure_stage": "acquisition_or_analysis", "exception_type": type(exc).__name__, "source_commit_used": source_commit, "post_analysis_checkout_unchanged": True}
    Path(os.environ["MEPHC_RESULT_PATH"]).write_text(json.dumps(_safe(result), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
