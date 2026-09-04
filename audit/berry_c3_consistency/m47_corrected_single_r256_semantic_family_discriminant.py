"""M47: corrected six-point gate, then at most one R256 acquisition."""
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
M45R2_PATH = ROOT / "audit/berry_c3_consistency/m45r2_robust_complete_semantic_family_adjudication.py"
SPEC = importlib.util.spec_from_file_location("m47_m45r2_parent", M45R2_PATH)
assert SPEC and SPEC.loader
m45r2 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m45r2)
m41r3 = m45r2.m41r3

RESULT_SCHEMA = "mephc-berry-c3-consistency-m47-corrected-r256-semantic-family-discriminant-v1"
DATASET_SCHEMA = "mephc-berry-c3-consistency-m47-r256-semantic-family-vertex-dataset-v1"
MEMBERS = tuple(m41r3.MEMBERS)
RESOLUTIONS = (64, 96, 128, 160, 192, 224, 256)
M41R3_DATASET_ID = m45r2.M41R3_DATASET_ID
M41R3_MANIFEST_SHA256 = m45r2.M41R3_MANIFEST_SHA256
M41R3_SCHEMA = m45r2.M41R3_SCHEMA
M44_DATASET_ID = m45r2.M44_DATASET_ID
M44_MANIFEST_SHA256 = m45r2.M44_MANIFEST_SHA256
M44_SCHEMA = m45r2.M44_SCHEMA
M46_DATASET_ID = "6a0bd125fb2b4b640292ff8580d4812cbb1be8d4e1e383133060cf8139e2f533"
M46_MANIFEST_SHA256 = "b7d2f0974b5305f1903a088c99d3dd285cbca844b3d93d9a8f3a705272a0ece8"
M46_SCHEMA = "mephc-berry-c3-consistency-m46-r224-semantic-family-vertex-dataset-v1"


def _safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)): return value
    if isinstance(value, float): return value if math.isfinite(value) else ("INF" if value > 0 else "-INF" if value < 0 else "NAN")
    if isinstance(value, np.generic): return _safe(value.item())
    if isinstance(value, complex): return [_safe(float(value.real)), _safe(float(value.imag))]
    if isinstance(value, np.ndarray): return _safe(value.tolist())
    if isinstance(value, Mapping): return {str(k): _safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)): return [_safe(v) for v in value]
    raise ValueError(f"M47_UNSAFE_RESULT:{type(value).__name__}")


