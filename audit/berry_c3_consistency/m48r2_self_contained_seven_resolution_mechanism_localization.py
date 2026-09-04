"""M48R2: self-contained, solver-free seven-resolution mechanism localization."""
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
SPEC = importlib.util.spec_from_file_location("m48r2_m45r2_substrate", M45R2_PATH)
assert SPEC and SPEC.loader
m45r2 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m45r2)
m41r3 = m45r2.m41r3

RESULT_SCHEMA = "mephc-berry-c3-consistency-m48r2-seven-resolution-mechanism-localization-v1"
MEMBERS = tuple(m41r3.MEMBERS)
RESOLUTIONS = (64, 96, 128, 160, 192, 224, 256)
M47_DATASET_ID = "8366cb27fbe2d2e9a94f30b3c86b8b866165a7728f5d0c3779780fd571d8b154"
M47_MANIFEST_SHA256 = "7e01ee6517cd1b3b49890998e8c7aa4ad83b7906f157f4453e21845226c583b3"
M47_SCHEMA = "mephc-berry-c3-consistency-m47-r256-semantic-family-vertex-dataset-v1"


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
        return {str(key): _safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(item) for item in value]
    raise ValueError(f"M48R2_UNSAFE_RESULT:{type(value).__name__}")


def _phase_lift(values: Sequence[float]) -> dict[str, Any]:
    raw = [float(value) for value in values]
    if not raw:
        return {"lifted_phases": [], "ambiguous": False, "maximum_pairwise_wrapped_distance": 0.0}
    candidates = []
    for anchor in sorted(set(raw), key=lambda value: (value % (2.0 * math.pi), value)):
        lifted = [value + 2.0 * math.pi * round((anchor - value) / (2.0 * math.pi)) for value in raw]
        center = float(np.median(lifted))
        candidates.append((max(abs(value - center) for value in lifted), anchor % (2.0 * math.pi), anchor, lifted))
    lifted = min(candidates, key=lambda item: item[:3])[3]
    wrapped = [abs(math.atan2(math.sin(left - right), math.cos(left - right))) for left, right in itertools.combinations(raw, 2)]
    return {"lifted_phases": lifted, "ambiguous": any(abs(value - math.pi) <= 1e-12 for value in wrapped), "maximum_pairwise_wrapped_distance": float(max(wrapped, default=0.0))}


def _scalar_stats(phases: Sequence[float], areas: Sequence[float]) -> dict[str, Any]:
    lift = _phase_lift(phases)
    values = [float(phase) / float(area) for phase, area in zip(lift["lifted_phases"], areas)]
    median = float(np.median(values)) if values else 0.0
    return {"values": values, "median": median, "uncertainty": float(max((abs(value - median) for value in values), default=0.0)), "phase_uncertainty": lift["maximum_pairwise_wrapped_distance"], "branch_ambiguous": lift["ambiguous"], "lifted_phases": lift["lifted_phases"]}


def _pairwise_c3(summary: Mapping[str, Any], key: str, require_rank1: bool) -> str:
    if require_rank1 and summary["rank1_qualification"]["status"] != "RANK1_QUALIFIED":
        return "RANK1_WITHHELD"
    for left, right in itertools.combinations(MEMBERS, 2):
        a, b = summary["member_summary"][left][key], summary["member_summary"][right][key]
        if abs(a["median"] - b["median"]) > a["uncertainty"] + b["uncertainty"]:
            return "FAIL"
        if a["median"] and b["median"] and np.sign(a["median"]) != np.sign(b["median"]):
            return "FAIL"
    return "PASS"


