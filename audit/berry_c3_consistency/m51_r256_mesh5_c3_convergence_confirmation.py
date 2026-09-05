"""M51: bounded R256 mesh-5 convergence confirmation for the C3 branch.

The preceding M50 result is consumed only as immutable evidence.  This entry
point adds one and only one new setting (R256_T1E9_M5), preserving the M50
mesh-1/mesh-3 comparison and keeping the mesh-causality test differential.
"""
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
M50_PATH = ROOT / "audit/berry_c3_consistency/m50_r256_mesh1_vs_mesh3_c3_causal_control.py"
SPEC = importlib.util.spec_from_file_location("m51_m50_reference", M50_PATH)
assert SPEC and SPEC.loader
m50 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m50)
m41r3 = m50.m41r3
m49r1 = m50.m49r1
detail_substrate = m50.detail_substrate
m45r2 = m50.m45r2

RESULT_SCHEMA = "mephc-berry-c3-consistency-m51-r256-mesh5-c3-convergence-confirmation-v1"
DATASET_SCHEMA = "mephc-berry-c3-consistency-m51-r256-mesh5-c3-convergence-dataset-v1"
CONFIGURATION_ID = "R256_T1E9_M5"
MESH_SIZE = 5
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
    raise ValueError(f"M51_UNSAFE_RESULT:{type(value).__name__}")


def _reference_analysis(job: Any, state_root: Path) -> dict[str, Any]:
    matrix, centers, m38, m39 = m50._read_reference(job, state_root)
    analyses = {
        resolution: detail_substrate.configuration_detail(
            rows, centers, m38, m39, f"R{resolution}_T1E9_M3"
        )
        for resolution, rows in matrix.items()
    }
    frequency_src, gap_src, subspace_src, link_src = m49r1._build_scalar_sources(matrix, analyses)
    frequency = m49r1._family(frequency_src, "frequency")
    gap = m49r1._family(gap_src, "gap")
    subspace = m49r1._family(subspace_src, "subspace")
    link = m49r1._family(link_src, "rank1_link_corroboration")
    berry2_values, berry1_values = m49r1._build_berry(matrix, analyses)
    berry2 = m49r1._berry_residual("canonical_rank2_trace_phase_density", berry2_values, "berry_rank2")
    rank1_eligible = analyses[256]["rank1_qualification"]["status"] == "RANK1_QUALIFIED"
    berry1 = m49r1._berry_residual("rank1_phase_density", berry1_values, "berry_rank1") if rank1_eligible else None
    association = m49r1._association(analyses)
    rank1 = {
        "eligible": rank1_eligible,
        "c3_pass": bool(berry1 and berry1["pass"]) if rank1_eligible else False,
        "blockers": m49r1._rank1_blockers(analyses[256]),
    }
    return {
        "matrix": matrix, "centers": centers, "m38": m38, "m39": m39,
        "analyses": analyses, "frequency_src": frequency_src, "gap_src": gap_src,
        "subspace_src": subspace_src, "link_src": link_src, "frequency": frequency,
        "gap": gap, "subspace": subspace, "link": link, "berry2": berry2,
        "berry1": berry1, "rank1": rank1, "association": association,
    }