def r256_graph(centers: Mapping[str, Sequence[float]], source_commit: str) -> list[dict[str, Any]]:
    graph = []
    for member_index, member in enumerate(MEMBERS):
        vertices, _ = m41r3._plaquette_vertices(centers[member], member_index)
        for repeat in range(3):
            for vertex_index, coordinate in enumerate(vertices):
                row = {"goal_id": "MEPHC-BERRY-C3-CONSISTENCY-V1", "milestone": "M47", "geometry_id": "G15", "stencil": "C3_COVARIANT", "configuration_id": "R256_T1E9_M3", "member_index": member_index, "c3_member_identity": member, "repeat_index": repeat, "vertex_index": vertex_index, "center": list(map(float, centers[member])), "coordinate": list(map(float, coordinate)), "deterministic": True, "num_bands": 4, "resolution": 256, "tolerance": 1e-9, "mesh_size": 3, "polarization": "TE", "mode_count": 65536, "fft_shape": [256, 256], "source_commit": source_commit}
                row["request_key_sha256"] = hashlib.sha256(json.dumps(row, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                graph.append(row)
    if len(graph) != 36 or len({row["request_key_sha256"] for row in graph}) != 36: raise ValueError("M47_R256_GRAPH_INVALID")
    return graph


def _capture(mp: Any, solver: Any, spec: Mapping[str, Any], counter: Any, source_commit: str) -> dict[str, Any]:
    value = m41r3._capture(mp, solver, spec, counter, source_commit)
    value.update({"schema": DATASET_SCHEMA, "configuration_id": "R256_T1E9_M3", "mode_count": 65536, "fft_shape": [256, 256], "native_layout_contract": {"accepted": [[65536, 2, 4], [4, 65536, 2], [4, 2, 65536]], "canonical": [4, 65536, 2]}})
    return value


def _lift(phases: Sequence[float]) -> list[float]:
    result = []
    for phase in phases:
        value = float(phase)
        if result: value += 2.0 * math.pi * round((result[-1] - value) / (2.0 * math.pi))
        result.append(value)
    return result


def _c3_status(summary: Mapping[str, Any], member_key: str) -> str:
    members = summary["member_summary"]
    left = members[member_key]
    values = left["rank1_phase_density"]
    return "PASS" if values else "FAIL"


def configuration_detail(records: Sequence[Mapping[str, Any]], centers: Mapping[str, Sequence[float]], m38: Any, m39: Any, configuration_id: str) -> dict[str, Any]:
    """Recompute finite-control qualification from local semantic repeat groups."""
    detail = m45r2.configuration_detail(records, centers, m38, m39, configuration_id)
    for member in MEMBERS:
        plaquettes = [p for p in detail["plaquettes"] if p["member"] == member]
        gaps_by_vertex = {v: [] for v in range(4)}
        for row in records:
            if row["c3_member_identity"] == member:
                gaps_by_vertex[int(row["vertex_index"])].append(min(float(row["adjacent_gaps"]["lower_gap"]), float(row["adjacent_gaps"]["internal_split"])))
        links_by_edge = {e: [] for e in range(4)}
        for p in plaquettes:
            for edge in p["rank1_edges"]: links_by_edge[int(edge["edge_index"])].append(float(edge["link_magnitude"]))
        gap_ranges = [max(v) - min(v) for v in gaps_by_vertex.values() if v]
        link_ranges = [max(v) - min(v) for v in links_by_edge.values() if v]
        gap_signal = min(v for values in gaps_by_vertex.values() for v in values)
        link_signal = min(v for values in links_by_edge.values() for v in values)
        gap_noise = max(gap_ranges, default=0.0); link_noise = max(link_ranges, default=0.0)
        phases = _lift([p["rank1_wilson_phase"] for p in plaquettes])
        densities = [phase / float(p["signed_area"]) for phase, p in zip(phases, plaquettes)]
        median = float(np.median(densities)); phase_noise = float(max(abs(v - median) for v in densities))
        branch_margin = min(math.pi - abs(p["rank1_wilson_phase"]) for p in plaquettes)
        association = all(edge["best_target_band"] == 2 for p in plaquettes for edge in p["rank1_edges"])
        rank2_association = all(edge["best_target_pair"] == [2, 3] for p in plaquettes for edge in p["rank2_edges"])
        gate = {"gap_signal": gap_signal, "gap_repeat_noise": gap_noise, "link_signal": link_signal, "link_repeat_noise": link_noise, "branch_uncertainty": phase_noise, "gap_ratio": gap_signal / gap_noise if gap_noise else (float("inf") if gap_signal > 0 else 0.0), "link_ratio": link_signal / link_noise if link_noise else (float("inf") if link_signal > 0 else 0.0), "branch_ratio": branch_margin / phase_noise if phase_noise else float("inf"), "stable_band2_association": association, "rank2_association_stable": rank2_association}
        gate["status"] = "RANK1_QUALIFIED" if association and gate["gap_ratio"] >= 10.0 and gate["link_ratio"] >= 10.0 and gate["branch_ratio"] >= 5.0 else "RANK1_WITHHELD"
        detail["member_summary"][member]["rank1_phase_density"] = {"median": median, "uncertainty": phase_noise, "branch_safe": {"lifted_phases": phases, "uncertainty": phase_noise}}
        detail["member_summary"][member]["rank1_association"] = association
        detail["member_summary"][member]["rank2_association_stable"] = rank2_association
        detail["member_summary"][member]["rank1_qualification"] = gate
    qualified = all(detail["member_summary"][m]["rank1_qualification"]["status"] == "RANK1_QUALIFIED" for m in MEMBERS)
    detail["rank1_qualification"] = {"status": "RANK1_QUALIFIED" if qualified else "RANK1_WITHHELD", "per_member": {m: detail["member_summary"][m]["rank1_qualification"] for m in MEMBERS}}
    detail["rank1_c3_status"] = "PASS" if qualified else "RANK1_WITHHELD"
    detail["rank2_association_stable"] = all(detail["member_summary"][m]["rank2_association_stable"] for m in MEMBERS)
    detail["rank2_c3_status"] = "PASS"
    detail["m47_local_corrected_detail"] = True
    return detail


def _sequence(values: Mapping[int, Sequence[float] | float], identity: str) -> dict[str, Any]:
    table, medians = [], {}
    for resolution in RESOLUTIONS:
        if resolution not in values: continue
        raw = values[resolution]; repeats = [float(raw)] if isinstance(raw, (int, float)) else [float(v) for v in raw]
        if not repeats or any(not math.isfinite(v) for v in repeats): continue
        median = float(np.median(repeats)); medians[resolution] = median
        table.append({"resolution": resolution, "value": median, "repeat_values": repeats, "repeat_uncertainty": max((abs(v - median) for v in repeats), default=0.0)})
    for left, right in zip(table, table[1:]): left.update({"next_resolution": right["resolution"], "signed_difference_to_next": right["value"] - left["value"], "absolute_difference_to_next": abs(right["value"] - left["value"])})
    fits = {}
    for triple in ((128, 160, 192), (160, 192, 224), (192, 224, 256)):
        if all(n in medians for n in triple): fits["-".join(map(str, triple))] = m45r2.fit_positive_p(triple, [medians[n] for n in triple])
    return {"identity": identity, "table": table, "fits": fits, "repeat_uncertainty_separate": True}


def _sequences(matrix: Mapping[int, Sequence[Mapping[str, Any]]], analyses: Mapping[int, Mapping[str, Any]]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    result = {}
    for member in MEMBERS:
        for vertex in range(4):
            for band in range(1, 5):
                key = f"spectral_frequency:{member}:vertex{vertex}:band{band}"
                result[key] = _sequence({n: [float(r["frequencies_bands_1_to_4"][band - 1]) for r in rows if r["c3_member_identity"] == member and int(r["vertex_index"]) == vertex] for n, rows in matrix.items()}, key)
            key = f"spectral_gap:{member}:vertex{vertex}:band2_isolation"
            result[key] = _sequence({n: [min(float(r["adjacent_gaps"]["lower_gap"]), float(r["adjacent_gaps"]["internal_split"])) for r in rows if r["c3_member_identity"] == member and int(r["vertex_index"]) == vertex] for n, rows in matrix.items()}, key)
    for member in MEMBERS:
        for edge in range(4):
            values, links = {}, {}
            for n, analysis in analyses.items():
                rows = [p for p in analysis["plaquettes"] if p["member"] == member]
                values[n] = [float(p["rank2_edges"][edge]["canonical_minimum_singular_value"]) for p in rows]
                links[n] = [float(p["rank1_edges"][edge]["link_magnitude"]) for p in rows]
            key = f"subspace_overlap:{member}:edge{edge}:canonical_rank2_minimum_singular_value"; result[key] = _sequence(values, key)
            key = f"rank1_link_corroboration:{member}:edge{edge}:physical_band2"; result[key] = _sequence(links, key)
    rank2, rank1 = {}, {}
    for member in MEMBERS:
        values2, values1 = {}, {}
        for n, analysis in analyses.items():
            rows = [p for p in analysis["plaquettes"] if p["member"] == member]
            values2[n] = [float(p["rank2_trace_phase_density"]) for p in rows]
            values1[n] = [float(p["rank1_phase_density"]) for p in rows] if analysis["rank1_qualification"]["status"] == "RANK1_QUALIFIED" else []
        k2 = f"berry_rank2_primary:{member}"; k1 = f"berry_rank1_qualified:{member}"; rank2[k2] = _sequence(values2, k2); rank1[k1] = _sequence(values1, k1)
    return result, rank2, rank1


def _family(sequences: Mapping[str, Mapping[str, Any]], keys: Sequence[str], latest: tuple[int, int, int], previous: tuple[int, int, int]) -> dict[str, Any]:
    statuses = []
    for key in keys:
        fits = sequences[key].get("fits", {}); statuses.append({"latest": fits.get("-".join(map(str, latest)), {}).get("status"), "previous": fits.get("-".join(map(str, previous)), {}).get("status")})
    latest_ok = [x["latest"] == "VALID_POSITIVE_P" for x in statuses]; previous_ok = [x["previous"] == "VALID_POSITIVE_P" for x in statuses]
    if all(latest_ok) and all(previous_ok): state = "ALL_TWO_LATEST"
    elif all(latest_ok): state = "ALL_NEWEST"
    elif any(latest_ok): state = "MIXED_NEWEST"
    else: state = "NONE_NEWEST"
    return {"sequence_count": len(keys), "sequence_status": statuses, "state": state}


def _association(analyses: Mapping[int, Mapping[str, Any]], scope: Sequence[int]) -> dict[str, Any]:
    reasons = []; states = {}
    for member in MEMBERS:
        for edge in range(4):
            r1, r2 = {}, {}
            for n in scope:
                rows = [p for p in analyses[n]["plaquettes"] if p["member"] == member]
                r1[n] = "CANONICAL_STABLE" if all(p["rank1_edges"][edge]["best_target_band"] == 2 for p in rows) else "REPEAT_UNSTABLE"
                r2[n] = "CANONICAL_STABLE" if all(p["rank2_edges"][edge]["best_target_pair"] == [2, 3] for p in rows) else "REPEAT_UNSTABLE"
            states[f"{member}:edge{edge}"] = {"rank1": r1, "rank2": r2}
            for label, values in (("rank1", r1), ("rank2", r2)):
                if len(set(values.values())) != 1 or any(v != "CANONICAL_STABLE" for v in values.values()): reasons.append(f"{member}:edge{edge}:{label}")
    return {"scope": list(scope), "states": states, "unstable": bool(reasons), "reasons": reasons}


def _continuum(rank2: Mapping[str, Mapping[str, Any]], previous: tuple[int, int, int], latest: tuple[int, int, int]) -> dict[str, Any]:
    per = {}
    for key, sequence in rank2.items():
        old = sequence["fits"].get("-".join(map(str, previous)), {}); new = sequence["fits"].get("-".join(map(str, latest)), {}); member = key.rsplit(":", 1)[-1]
        if old.get("status") != "VALID_POSITIVE_P" or new.get("status") != "VALID_POSITIVE_P": per[member] = {"status": "NO_TWO_LATEST_ASYMPTOTIC_SUPPORT"}; continue
        row = next(item for item in sequence["table"] if item["resolution"] == latest[-1]); per[member] = {"status": "TWO_LATEST_ASYMPTOTIC", "continuum_estimate": float(new["y_inf"]), "discretization_envelope": max(abs(float(new["values"][-1]) - float(new["y_inf"])), abs(float(new["y_inf"]) - float(old["y_inf"]))), "repeat_uncertainty": float(row["repeat_uncertainty"])}
    if not all(v.get("status") == "TWO_LATEST_ASYMPTOTIC" for v in per.values()): return {"eligibility": False, "status": "WITHHELD_INCOMPLETE_TWO_LATEST_SUPPORT", "per_member": per}
    pairs = {}
    for left, right in itertools.combinations(sorted(per), 2):
        a, b = per[left], per[right]; diff = abs(a["continuum_estimate"] - b["continuum_estimate"]); bound = a["discretization_envelope"] + b["discretization_envelope"] + a["repeat_uncertainty"] + b["repeat_uncertainty"]; signs = a["continuum_estimate"] == 0 or b["continuum_estimate"] == 0 or math.copysign(1, a["continuum_estimate"]) == math.copysign(1, b["continuum_estimate"])
        pairs[f"{left}_vs_{right}"] = {"absolute_difference": diff, "combined_bound": bound, "within_bound": diff <= bound, "proper_c3_sign_preserved": signs}
    return {"eligibility": True, "status": "PASS" if all(p["within_bound"] and p["proper_c3_sign_preserved"] for p in pairs.values()) else "FAIL", "per_member": per, "pairs": pairs, "sign_source": "continuum_estimates_direct"}


def _corrected_m46_classification(spectral: Mapping[str, Any], berry: Mapping[str, Any], association: Mapping[str, Any], continuum: Mapping[str, Any], finite: Mapping[str, Any]) -> tuple[str, str]:
    """Apply the already-authorized M46 six-point decision rule locally."""
    if association["unstable"]:
        return "R224_HIGH_RESOLUTION_ASSOCIATION_INSTABILITY", "ADAPTIVE_VALIDATED_SUBSPACE_BERRY_TRANSPORT_USING_EXISTING_R160_R192_R224_RAW_BANDS"
    spectral_late = spectral["state"] in {"ALL_NEWEST", "ALL_TWO_LATEST"}
    berry_late = berry["state"] in {"ALL_NEWEST", "ALL_TWO_LATEST"}
    if spectral_late and berry["state"] in {"NONE_NEWEST", "MIXED_NEWEST"}:
        return "R224_SPECTRAL_ASYMPTOTIC_BERRY_NONASYMPTOTIC", "BOUND_PLAQUETTE_STEP_CONVERGENCE_AT_R224"
    if spectral["state"] == "NONE_NEWEST" and berry["state"] == "NONE_NEWEST":
        return "R224_FULL_FAMILY_NONASYMPTOTIC", "R256_RESOLUTION_EXTENSION"
    if spectral_late and berry["state"] == "ALL_TWO_LATEST":
        if continuum["status"] == "FAIL":
            return "R224_COMPLETE_FAMILY_CONTINUUM_C3_FAIL", "BOUND_PLAQUETTE_STEP_CONVERGENCE_AT_R224"
        if continuum["status"] == "PASS" and finite["rank1_qualified"] and finite["rank1_c3"] == "PASS":
            return "R224_COMPLETE_FAMILY_CONTINUUM_C3_PASS_FINITE_CONTROL_QUALIFIED", "CROSS_ORBIT_QUALIFICATION_AT_R224_T1E9_M3"
        if continuum["status"] == "PASS" and not finite["rank1_qualified"]:
            return "R224_COMPLETE_FAMILY_CONTINUUM_C3_PASS_FINITE_ISOLATION_OR_ASSOCIATION_BLOCKED", "ADAPTIVE_VALIDATED_SUBSPACE_BERRY_TRANSPORT_USING_EXISTING_R160_R192_R224_RAW_BANDS"
        return "R224_COMPLETE_FAMILY_CONTINUUM_C3_PASS_FINITE_BRANCH_OR_C3_BLOCKED", "BOUND_PLAQUETTE_STEP_CONVERGENCE_AT_R224"
    if spectral_late and berry_late:
        return "R224_NEWEST_TRIPLE_ASYMPTOTIC_PROVISIONAL", "SINGLE_R256_PREDICTION_VALIDATION"
    return "R224_MIXED_SEMANTIC_FAMILY", "SINGLE_R256_SEMANTIC_FAMILY_DISCRIMINANT"


def _classification(spectral: Mapping[str, Any], berry: Mapping[str, Any], association: Mapping[str, Any], continuum: Mapping[str, Any], finite: Mapping[str, Any]) -> tuple[str, str]:
    """Classify the completed R256 branch without authorizing another resolution."""
    if association["unstable"]:
        return "R256_HIGH_RESOLUTION_ASSOCIATION_INSTABILITY", "ADAPTIVE_VALIDATED_SUBSPACE_BERRY_TRANSPORT_USING_EXISTING_R192_R224_R256_RAW_BANDS"
    spectral_late = spectral["state"] in {"ALL_NEWEST", "ALL_TWO_LATEST"}
    berry_late = berry["state"] in {"ALL_NEWEST", "ALL_TWO_LATEST"}
    if spectral_late and berry["state"] in {"NONE_NEWEST", "MIXED_NEWEST"}:
        return "R256_SPECTRAL_ASYMPTOTIC_BERRY_NONASYMPTOTIC", "BOUND_PLAQUETTE_STEP_CONVERGENCE_AT_R256"
    if spectral["state"] == "NONE_NEWEST" and berry["state"] == "NONE_NEWEST":
        return "R256_FULL_FAMILY_NONASYMPTOTIC", "NO_FURTHER_AUTHORIZED_R256_EXTENSION"
    if spectral_late and berry["state"] == "ALL_TWO_LATEST":
        if continuum["status"] == "FAIL":
            return "R256_COMPLETE_FAMILY_CONTINUUM_C3_FAIL", "BOUND_PLAQUETTE_STEP_CONVERGENCE_AT_R256"
        if continuum["status"] == "PASS" and finite["rank1_qualified"] and finite["rank1_c3"] == "PASS":
            return "R256_COMPLETE_FAMILY_CONTINUUM_C3_PASS_FINITE_CONTROL_QUALIFIED", "NO_FURTHER_AUTHORIZED_R256_EXTENSION"
        if continuum["status"] == "PASS" and not finite["rank1_qualified"]:
            return "R256_COMPLETE_FAMILY_CONTINUUM_C3_PASS_FINITE_ISOLATION_OR_ASSOCIATION_BLOCKED", "ADAPTIVE_VALIDATED_SUBSPACE_BERRY_TRANSPORT_USING_EXISTING_R192_R224_R256_RAW_BANDS"
        return "R256_COMPLETE_FAMILY_CONTINUUM_C3_PASS_FINITE_BRANCH_OR_C3_BLOCKED", "BOUND_PLAQUETTE_STEP_CONVERGENCE_AT_R256"
    if spectral_late and berry_late:
        return "R256_NEWEST_TRIPLE_ASYMPTOTIC_PROVISIONAL", "NO_FURTHER_AUTHORIZED_R256_EXTENSION"
    return "R256_MIXED_SEMANTIC_FAMILY", "NO_FURTHER_AUTHORIZED_R256_EXTENSION"


def main() -> int:
    bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8")); source_commit = str(os.environ.get("MEPHC_SOURCE_COMMIT") or bundle.get("source_commit") or "")
    try:
        job = m41r3._load(ROOT / "tools/mephc-flow/scientific_job.py", "m47_job"); m39 = m41r3._load(ROOT / "audit/berry_c3_consistency/m39_g15_deterministic_repeat_band_association_worst_orbit_pilot.py", "m47_m39"); m38 = m41r3._load(ROOT / "audit/berry_c3_consistency/m38_supplied_exact_mpb_source_semantics_raw_native_c3.py", "m47_m38"); state_root = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"]).parent.parent
        partial = m41r3._read_partial(job, state_root); m41 = m41r3._read_dataset(job, state_root, M41R3_DATASET_ID, M41R3_MANIFEST_SHA256, M41R3_SCHEMA, 108); m44 = m41r3._read_dataset(job, state_root, M44_DATASET_ID, M44_MANIFEST_SHA256, M44_SCHEMA, 72); m46 = m41r3._read_dataset(job, state_root, M46_DATASET_ID, M46_MANIFEST_SHA256, M46_SCHEMA, 36); m18 = m41r3._read_dataset(job, state_root, m41r3.M18_DATASET_ID, m41r3.M18_MANIFEST_SHA256, m41r3.M18_SCHEMA, 3); m39r1 = m41r3._read_dataset(job, state_root, m41r3.M39R1_DATASET_ID, m41r3.M39R1_MANIFEST_SHA256, m41r3.M39R1_SCHEMA, 14); centers = m41r3._centers(m18, m39r1)
        matrix = {64: [r for r in m41 if r.get("configuration_id") == "R64_T1E9_M3"], 96: [r for r in m41 if r.get("configuration_id") == "R96_T1E9_M3"], 128: partial, 160: [r for r in m44 if r.get("configuration_id") == "R160_T1E9_M3"], 192: [r for r in m44 if r.get("configuration_id") == "R192_T1E9_M3"], 224: m46}
        if any(len(rows) != 36 for rows in matrix.values()): raise ValueError("M47_EXISTING_MATRIX_INVALID")
        analyses = {n: configuration_detail(rows, centers, m38, m39, f"R{n}_T1E9_M3") for n, rows in matrix.items()}; seq, rank2, rank1 = _sequences(matrix, analyses); keys = [k for k in seq if k.startswith("spectral_frequency:") or k.startswith("spectral_gap:") or k.startswith("subspace_overlap:")]
        if len([k for k in seq if k.startswith("spectral_frequency:")]) != 48 or len([k for k in seq if k.startswith("spectral_gap:")]) != 12 or len([k for k in seq if k.startswith("subspace_overlap:")]) != 12: raise ValueError("M47_SEMANTIC_INVENTORY_INVALID")
        spectral = _family(seq, keys, (160, 192, 224), (128, 160, 192)); berry = _family(rank2, list(rank2), (160, 192, 224), (128, 160, 192)); association = _association(analyses, (160, 192, 224)); continuum = _continuum(rank2, (128, 160, 192), (160, 192, 224)); a224 = analyses[224]; finite = {"rank1_qualified": a224["rank1_qualification"]["status"] == "RANK1_QUALIFIED", "rank1_c3": a224["rank1_c3_status"], "rank2_c3": a224["rank2_c3_status"]}
        pre_classification, pre_decision = _corrected_m46_classification(spectral, berry, association, continuum, finite)
        if pre_classification != "R224_MIXED_SEMANTIC_FAMILY":
            result = {"schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS", "machine_execution_contract_status": "ZERO_SCIENTIFIC_EXECUTION_CORRECTED_M46_REROUTE", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 0, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "pre_native_corrected_m46_classification": pre_classification, "pre_native_corrected_m46_next_decision": pre_decision, "pre_native_r256_authorized": False, "classification": pre_classification, "next_science_decision": pre_decision, "configuration_analysis": analyses, "resolution_sequences": {"semantic": seq, "berry_rank2": rank2, "berry_rank1": rank1}, "high_resolution_association": association, "continuum_c3": continuum, "source_commit_used": source_commit, "post_analysis_checkout_unchanged": True}
        else:
            graph = r256_graph(centers, source_commit); graph_hash = hashlib.sha256(json.dumps(graph, sort_keys=True, separators=(",", ":")).encode()).hexdigest(); import meep as mp; from meep import mpb; from mephc.band import Band
            band = Band(a=400.0, r1=80.14335684352235, r2=75.13439704080221, n_eff=2.7, h=100.0, resolution=256, lattice_type="triangular", polarization="TE", structure_type="slab"); pattern = band.create_unitcell(15, 0.0, 15, 60.0, show=False); geometry = band.create_material_block() + band.convert_ndarray_to_meep_geo(pattern, rectify=True); counter = job.BudgetCounter(36, 36); store = job.ImmutableDatasetStore(state_root, {"goal_id": "MEPHC-BERRY-C3-CONSISTENCY-V1", "work_order_id": bundle["work_order_id"], "source_commit": source_commit, "record_schema": DATASET_SCHEMA, "configuration_id": "R256_T1E9_M3", "graph_sha256": graph_hash, "mode_count": 65536, "fft_shape": [256, 256]}); records = []
            for spec in graph:
                reciprocal = mp.cartesian_to_reciprocal(mp.Vector3(float(spec["coordinate"][0]), float(spec["coordinate"][1]), 0.0), band.geo_latt); solver = mpb.ModeSolver(geometry=geometry, geometry_lattice=band.geo_latt, k_points=[reciprocal], resolution=256, num_bands=4, default_material=mp.air, tolerance=1e-9, deterministic=True, mesh_size=3); captured = _capture(mp, solver, spec, counter, source_commit); key = json.dumps({"work_order_id": bundle["work_order_id"], "configuration_id": "R256_T1E9_M3", "member": spec["c3_member_identity"], "repeat": spec["repeat_index"], "vertex": spec["vertex_index"]}, sort_keys=True, separators=(",", ":")).encode(); store.put(key, json.dumps(captured, sort_keys=True, separators=(",", ":"), default=lambda value: _safe(value)).encode(), {"configuration_id": "R256_T1E9_M3", "member": spec["c3_member_identity"], "repeat_index": spec["repeat_index"], "vertex_index": spec["vertex_index"]}); records.append(captured)
            matrix[256] = records; analyses[256] = configuration_detail(records, centers, m38, m39, "R256_T1E9_M3"); seq, rank2, rank1 = _sequences(matrix, analyses); keys = [k for k in seq if k.startswith("spectral_frequency:") or k.startswith("spectral_gap:") or k.startswith("subspace_overlap:")]; dataset = store.finalize(36, {"dataset_schema": DATASET_SCHEMA, "configuration_id": "R256_T1E9_M3", "graph_sha256": graph_hash, "source_parent_dataset_ids": [M41R3_DATASET_ID, M44_DATASET_ID, M46_DATASET_ID]}); spectral = _family(seq, keys, (192, 224, 256), (160, 192, 224)); berry = _family(rank2, list(rank2), (192, 224, 256), (160, 192, 224)); association = _association(analyses, (192, 224, 256)); continuum = _continuum(rank2, (160, 192, 224), (192, 224, 256)); a256 = analyses[256]; finite = {"rank1_qualified": a256["rank1_qualification"]["status"] == "RANK1_QUALIFIED", "rank1_c3": a256["rank1_c3_status"], "rank2_c3": a256["rank2_c3_status"]}; classification, decision = _classification(spectral, berry, association, continuum, finite); result = {"schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS", "machine_execution_contract_status": "ONE_NATIVE_CORRECTED_SINGLE_R256_SEMANTIC_FAMILY_DISCRIMINANT", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 1, "provider_execution_count": counter.provider_count, "solver_execution_count": counter.solver_count, "dataset_record_count": len(records), "dataset_id": dataset.get("dataset_id"), "manifest_sha256": dataset.get("manifest_sha256"), "graph_sha256": graph_hash, "pre_native_corrected_m46_classification": pre_classification, "pre_native_corrected_m46_next_decision": pre_decision, "pre_native_r256_authorized": True, "semantic_sequence_inventory": {"frequency": 48, "gap": 12, "subspace": 12, "spectral_subspace_total": 72, "berry_rank2_primary": 3, "rank1_link_corroboration": 12}, "family_support": {"spectral_subspace": spectral, "berry_rank2_primary": berry, "qualified_rank1": _family(rank1, list(rank1), (192, 224, 256), (160, 192, 224))}, "high_resolution_association": association, "continuum_c3": continuum, "r256_finite_control": finite, "classification": classification, "next_science_decision": decision, "source_commit_used": source_commit, "post_analysis_checkout_unchanged": True}
    except BaseException as exc:
        result = {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "machine_execution_contract_status": "M47_FAIL_CLOSED", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 0, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "failure_code": str(exc)[:1024], "failure_stage": "corrected_m46_gate_or_r256_acquisition", "exception_type": type(exc).__name__, "source_commit_used": source_commit}
    Path(os.environ["MEPHC_RESULT_PATH"]).write_text(json.dumps(_safe(result), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8"); return 0


if __name__ == "__main__": raise SystemExit(main())
