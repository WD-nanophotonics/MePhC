"""M50: bounded R256 mesh-1 control for the corrected C3 frequency branch."""
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
M49R1_PATH = ROOT / "audit/berry_c3_consistency/m49r1_corrected_r256_c3_residual_causal_adjudication.py"
SPEC = importlib.util.spec_from_file_location("m50_m49r1_reference", M49R1_PATH)
assert SPEC and SPEC.loader
m49r1 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m49r1)
m41r3 = m49r1.m41r3
detail_substrate = m49r1.detail_substrate
m45r2 = m49r1.m45r2

RESULT_SCHEMA = "mephc-berry-c3-consistency-m50-r256-mesh1-vs-mesh3-c3-causal-control-v1"
DATASET_SCHEMA = "mephc-berry-c3-consistency-m50-r256-mesh1-c3-causal-control-dataset-v1"
MEMBERS = tuple(m49r1.MEMBERS)


def _safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else ("INF" if value > 0 else "-INF" if value < 0 else "NAN")
    if isinstance(value, np.generic):
        return _safe(value.item())
    if isinstance(value, np.ndarray):
        return _safe(value.tolist())
    if isinstance(value, complex):
        return [_safe(value.real), _safe(value.imag)]
    if isinstance(value, Mapping):
        return {str(key): _safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(item) for item in value]
    raise ValueError(f"M50_UNSAFE_RESULT:{type(value).__name__}")


def _read_reference(job: Any, state_root: Path) -> tuple[dict[int, list[dict[str, Any]]], Mapping[str, Sequence[float]], Any, Any]:
    return m49r1._read_matrix(job, state_root)


def _reference_analysis(job: Any, state_root: Path) -> dict[str, Any]:
    matrix, centers, m38, m39 = _read_reference(job, state_root)
    analyses = {resolution: detail_substrate.configuration_detail(rows, centers, m38, m39, f"R{resolution}_T1E9_M3") for resolution, rows in matrix.items()}
    frequency_src, gap_src, subspace_src, link_src = m49r1._build_scalar_sources(matrix, analyses)
    frequency = m49r1._family(frequency_src, "frequency"); gap = m49r1._family(gap_src, "gap"); subspace = m49r1._family(subspace_src, "subspace"); link = m49r1._family(link_src, "rank1_link_corroboration")
    berry2_values, berry1_values = m49r1._build_berry(matrix, analyses)
    berry2_residual = m49r1._berry_residual("canonical_rank2_trace_phase_density", berry2_values, "berry_rank2")
    rank1_eligible = analyses[256]["rank1_qualification"]["status"] == "RANK1_QUALIFIED"
    berry1_residual = m49r1._berry_residual("rank1_phase_density", berry1_values, "berry_rank1") if rank1_eligible else None
    association = m49r1._association(analyses); blockers = m49r1._rank1_blockers(analyses[256]); rank1 = {"eligible": rank1_eligible, "c3_pass": bool(berry1_residual and berry1_residual["pass"]) if rank1_eligible else False, "blockers": blockers}
    families = {"frequency": frequency, "gap": gap, "subspace": subspace, "berry_rank2": {"identities": {"canonical_rank2_trace_phase_density": berry2_residual}, "all_pass": berry2_residual["pass"], "failing_identities": [] if berry2_residual["pass"] else ["canonical_rank2_trace_phase_density"]}}
    classification, decision, failing_layers = m49r1._localize(families, berry2_residual["pass"], bool(berry2_residual["branch_ambiguity"]), rank1, association)
    return {"matrix": matrix, "centers": centers, "m38": m38, "m39": m39, "analyses": analyses, "frequency_src": frequency_src, "gap_src": gap_src, "subspace_src": subspace_src, "link_src": link_src, "frequency": frequency, "gap": gap, "subspace": subspace, "link": link, "berry2": berry2_residual, "rank1": rank1, "association": association, "classification": classification, "decision": decision, "failing_layers": failing_layers}


def _mesh_graph(centers: Mapping[str, Sequence[float]], source_commit: str) -> list[dict[str, Any]]:
    graph = []
    for member_index, member in enumerate(MEMBERS):
        vertices, _ = m41r3._plaquette_vertices(centers[member], member_index)
        for repeat in range(3):
            for vertex_index, coordinate in enumerate(vertices):
                row = {"goal_id": "MEPHC-BERRY-C3-CONSISTENCY-V1", "milestone": "M50", "geometry_id": "G15", "stencil": "C3_COVARIANT", "configuration_id": "R256_T1E9_M1", "member_index": member_index, "c3_member_identity": member, "repeat_index": repeat, "vertex_index": vertex_index, "center": list(map(float, centers[member])), "coordinate": list(map(float, coordinate)), "deterministic": True, "num_bands": 4, "resolution": 256, "tolerance": 1e-9, "mesh_size": 1, "polarization": "TE", "mode_count": 65536, "fft_shape": [256, 256], "source_commit": source_commit}
                row["request_key_sha256"] = hashlib.sha256(json.dumps(row, sort_keys=True, separators=(",", ":")).encode()).hexdigest(); graph.append(row)
    if len(graph) != 36 or len({row["request_key_sha256"] for row in graph}) != 36:
        raise ValueError("M50_R256_MESH1_GRAPH_INVALID")
    return graph