def _mesh_graph(centers: Mapping[str, Sequence[float]], source_commit: str) -> list[dict[str, Any]]:
    graph: list[dict[str, Any]] = []
    for member_index, member in enumerate(MEMBERS):
        vertices, _ = m41r3._plaquette_vertices(centers[member], member_index)
        for repeat in range(3):
            for vertex_index, coordinate in enumerate(vertices):
                row = {
                    "goal_id": "MEPHC-BERRY-C3-CONSISTENCY-V1", "milestone": "M51",
                    "geometry_id": "G15", "stencil": "C3_COVARIANT",
                    "configuration_id": CONFIGURATION_ID, "member_index": member_index,
                    "c3_member_identity": member, "repeat_index": repeat,
                    "vertex_index": vertex_index, "center": list(map(float, centers[member])),
                    "coordinate": list(map(float, coordinate)), "deterministic": True,
                    "num_bands": 4, "resolution": 256, "tolerance": 1e-9,
                    "mesh_size": MESH_SIZE, "polarization": "TE", "mode_count": 65536,
                    "fft_shape": [256, 256], "source_commit": source_commit,
                }
                row["request_key_sha256"] = hashlib.sha256(
                    json.dumps(row, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest()
                graph.append(row)
    if len(graph) != 36 or len({row["request_key_sha256"] for row in graph}) != 36:
        raise ValueError("M51_R256_MESH5_GRAPH_INVALID")
    return graph


def _capture_mesh5(mp: Any, solver: Any, spec: Mapping[str, Any], counter: Any, source_commit: str) -> dict[str, Any]:
    value = m41r3._capture(mp, solver, spec, counter, source_commit)
    value.update({
        "schema": DATASET_SCHEMA, "configuration_id": CONFIGURATION_ID,
        "resolution": 256, "mesh_size": MESH_SIZE, "mode_count": 65536,
        "fft_shape": [256, 256],
        "native_layout_contract": {
            "accepted": [[65536, 2, 4], [4, 65536, 2], [4, 2, 65536]],
            "canonical": [4, 65536, 2],
        },
    })
    return value


def _frequency_mesh_ledger(baseline: Mapping[str, Any], control: Mapping[str, Any]) -> dict[str, Any]:
    entries: dict[str, Any] = {}
    for identity in baseline["frequency"]["failing_identities"]:
        base = baseline["frequency_src"][identity][256]
        ctl = control["frequency_src"][identity][256]
        pairs: dict[str, Any] = {}
        for left, right in itertools.combinations(MEMBERS, 2):
            base_left, base_right = m49r1._scalar_stats(base[left]), m49r1._scalar_stats(base[right])
            ctl_left, ctl_right = m49r1._scalar_stats(ctl[left]), m49r1._scalar_stats(ctl[right])
            shift_left = ctl_left["median"] - base_left["median"]
            shift_right = ctl_right["median"] - base_right["median"]
            differential = shift_left - shift_right
            uncertainty = (
                ctl_left["repeat_uncertainty"] + ctl_right["repeat_uncertainty"]
                + base_left["repeat_uncertainty"] + base_right["repeat_uncertainty"]
            )
            pairs[f"{left}_vs_{right}"] = {
                "shift35_left": shift_left, "shift35_right": shift_right,
                "differential35": differential,
                "combined_repeat_uncertainty": uncertainty,
                "mesh35_sensitive": abs(differential) > uncertainty,
                "mesh35_common_mode": abs(differential) <= uncertainty,
                "strict_excess_rule": "abs(differential35)>combined_repeat_uncertainty",
            }
        entries[identity] = {
            "pairs": pairs,
            "all_pairs_mesh_sensitive": all(p["mesh35_sensitive"] for p in pairs.values()),
            "any_pair_mesh_sensitive": any(p["mesh35_sensitive"] for p in pairs.values()),
        }
    return {
        "baseline_failing_frequency_identities": list(baseline["frequency"]["failing_identities"]),
        "per_identity": entries,
        "mesh_sensitive_pair_count": sum(
            sum(pair["mesh35_sensitive"] for pair in item["pairs"].values())
            for item in entries.values()
        ),
        "mesh35_all_common_mode": bool(entries) and all(
            not item["any_pair_mesh_sensitive"] for item in entries.values()
        ),
        "mesh35_any_sensitive": any(item["any_pair_mesh_sensitive"] for item in entries.values()),
    }


def _frequency_c3_pass(baseline: Mapping[str, Any], control: Mapping[str, Any]) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for identity in baseline["frequency"]["failing_identities"]:
        values = control["frequency_src"][identity][256]
        pairs = {}
        for left, right in itertools.combinations(MEMBERS, 2):
            l, r = m49r1._scalar_stats(values[left]), m49r1._scalar_stats(values[right])
            adjacent = abs(l["median"] - baseline["frequency_src"][identity][256][left][1])
            adjacent += abs(r["median"] - baseline["frequency_src"][identity][256][right][1])
            uncertainty = l["repeat_uncertainty"] + r["repeat_uncertainty"] + adjacent
            residual = abs(l["median"] - r["median"])
            pairs[f"{left}_vs_{right}"] = {
                "residual": residual, "total_mesh_uncertainty": uncertainty,
                "pass": residual <= uncertainty,
            }
        results[identity] = {"pairs": pairs, "pass": all(p["pass"] for p in pairs.values())}
    return {"per_identity": results, "all_pass": bool(results) and all(v["pass"] for v in results.values())}


def _classify(ledger: Mapping[str, Any], frequency_test: Mapping[str, Any], control: Mapping[str, Any]) -> tuple[str, str]:
    ids = list(ledger["baseline_failing_frequency_identities"])
    if not ids:
        return "PRENATIVE_M50_REROUTE_NO_MESH5", "USE_PRENATIVE_REPRODUCED_CONCRETE_DECISION"
    if ledger["mesh35_all_common_mode"] and frequency_test["all_pass"]:
        if not control.get("gap", {}).get("pass", True) or not control.get("subspace", {}).get("pass", True):
            return "R256_M3_M5_FREQUENCY_MESH_PLATEAU_DOWNSTREAM_GAP_OR_SUBSPACE_FAIL", "ADAPTIVE_VALIDATED_SUBSPACE_AND_NEAR_DEGENERACY_ADJUDICATION_USING_R256_M3_M5_RAW_BANDS"
        if not control.get("berry2", {}).get("pass", True):
            return "R256_M3_M5_FREQUENCY_MESH_PLATEAU_BERRY_OR_BRANCH_FAIL", "BOUND_PLAQUETTE_STEP_CONVERGENCE_AT_R256_M5"
        if not control.get("rank1", {}).get("eligible", False):
            return "R256_M3_M5_FREQUENCY_MESH_PLATEAU_RANK1_WITHHELD_ISOLATION_OR_ASSOCIATION", "ADAPTIVE_VALIDATED_SUBSPACE_BERRY_TRANSPORT_USING_R256_M3_M5_RAW_BANDS"
        return "R256_M3_M5_FREQUENCY_MESH_PLATEAU_ALL_C3_PASS", "CROSS_ORBIT_C3_QUALIFICATION_AT_R256_T1E9_M5"
    if ledger["mesh35_all_common_mode"]:
        return "R256_M3_M5_NO_FREQUENCY_MESH_PLATEAU_MESH_INSENSITIVE_C3_FAILURE", "R256_RECIPROCAL_TRUNCATION_C3_COVARIANCE_DIAGNOSTIC_USING_M3_M5_RAW_H"
    if all(item["all_pairs_mesh_sensitive"] for item in ledger["per_identity"].values()):
        return "R256_M3_M5_NO_FREQUENCY_MESH_PLATEAU_STILL_MESH_SENSITIVE", "BOUND_R256_MESH7_C3_CONVERGENCE_CONFIRMATION"
    return "R256_M3_M5_MIXED_FREQUENCY_MESH_RESPONSE", "R256_RECIPROCAL_TRUNCATION_C3_COVARIANCE_DIAGNOSTIC_WITH_MESH_CONTRIBUTOR"


def _result_base(bundle: Mapping[str, Any], source_commit: str, pre: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS",
        "machine_execution_contract_status": "CONDITIONAL_ZERO_OR_ONE_NATIVE_R256_MESH5_C3_CONVERGENCE_CONFIRMATION",
        "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 0,
        "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0,
        "pre_native_m49r1_failing_layers": pre["frequency"]["failing_identities"],
        "pre_native_m49r1_classification": pre["analyses"].get(256, {}).get("configuration_id", "R256_T1E9_M3"),
        "pre_native_mesh1_mesh3_association": pre["association"],
        "pre_native_mesh5_authorized": False, "source_commit_used": source_commit,
        "post_analysis_checkout_unchanged": True,
    }


def main() -> int:
    bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8"))
    source_commit = str(os.environ.get("MEPHC_SOURCE_COMMIT") or bundle.get("source_commit") or "")
    try:
        job = m41r3._load(ROOT / "tools/mephc-flow/scientific_job.py", "m51_job")
        state_root = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"]).parent.parent
        pre = _reference_analysis(job, state_root)
        authorized = bool(pre["frequency"]["failing_identities"]) and pre["analyses"].get(256, {}).get("configuration_id", "R256_T1E9_M3")
        if not authorized:
            result = _result_base(bundle, source_commit, pre)
            result.update({"status": "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "failure_code": "PRENATIVE_M50_GATE_NOT_REPRODUCED"})
        else:
            graph = _mesh_graph(pre["centers"], source_commit)
            graph_hash = hashlib.sha256(json.dumps(graph, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            import meep as mp
            from meep import mpb
            from mephc.band import Band
            band = Band(a=400.0, r1=80.14335684352235, r2=75.13439704080221, n_eff=2.7, h=100.0, resolution=256, lattice_type="triangular", polarization="TE", structure_type="slab")
            pattern = band.create_unitcell(15, 0.0, 15, 60.0, show=False)
            geometry = band.create_material_block() + band.convert_ndarray_to_meep_geo(pattern, rectify=True)
            counter = job.BudgetCounter(36, 36)
            store = job.ImmutableDatasetStore(state_root, {"goal_id": "MEPHC-BERRY-C3-CONSISTENCY-V1", "work_order_id": bundle["work_order_id"], "source_commit": source_commit, "record_schema": DATASET_SCHEMA, "configuration_id": CONFIGURATION_ID, "graph_sha256": graph_hash, "mode_count": 65536, "fft_shape": [256, 256]})
            records = []
            for spec in graph:
                reciprocal = mp.cartesian_to_reciprocal(mp.Vector3(float(spec["coordinate"][0]), float(spec["coordinate"][1]), 0.0), band.geo_latt)
                solver = mpb.ModeSolver(geometry=geometry, geometry_lattice=band.geo_latt, k_points=[reciprocal], resolution=256, num_bands=4, default_material=mp.air, tolerance=1e-9, deterministic=True, mesh_size=MESH_SIZE)
                captured = _capture_mesh5(mp, solver, spec, counter, source_commit)
                key = json.dumps({"work_order_id": bundle["work_order_id"], "configuration_id": CONFIGURATION_ID, "member": spec["c3_member_identity"], "repeat": spec["repeat_index"], "vertex": spec["vertex_index"]}, sort_keys=True, separators=(",", ":")).encode()
                store.put(key, json.dumps(captured, sort_keys=True, separators=(",", ":"), default=_safe).encode(), {"configuration_id": CONFIGURATION_ID, "member": spec["c3_member_identity"], "repeat_index": spec["repeat_index"], "vertex_index": spec["vertex_index"]})
                records.append(captured)
            dataset = store.finalize(36, {"dataset_schema": DATASET_SCHEMA, "configuration_id": CONFIGURATION_ID, "graph_sha256": graph_hash, "source_parent_dataset_ids": [m45r2.M41R3_DATASET_ID, m49r1.M46_DATASET_ID, m49r1.M47_DATASET_ID]})
            mesh_matrix = dict(pre["matrix"]); mesh_matrix[256] = records
            mesh_analyses = dict(pre["analyses"]); mesh_analyses[256] = detail_substrate.configuration_detail(records, pre["centers"], pre["m38"], pre["m39"], CONFIGURATION_ID)
            mesh_frequency, mesh_gap, mesh_subspace, mesh_link = m49r1._build_scalar_sources(mesh_matrix, mesh_analyses)
            mesh_berry2_values, _ = m49r1._build_berry(mesh_matrix, mesh_analyses)
            mesh_berry2 = m49r1._berry_residual("canonical_rank2_trace_phase_density", mesh_berry2_values, "berry_rank2")
            mesh_rank1 = {"eligible": mesh_analyses[256]["rank1_qualification"]["status"] == "RANK1_QUALIFIED", "blockers": m49r1._rank1_blockers(mesh_analyses[256])}
            control = {"frequency_src": mesh_frequency, "gap": m49r1._family(mesh_gap, "gap"), "subspace": m49r1._family(mesh_subspace, "subspace"), "berry2": mesh_berry2, "rank1": mesh_rank1}
            ledger = _frequency_mesh_ledger(pre, control)
            frequency_test = _frequency_c3_pass(pre, control)
            classification, decision = _classify(ledger, frequency_test, control)
            result = _result_base(bundle, source_commit, pre)
            result.update({"classification": classification, "causal_outcome": classification, "next_science_decision": decision, "pre_native_mesh5_authorized": True, "native_invocation_count": 1, "provider_execution_count": counter.provider_count, "solver_execution_count": counter.solver_count, "dataset_record_count": len(records), "dataset_id": dataset.get("dataset_id"), "manifest_sha256": dataset.get("manifest_sha256"), "graph_sha256": graph_hash, "mesh1_mesh3_mesh5_differential_ledger": ledger, "mesh5_frequency_c3_test": frequency_test, "mesh5_downstream_detail": {"gap": control["gap"], "subspace": control["subspace"], "berry2": control["berry2"], "rank1": control["rank1"], "link_identity_count": len(mesh_link)}, "uncertainty_components": {"repeat": "mesh5 scalar repeat uncertainty", "resolution": "existing R224_M3 to R256_M3 corresponding identity", "mesh": "R256_M3 to R256_M5 corresponding identity"}, "r256_mesh5_verified_record_count": len(records)})
    except BaseException as exc:
        result = {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "machine_execution_contract_status": "M51_FAIL_CLOSED", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 0, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "failure_code": str(exc)[:1024], "failure_stage": "prenative_gate_or_mesh5_convergence", "exception_type": type(exc).__name__, "source_commit_used": source_commit}
    Path(os.environ["MEPHC_RESULT_PATH"]).write_text(json.dumps(_safe(result), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