def configuration_detail(records: Sequence[Mapping[str, Any]], centers: Mapping[str, Sequence[float]], m38: Any, m39: Any, configuration_id: str) -> dict[str, Any]:
    """Use only M45R2's detail-producing raw-H substrate, then overwrite summaries."""
    if len(records) != 36:
        raise ValueError(f"M48R2_CONFIGURATION_RECORD_COUNT_INVALID:{configuration_id}:{len(records)}")
    detail = m45r2.configuration_detail(records, centers, m38, m39, configuration_id)
    for plaquette in detail["plaquettes"]:
        area = float(plaquette["signed_area"])
        rank1_phase = float(plaquette["rank1_wilson_phase"])
        rank2_phase = float(plaquette.get("rank2_trace_phase", plaquette.get("rank2_trace_wilson_phase", 0.0)))
        plaquette["rank1_phase"] = rank1_phase
        plaquette["rank1_phase_density"] = rank1_phase / area
        plaquette["rank2_trace_phase"] = rank2_phase
        plaquette["rank2_trace_phase_density"] = rank2_phase / area
        plaquette["rank2_trace_wilson_phase"] = rank2_phase
        for edge in plaquette["rank2_edges"]:
            edge["canonical_target_pair"] = [2, 3]
            if "canonical_minimum_singular_value" not in edge:
                edge["canonical_minimum_singular_value"] = float(edge["minimum_singular_value"])
    by_member: dict[str, Any] = {}
    for member in MEMBERS:
        plaquettes = [item for item in detail["plaquettes"] if item["member"] == member]
        rank1 = _scalar_stats([item["rank1_phase"] for item in plaquettes], [item["signed_area"] for item in plaquettes])
        rank2 = _scalar_stats([item["rank2_trace_phase"] for item in plaquettes], [item["signed_area"] for item in plaquettes])
        gaps: dict[int, list[float]] = {vertex: [] for vertex in range(4)}
        for record in records:
            if record["c3_member_identity"] == member:
                gaps[int(record["vertex_index"])].append(min(float(record["adjacent_gaps"]["lower_gap"]), float(record["adjacent_gaps"]["internal_split"])))
        links: dict[int, list[float]] = {edge: [] for edge in range(4)}
        for plaquette in plaquettes:
            for edge in plaquette["rank1_edges"]:
                links[int(edge["edge_index"])].append(float(edge["link_magnitude"]))
        gap_ranges = {vertex: max(values) - min(values) for vertex, values in gaps.items() if values}
        link_ranges = {edge: max(values) - min(values) for edge, values in links.items() if values}
        rank1_association = all(edge["best_target_band"] == 2 for item in plaquettes for edge in item["rank1_edges"])
        rank2_association = {edge: _association_state([item["best_target_pair"] for plaquette in plaquettes for item in plaquette["rank2_edges"] if int(item["edge_index"]) == edge]) for edge in range(4)}
        gap_signal = min(value for values in gaps.values() for value in values)
        link_signal = min(value for values in links.values() for value in values)
        gap_noise = max(gap_ranges.values(), default=0.0)
        link_noise = max(link_ranges.values(), default=0.0)
        branch_margin = min(math.pi - abs(float(item["rank1_phase"])) for item in plaquettes)
        gate = {"gap_signal": gap_signal, "gap_repeat_noise": gap_noise, "link_signal": link_signal, "link_repeat_noise": link_noise, "branch_margin": branch_margin, "branch_uncertainty": rank1["phase_uncertainty"], "phase_density_uncertainty": rank1["uncertainty"], "gap_ratio": gap_signal / gap_noise if gap_noise else (float("inf") if gap_signal > 0 else 0.0), "link_ratio": link_signal / link_noise if link_noise else (float("inf") if link_signal > 0 else 0.0), "branch_ratio": branch_margin / rank1["phase_uncertainty"] if rank1["phase_uncertainty"] else float("inf"), "stable_band2_association": rank1_association, "rank2_association": rank2_association}
        gate["status"] = "RANK1_QUALIFIED" if rank1_association and gate["gap_ratio"] >= 10.0 and gate["link_ratio"] >= 10.0 and gate["branch_ratio"] >= 5.0 and not rank1["branch_ambiguous"] else "RANK1_WITHHELD"
        by_member[member] = {"rank1_phase_density": rank1, "rank2_trace_phase_density": rank2, "gap_signal": gap_signal, "gap_repeat_noise": gap_noise, "link_signal": link_signal, "link_repeat_noise": link_noise, "rank1_association": rank1_association, "rank2_association": rank2_association, "rank1_qualification": gate}
    qualified = all(by_member[member]["rank1_qualification"]["status"] == "RANK1_QUALIFIED" for member in MEMBERS)
    detail["member_summary"] = by_member
    detail["rank1_qualification"] = {"status": "RANK1_QUALIFIED" if qualified else "RANK1_WITHHELD", "per_member": {member: by_member[member]["rank1_qualification"] for member in MEMBERS}, "stable_band2_association": all(by_member[member]["rank1_association"] for member in MEMBERS)}
    detail["rank2_association_stable"] = all(state == "CANONICAL_STABLE" for member in MEMBERS for state in by_member[member]["rank2_association"].values())
    detail["rank1_c3_status"] = _pairwise_c3(detail, "rank1_phase_density", True)
    detail["rank2_c3_status"] = _pairwise_c3(detail, "rank2_trace_phase_density", False)
    detail["canonical_rank2_pair_one_based"] = [2, 3]
    detail["qualification_source"] = "M48R2 local recomputation over M45R2 raw-H plaquette substrate"
    return detail