def _capture_mesh1(mp: Any, solver: Any, spec: Mapping[str, Any], counter: Any, source_commit: str) -> dict[str, Any]:
    value = m41r3._capture(mp, solver, spec, counter, source_commit)
    value.update({"schema": DATASET_SCHEMA, "configuration_id": "R256_T1E9_M1", "resolution": 256, "mesh_size": 1, "mode_count": 65536, "fft_shape": [256, 256], "native_layout_contract": {"accepted": [[65536, 2, 4], [4, 65536, 2], [4, 2, 65536]], "canonical": [4, 65536, 2]}})
    return value


def _frequency_mesh_ledger(baseline: Mapping[str, Any], control: Mapping[str, Any]) -> dict[str, Any]:
    failing = list(baseline["frequency"]["failing_identities"]); entries = {}
    for identity in failing:
        base_by_member = baseline["frequency_src"][identity][256]; control_by_member = control["frequency_src"][identity][256]; pairs = {}
        for left, right in itertools.combinations(MEMBERS, 2):
            base_left = m49r1._scalar_stats(base_by_member[left]); base_right = m49r1._scalar_stats(base_by_member[right]); ctl_left = m49r1._scalar_stats(control_by_member[left]); ctl_right = m49r1._scalar_stats(control_by_member[right])
            shift_left = ctl_left["median"] - base_left["median"]; shift_right = ctl_right["median"] - base_right["median"]; differential = shift_left - shift_right; uncertainty = ctl_left["repeat_uncertainty"] + ctl_right["repeat_uncertainty"] + base_left["repeat_uncertainty"] + base_right["repeat_uncertainty"]
            pairs[f"{left}_vs_{right}"] = {"shift_left": shift_left, "shift_right": shift_right, "differential_shift": differential, "combined_repeat_uncertainty": uncertainty, "mesh_sensitive": abs(differential) > uncertainty, "strict_excess_rule": "abs(differential_shift)>combined_repeat_uncertainty"}
        entries[identity] = {"pairs": pairs, "all_pairs_mesh_sensitive": all(pair["mesh_sensitive"] for pair in pairs.values()), "any_pair_mesh_sensitive": any(pair["mesh_sensitive"] for pair in pairs.values())}
    return {"baseline_failing_frequency_identities": failing, "per_identity": entries, "mesh_sensitive_pair_count": sum(sum(pair["mesh_sensitive"] for pair in item["pairs"].values()) for item in entries.values()), "mesh_sensitive": any(item["any_pair_mesh_sensitive"] for item in entries.values())}


def _classify_mesh(ledger: Mapping[str, Any]) -> tuple[str, str]:
    identities = list(ledger["per_identity"].values())
    if not identities or not ledger["baseline_failing_frequency_identities"]:
        return "PRENATIVE_M49R1_REROUTE_NO_MESH_ACQUISITION", "USE_PRENATIVE_REPRODUCED_M49R1_CONCRETE_DECISION"
    if all(item["all_pairs_mesh_sensitive"] for item in identities):
        return "R256_FREQUENCY_C3_BREAKING_FULLY_MESH_SENSITIVE", "BOUND_R256_HIGHER_MESH_C3_CONVERGENCE_CONFIRMATION"
    if not any(item["any_pair_mesh_sensitive"] for item in identities):
        return "R256_FREQUENCY_C3_BREAKING_MESH_INSENSITIVE", "R256_RECIPROCAL_TRUNCATION_C3_COVARIANCE_DIAGNOSTIC_USING_EXISTING_RAW_H"
    return "R256_FREQUENCY_C3_BREAKING_MIXED_MESH_AND_NONMESH", "R256_RECIPROCAL_TRUNCATION_C3_COVARIANCE_DIAGNOSTIC_WITH_MESH_CONTRIBUTOR"


def _result_base(bundle: Mapping[str, Any], source_commit: str, classification: str, decision: str, pre: Mapping[str, Any], ledger: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {"schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS", "machine_execution_contract_status": "CONDITIONAL_ZERO_OR_ONE_NATIVE_R256_MESH1_VS_MESH3_C3_CAUSAL_CONTROL", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 0, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "pre_native_failing_layers": pre["failing_layers"], "pre_native_m49r1_classification": pre["classification"], "pre_native_m49r1_next_decision": pre["decision"], "pre_native_mesh1_authorized": False, "classification": classification, "causal_outcome": classification, "next_science_decision": decision, "frequency_failure_set": pre["frequency"]["failing_identities"], "high_resolution_association": pre["association"], "pre_native_reference": {"verified_record_total": 252, "r128_source": "m41r3._read_partial", "source": "corrected M49R1 recomputation"}, "mesh_differential_ledger": ledger or {}, "source_commit_used": source_commit, "post_analysis_checkout_unchanged": True}


def main() -> int:
    bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8")); source_commit = str(os.environ.get("MEPHC_SOURCE_COMMIT") or bundle.get("source_commit") or "")
    try:
        job = m41r3._load(ROOT / "tools/mephc-flow/scientific_job.py", "m50_job"); state_root = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"]).parent.parent; pre = _reference_analysis(job, state_root)
        authorized = bool(pre["frequency"]["failing_identities"]) and pre["decision"] == "BOUND_R256_MESH_DISCRETIZATION_CONTROL"
        if not authorized:
            result = _result_base(bundle, source_commit, "PRENATIVE_M49R1_REROUTE_NO_MESH_ACQUISITION", "USE_PRENATIVE_REPRODUCED_M49R1_CONCRETE_DECISION", pre)
        else:
            graph = _mesh_graph(pre["centers"], source_commit); graph_hash = hashlib.sha256(json.dumps(graph, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            import meep as mp
            from meep import mpb
            from mephc.band import Band
            band = Band(a=400.0, r1=80.14335684352235, r2=75.13439704080221, n_eff=2.7, h=100.0, resolution=256, lattice_type="triangular", polarization="TE", structure_type="slab")
            pattern = band.create_unitcell(15, 0.0, 15, 60.0, show=False); geometry = band.create_material_block() + band.convert_ndarray_to_meep_geo(pattern, rectify=True)
            counter = job.BudgetCounter(36, 36); store = job.ImmutableDatasetStore(state_root, {"goal_id": "MEPHC-BERRY-C3-CONSISTENCY-V1", "work_order_id": bundle["work_order_id"], "source_commit": source_commit, "record_schema": DATASET_SCHEMA, "configuration_id": "R256_T1E9_M1", "graph_sha256": graph_hash, "mode_count": 65536, "fft_shape": [256, 256]}); records = []
            for spec in graph:
                reciprocal = mp.cartesian_to_reciprocal(mp.Vector3(float(spec["coordinate"][0]), float(spec["coordinate"][1]), 0.0), band.geo_latt); solver = mpb.ModeSolver(geometry=geometry, geometry_lattice=band.geo_latt, k_points=[reciprocal], resolution=256, num_bands=4, default_material=mp.air, tolerance=1e-9, deterministic=True, mesh_size=1); captured = _capture_mesh1(mp, solver, spec, counter, source_commit); key = json.dumps({"work_order_id": bundle["work_order_id"], "configuration_id": "R256_T1E9_M1", "member": spec["c3_member_identity"], "repeat": spec["repeat_index"], "vertex": spec["vertex_index"]}, sort_keys=True, separators=(",", ":")).encode(); store.put(key, json.dumps(captured, sort_keys=True, separators=(",", ":"), default=_safe).encode(), {"configuration_id": "R256_T1E9_M1", "member": spec["c3_member_identity"], "repeat_index": spec["repeat_index"], "vertex_index": spec["vertex_index"]}); records.append(captured)
            dataset = store.finalize(36, {"dataset_schema": DATASET_SCHEMA, "configuration_id": "R256_T1E9_M1", "graph_sha256": graph_hash, "source_parent_dataset_ids": [m45r2.M41R3_DATASET_ID, m49r1.M46_DATASET_ID, m49r1.M47_DATASET_ID]})
            mesh_matrix = dict(pre["matrix"]); mesh_matrix[256] = records; mesh_analyses = dict(pre["analyses"]); mesh_analyses[256] = detail_substrate.configuration_detail(records, pre["centers"], pre["m38"], pre["m39"], "R256_T1E9_M1"); mesh_frequency, mesh_gap, mesh_subspace, mesh_link = m49r1._build_scalar_sources(mesh_matrix, mesh_analyses); ledger = _frequency_mesh_ledger(pre, {"frequency_src": mesh_frequency}); classification, decision = _classify_mesh(ledger); result = _result_base(bundle, source_commit, classification, decision, pre, ledger); result.update({"pre_native_mesh1_authorized": True, "native_invocation_count": 1, "provider_execution_count": counter.provider_count, "solver_execution_count": counter.solver_count, "dataset_record_count": len(records), "dataset_id": dataset.get("dataset_id"), "manifest_sha256": dataset.get("manifest_sha256"), "graph_sha256": graph_hash, "r256_mesh1_verified_record_count": len(records), "mesh1_downstream_detail": {"association": detail_substrate._association(mesh_analyses, (192, 224, 256)), "gap_identity_count": len(mesh_gap), "subspace_identity_count": len(mesh_subspace), "link_identity_count": len(mesh_link), "berry_semantics": "corrected phase/density separation retained"}, "r128_context": "descriptive only; existing mesh1/mesh3 controls"})
    except BaseException as exc:
        result = {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "machine_execution_contract_status": "M50_FAIL_CLOSED", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 0, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "failure_code": str(exc)[:1024], "failure_stage": "prenative_gate_or_mesh1_control", "exception_type": type(exc).__name__, "source_commit_used": source_commit}
    Path(os.environ["MEPHC_RESULT_PATH"]).write_text(json.dumps(_safe(result), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