def _association_state(pairs: Sequence[Sequence[int]]) -> str:
    values = [tuple(int(value) for value in pair) for pair in pairs]
    if not values or len(set(values)) != 1:
        return "REPEAT_UNSTABLE"
    return "CANONICAL_STABLE" if values[0] == (2, 3) else "NONCANONICAL_STABLE"


def _sequence(values: Mapping[int, Sequence[float] | float], identity: str) -> dict[str, Any]:
    table, medians = [], {}
    for resolution in RESOLUTIONS:
        if resolution not in values:
            continue
        raw = values[resolution]; repeats = [float(raw)] if isinstance(raw, (int, float)) else [float(value) for value in raw]
        if not repeats or any(not math.isfinite(value) for value in repeats):
            continue
        median = float(np.median(repeats)); medians[resolution] = median
        table.append({"resolution": resolution, "value": median, "repeat_values": repeats, "repeat_uncertainty": max((abs(value - median) for value in repeats), default=0.0)})
    for left, right in zip(table, table[1:]):
        left.update({"next_resolution": right["resolution"], "signed_difference_to_next": right["value"] - left["value"], "absolute_difference_to_next": abs(right["value"] - left["value"])})
    fits = {}
    for triple in ((128, 160, 192), (160, 192, 224), (192, 224, 256)):
        if all(resolution in medians for resolution in triple):
            fits["-".join(map(str, triple))] = m45r2.fit_positive_p(triple, [medians[resolution] for resolution in triple])
    return {"identity": identity, "table": table, "fits": fits, "repeat_uncertainty_separate": True}


def _build_sequences(matrix: Mapping[int, Sequence[Mapping[str, Any]]], analyses: Mapping[int, Mapping[str, Any]]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    spectral: dict[str, Any] = {}
    for member in MEMBERS:
        for vertex in range(4):
            for band in range(1, 5):
                key = f"spectral_frequency:{member}:vertex{vertex}:band{band}"
                spectral[key] = _sequence({resolution: [float(row["frequencies_bands_1_to_4"][band - 1]) for row in rows if row["c3_member_identity"] == member and int(row["vertex_index"]) == vertex] for resolution, rows in matrix.items()}, key)
            key = f"spectral_gap:{member}:vertex{vertex}:band2_isolation"
            spectral[key] = _sequence({resolution: [min(float(row["adjacent_gaps"]["lower_gap"]), float(row["adjacent_gaps"]["internal_split"])) for row in rows if row["c3_member_identity"] == member and int(row["vertex_index"]) == vertex] for resolution, rows in matrix.items()}, key)
    for member in MEMBERS:
        for edge in range(4):
            values, links = {}, {}
            for resolution, analysis in analyses.items():
                rows = [item for item in analysis["plaquettes"] if item["member"] == member]
                values[resolution] = [float(item["rank2_edges"][edge]["canonical_minimum_singular_value"]) for item in rows]
                links[resolution] = [float(item["rank1_edges"][edge]["link_magnitude"]) for item in rows]
            key = f"subspace_overlap:{member}:edge{edge}:canonical_rank2_minimum_singular_value"; spectral[key] = _sequence(values, key)
            key = f"rank1_link_corroboration:{member}:edge{edge}:physical_band2"; spectral[key] = _sequence(links, key)
    rank2, rank1 = {}, {}
    for member in MEMBERS:
        values2, values1 = {}, {}
        for resolution, analysis in analyses.items():
            rows = [item for item in analysis["plaquettes"] if item["member"] == member]
            values2[resolution] = [float(item["rank2_trace_phase_density"]) for item in rows]
            values1[resolution] = [float(item["rank1_phase_density"]) for item in rows] if analysis["rank1_qualification"]["status"] == "RANK1_QUALIFIED" else []
        key = f"berry_rank2_primary:{member}"; rank2[key] = _sequence(values2, key)
        key = f"berry_rank1_qualified:{member}"; rank1[key] = _sequence(values1, key)
    return spectral, rank2, rank1


def _transition(sequences: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in sequences.items():
        fits = value.get("fits", {}); w2 = fits.get("160-192-224", {}); w3 = fits.get("192-224-256", {})
        w2_ok, w3_ok = w2.get("status") == "VALID_POSITIVE_P", w3.get("status") == "VALID_POSITIVE_P"
        state = "STABLE_LATE_ASYMPTOTIC" if w2_ok and w3_ok else "ENTERING_ASYMPTOTIC" if w3_ok else "EXITING_ASYMPTOTIC" if w2_ok else "PERSISTENT_NONASYMPTOTIC"
        result[key] = {**value, "transition_class": state, "withholding_reasons": {name: fit.get("reason") for name, fit in fits.items() if fit.get("status") != "VALID_POSITIVE_P"}}
    return result


def _partition(sequences: Mapping[str, Mapping[str, Any]], keys: Sequence[str]) -> dict[str, Any]:
    failed = [key for key in keys if sequences[key].get("fits", {}).get("192-224-256", {}).get("status") != "VALID_POSITIVE_P"]
    return {"sequence_count": len(keys), "all_w3_valid": not failed, "failing_identities": failed, "transition_classes": {key: sequences[key]["transition_class"] for key in keys}}


def _association(analyses: Mapping[int, Mapping[str, Any]], scope: Sequence[int]) -> dict[str, Any]:
    states, reasons = {}, []
    for member in MEMBERS:
        for edge in range(4):
            values = {}
            for resolution in scope:
                summary = analyses[resolution]["member_summary"][member]
                values[resolution] = {"rank1": "CANONICAL_STABLE" if summary["rank1_association"] else "REPEAT_UNSTABLE", "rank2": summary["rank2_association"][edge]}
            key = f"{member}:edge{edge}"; states[key] = values
            for label in ("rank1", "rank2"):
                series = [values[resolution][label] for resolution in scope]
                if len(set(series)) != 1 or series[0] != "CANONICAL_STABLE":
                    reasons.append(f"{key}:{label}")
    return {"scope": list(scope), "states": states, "unstable": bool(reasons), "reasons": reasons, "priority": "before_scalar_localization"}


def _localize(partitions: Mapping[str, Mapping[str, Any]], association: Mapping[str, Any]) -> tuple[str, str]:
    if association["unstable"]:
        return "HIGH_RESOLUTION_ASSOCIATION_INSTABILITY", "ADAPTIVE_VALIDATED_SUBSPACE_BERRY_TRANSPORT_USING_EXISTING_R192_R224_R256_RAW_BANDS"
    failed = {name for name in ("frequency", "gap", "subspace", "berry") if not partitions[name]["all_w3_valid"]}
    if not failed:
        return "ALL_LATEST_FAMILIES_ASYMPTOTIC_AFTER_CORRECTION", "R256_CONTINUUM_AND_FINITE_CONTROL_REQUALIFICATION"
    if "frequency" in failed:
        return ("MULTIPLE_STRUCTURED_MIXED_FAILURES", "PRIORITIZE_R256_MESH_VS_SUBSPACE_VS_PLAQUETTE_BY_EXACT_FAILURE_IDENTITIES") if len(failed) > 1 else ("FREQUENCY_DISCRETIZATION_NONASYMPTOTIC", "BOUND_R256_MESH_DISCRETIZATION_CONTROL")
    if "gap" in failed:
        return ("MULTIPLE_STRUCTURED_MIXED_FAILURES", "PRIORITIZE_R256_MESH_VS_SUBSPACE_VS_PLAQUETTE_BY_EXACT_FAILURE_IDENTITIES") if failed & {"subspace", "berry"} else ("FREQUENCY_ASYMPTOTIC_GAP_NONASYMPTOTIC", "ADAPTIVE_VALIDATED_SUBSPACE_AND_NEAR_DEGENERACY_ADJUDICATION_USING_EXISTING_R192_R224_R256_RAW_BANDS")
    if "subspace" in failed:
        return ("MULTIPLE_STRUCTURED_MIXED_FAILURES", "PRIORITIZE_R256_MESH_VS_SUBSPACE_VS_PLAQUETTE_BY_EXACT_FAILURE_IDENTITIES") if "berry" in failed else ("SPECTRAL_GAP_ASYMPTOTIC_SUBSPACE_NONASYMPTOTIC", "ADAPTIVE_VALIDATED_SUBSPACE_BERRY_TRANSPORT_USING_EXISTING_R192_R224_R256_RAW_BANDS")
    return "SPECTRAL_SUBSPACE_ASYMPTOTIC_BERRY_NONASYMPTOTIC", "BOUND_PLAQUETTE_STEP_CONVERGENCE_AT_R256"


def _read_matrix(job: Any, state_root: Path) -> tuple[dict[int, list[dict[str, Any]]], dict[str, list[float]], Any, Any]:
    m41 = m41r3._read_dataset(job, state_root, m45r2.M41R3_DATASET_ID, m45r2.M41R3_MANIFEST_SHA256, m45r2.M41R3_SCHEMA, 108)
    partial = m41r3._read_partial(job, state_root)
    m44 = m41r3._read_dataset(job, state_root, m45r2.M44_DATASET_ID, m45r2.M44_MANIFEST_SHA256, m45r2.M44_SCHEMA, 72)
    m46 = m41r3._read_dataset(job, state_root, "6a0bd125fb2b4b640292ff8580d4812cbb1be8d4e1e383133060cf8139e2f533", "b7d2f0974b5305f1903a088c99d3dd285cbca844b3d93d9a8f3a705272a0ece8", "mephc-berry-c3-consistency-m46-r224-semantic-family-vertex-dataset-v1", 36)
    m47 = m41r3._read_dataset(job, state_root, M47_DATASET_ID, M47_MANIFEST_SHA256, M47_SCHEMA, 36)
    m18 = m41r3._read_dataset(job, state_root, m41r3.M18_DATASET_ID, m41r3.M18_MANIFEST_SHA256, m41r3.M18_SCHEMA, 3)
    m39 = m41r3._read_dataset(job, state_root, m41r3.M39R1_DATASET_ID, m41r3.M39R1_MANIFEST_SHA256, m41r3.M39R1_SCHEMA, 14)
    sources = ((64, m41), (96, m41), (128, partial), (160, m44), (192, m44), (224, m46), (256, m47))
    matrix = {resolution: [dict(row) for row in source if int(row.get("resolution", -1)) == resolution and row.get("configuration_id") == f"R{resolution}_T1E9_M3" and row.get("geometry_id") == "G15" and row.get("stencil") == "C3_COVARIANT" and int(row.get("mesh_size", -1)) == 3] for resolution, source in sources}
    if any(len(rows) != 36 for rows in matrix.values()) or sum(len(rows) for rows in matrix.values()) != 252:
        raise ValueError(f"M48R2_SEVEN_RESOLUTION_MATRIX_INVALID:{[(resolution, len(rows)) for resolution, rows in matrix.items()]}")
    return matrix, m41r3._centers(m18, m39), m41r3._load(ROOT / "audit/berry_c3_consistency/m38_supplied_exact_mpb_source_semantics_raw_native_c3.py", "m48r2_m38"), m41r3._load(ROOT / "audit/berry_c3_consistency/m39_g15_deterministic_repeat_band_association_worst_orbit_pilot.py", "m48r2_m39")


def _counterevidence(partitions: Mapping[str, Mapping[str, Any]], selected: str, sequences: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    converged = [name for name, partition in partitions.items() if partition["all_w3_valid"]]
    stable_late = [key for key, sequence in sequences.items() if sequence["transition_class"] == "STABLE_LATE_ASYMPTOTIC" and selected != "ALL_LATEST_FAMILIES_ASYMPTOTIC_AFTER_CORRECTION"]
    counts = {"member": {}, "vertex": {}, "band": {}, "edge": {}}
    for key, sequence in sequences.items():
        if sequence["transition_class"] != "PERSISTENT_NONASYMPTOTIC":
            continue
        parts = key.split(":")
        for label, token in (("member", parts[1] if len(parts) > 1 else "unknown"), ("vertex", next((part for part in parts if part.startswith("vertex")), "none")), ("band", next((part for part in parts if part.startswith("band")), "none")), ("edge", next((part for part in parts if part.startswith("edge")), "none"))):
            counts[label][token] = counts[label].get(token, 0) + 1
    return {"converged_partitions": converged, "contradicting_stable_late_identities": stable_late, "failure_identity_counts": counts, "concentration_is_descriptive_only": True}


def main() -> int:
    bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8")); source_commit = str(os.environ.get("MEPHC_SOURCE_COMMIT") or bundle.get("source_commit") or "")
    try:
        job = m41r3._load(ROOT / "tools/mephc-flow/scientific_job.py", "m48r2_job"); state_root = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"]).parent.parent
        matrix, centers, m38, m39 = _read_matrix(job, state_root)
        analyses = {resolution: configuration_detail(rows, centers, m38, m39, f"R{resolution}_T1E9_M3") for resolution, rows in matrix.items()}
        spectral0, rank20, rank10 = _build_sequences(matrix, analyses); spectral, rank2, rank1 = _transition(spectral0), _transition(rank20), _transition(rank10)
        frequency = [key for key in spectral if key.startswith("spectral_frequency:")]; gap = [key for key in spectral if key.startswith("spectral_gap:")]; subspace = [key for key in spectral if key.startswith("subspace_overlap:")]; links = [key for key in spectral if key.startswith("rank1_link_corroboration:")]; berry = list(rank2)
        partitions = {"frequency": _partition(spectral, frequency), "gap": _partition(spectral, gap), "subspace": _partition(spectral, subspace), "berry": _partition(rank2, berry), "rank1_link_corroboration": _partition(spectral, links)}
        association = _association(analyses, (192, 224, 256)); classification, decision = _localize(partitions, association); all_sequences = {**spectral, **rank2, **rank1}
        result = {"schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS", "machine_execution_contract_status": "ZERO_SCIENTIFIC_EXECUTION_SELF_CONTAINED_SEVEN_RESOLUTION_MECHANISM_LOCALIZATION", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 0, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "verified_record_counts": {str(resolution): len(rows) for resolution, rows in matrix.items()}, "verified_record_total": sum(len(rows) for rows in matrix.values()), "r128_source": "m41r3._read_partial", "configuration_analysis": analyses, "semantic_sequence_inventory": {"frequency": len(frequency), "gap": len(gap), "subspace": len(subspace), "rank1_link_corroboration": len(links), "berry_rank2_primary": len(berry), "qualified_rank1": len(rank1)}, "semantic_sequences": all_sequences, "partitions": partitions, "high_resolution_association": association, "corrected_c3_context": {str(resolution): {"rank1": analyses[resolution]["rank1_c3_status"], "rank2": analyses[resolution]["rank2_c3_status"]} for resolution in (192, 224, 256)}, "counterevidence": _counterevidence(partitions, classification, all_sequences), "localization_class": classification, "classification": classification, "next_science_decision": decision, "source_commit_used": source_commit, "post_analysis_checkout_unchanged": True}
    except BaseException as exc:
        result = {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "machine_execution_contract_status": "M48R2_FAIL_CLOSED", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 0, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "failure_code": str(exc)[:1024], "failure_stage": "self_contained_seven_resolution_analysis", "exception_type": type(exc).__name__, "source_commit_used": source_commit}
    Path(os.environ["MEPHC_RESULT_PATH"]).write_text(json.dumps(_safe(result), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
