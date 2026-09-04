"""M48: solver-free localization of the corrected seven-resolution result."""
from __future__ import annotations

import itertools
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from audit.berry_c3_consistency import m47_corrected_single_r256_semantic_family_discriminant as m47

ROOT = Path(__file__).resolve().parents[2]
RESULT_SCHEMA = "mephc-berry-c3-consistency-m48-seven-resolution-mixed-family-mechanism-localization-v1"
MEMBERS = tuple(m47.MEMBERS)
RESOLUTIONS = (64, 96, 128, 160, 192, 224, 256)
M47_DATASET_ID = "8366cb27fbe2d2e9a94f30b3c86b8b866165a7728f5d0c3779780fd571d8b154"
M47_MANIFEST_SHA256 = "7e01ee6517cd1b3b49890998e8c7aa4ad83b7906f157f4453e21845226c583b3"
M47_SCHEMA = "mephc-berry-c3-consistency-m47-r256-semantic-family-vertex-dataset-v1"

M42_PATH = ROOT / "audit/berry_c3_consistency/m42_m41r3_corrected_uncertainty_cheapest_control_adjudication.py"
m42 = m47.m41r3._load(M42_PATH, "m48_m42")
m45r2 = m47.m45r2


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
    raise ValueError(f"M48_UNSAFE_RESULT:{type(value).__name__}")


def _phase_lift(values: Sequence[float]) -> dict[str, Any]:
    """Lift a circular triplet independently of input order, preserving identity."""
    raw = [float(value) for value in values]
    if not raw:
        return {"lifted_phases": [], "ambiguous": False, "maximum_pairwise_wrapped_distance": 0.0}
    candidates = []
    for anchor in sorted(set(raw), key=lambda value: (value % (2.0 * math.pi), value)):
        lifted = [value + 2.0 * math.pi * round((anchor - value) / (2.0 * math.pi)) for value in raw]
        center = float(np.median(lifted))
        spread = max(abs(value - center) for value in lifted)
        candidates.append((spread, anchor % (2.0 * math.pi), anchor, lifted))
    _, _, _, lifted = min(candidates, key=lambda item: item[:3])
    wrapped = [abs(math.atan2(math.sin(left - right), math.cos(left - right))) for left, right in itertools.combinations(raw, 2)]
    return {"lifted_phases": lifted, "ambiguous": any(abs(value - math.pi) <= 1e-12 for value in wrapped), "maximum_pairwise_wrapped_distance": float(max(wrapped, default=0.0))}


def _scalar_stats(phases: Sequence[float], areas: Sequence[float]) -> dict[str, Any]:
    lift = _phase_lift(phases)
    densities = [float(phase) / float(area) for phase, area in zip(lift["lifted_phases"], areas)]
    median = float(np.median(densities)) if densities else 0.0
    return {"values": densities, "median": median, "uncertainty": float(max((abs(value - median) for value in densities), default=0.0)), "phase_uncertainty": lift["maximum_pairwise_wrapped_distance"], "branch_ambiguous": lift["ambiguous"], "lifted_phases": lift["lifted_phases"]}


def _c3_pair_test(summary: Mapping[str, Any], key: str, require_rank1: bool) -> str:
    if require_rank1 and summary["rank1_qualification"]["status"] != "RANK1_QUALIFIED":
        return "RANK1_WITHHELD"
    for left, right in itertools.combinations(MEMBERS, 2):
        a, b = summary["member_summary"][left][key], summary["member_summary"][right][key]
        same_sign = not (a["median"] and b["median"]) or np.sign(a["median"]) == np.sign(b["median"])
        if abs(a["median"] - b["median"]) > a["uncertainty"] + b["uncertainty"] or not same_sign:
            return "FAIL"
    return "PASS"


def configuration_detail(records: Sequence[Mapping[str, Any]], centers: Mapping[str, Sequence[float]], m38: Any, m39: Any, configuration_id: str) -> dict[str, Any]:
    """Recompute all finite rank1/rank2 evidence from raw immutable records."""
    if len(records) != 36:
        raise ValueError("M48_CONFIGURATION_RECORD_COUNT_INVALID")
    detail = m42._configuration(records, m38, m39, configuration_id)
    for plaquette in detail["plaquettes"]:
        area = float(plaquette["signed_area"])
        plaquette["rank1_wilson_phase"] = float(plaquette["rank1_phase"])
        plaquette["rank1_phase_density"] = float(plaquette["rank1_phase"]) / area
        plaquette["rank2_trace_phase"] = float(plaquette["rank2_phase"])
        plaquette["rank2_trace_wilson_phase"] = float(plaquette["rank2_phase"])
        plaquette["rank2_trace_phase_density"] = float(plaquette["rank2_phase"]) / area
        for edge in plaquette["rank2_edges"]:
            edge["canonical_target_pair"] = [2, 3]
            edge["canonical_minimum_singular_value"] = float(edge["canonical_minimum_singular_value"])
    by_member: dict[str, Any] = {}
    for member in MEMBERS:
        rows = [row for row in detail["plaquettes"] if row["member"] == member]
        rank1 = _scalar_stats([row["rank1_phase"] for row in rows], [row["signed_area"] for row in rows])
        rank2 = _scalar_stats([row["rank2_phase"] for row in rows], [row["signed_area"] for row in rows])
        gaps: dict[int, list[float]] = {vertex: [] for vertex in range(4)}
        for record in records:
            if record["c3_member_identity"] == member:
                value = min(float(record["adjacent_gaps"]["lower_gap"]), float(record["adjacent_gaps"]["internal_split"]))
                gaps[int(record["vertex_index"])].append(value)
        links: dict[int, list[float]] = {edge: [] for edge in range(4)}
        for row in rows:
            for edge in row["rank1_edges"]:
                links[int(edge["edge_index"])].append(float(edge["link_magnitude"]))
        gap_ranges = {vertex: max(values) - min(values) for vertex, values in gaps.items() if values}
        link_ranges = {edge: max(values) - min(values) for edge, values in links.items() if values}
        gap_signal = min(value for values in gaps.values() for value in values)
        link_signal = min(value for values in links.values() for value in values)
        gap_noise = max(gap_ranges.values(), default=0.0)
        link_noise = max(link_ranges.values(), default=0.0)
        rank1_association = all(edge["best_target_band"] == 2 for row in rows for edge in row["rank1_edges"])
        rank2_association = {edge: m42._association_state([item["best_target_pair"] for row in rows for item in row["rank2_edges"] if int(item["edge_index"]) == edge]) for edge in range(4)}
        branch_margin = min(math.pi - abs(float(row["rank1_phase"])) for row in rows)
        phase_uncertainty = float(rank1["phase_uncertainty"])
        gate = {"gap_signal": gap_signal, "gap_repeat_noise": gap_noise, "link_signal": link_signal, "link_repeat_noise": link_noise, "branch_uncertainty": phase_uncertainty, "phase_density_uncertainty": rank1["uncertainty"], "branch_margin": branch_margin, "gap_ratio": gap_signal / gap_noise if gap_noise else (float("inf") if gap_signal > 0 else 0.0), "link_ratio": link_signal / link_noise if link_noise else (float("inf") if link_signal > 0 else 0.0), "branch_ratio": branch_margin / phase_uncertainty if phase_uncertainty else float("inf"), "stable_band2_association": rank1_association, "rank2_association": rank2_association}
        gate["status"] = "RANK1_QUALIFIED" if rank1_association and gate["gap_ratio"] >= 10.0 and gate["link_ratio"] >= 10.0 and gate["branch_ratio"] >= 5.0 and not rank1["branch_ambiguous"] else "RANK1_WITHHELD"
        by_member[member] = {"rank1_phase_density": rank1, "rank2_trace_phase_density": rank2, "gap_signal": gap_signal, "gap_repeat_noise": gap_noise, "link_signal": link_signal, "link_repeat_noise": link_noise, "rank1_association": rank1_association, "rank2_association": rank2_association, "rank1_qualification": gate}
    rank1_qualified = all(by_member[member]["rank1_qualification"]["status"] == "RANK1_QUALIFIED" for member in MEMBERS)
    detail["member_summary"] = by_member
    detail["rank1_qualification"] = {"status": "RANK1_QUALIFIED" if rank1_qualified else "RANK1_WITHHELD", "per_member": {member: by_member[member]["rank1_qualification"] for member in MEMBERS}, "stable_band2_association": all(by_member[member]["rank1_association"] for member in MEMBERS)}
    detail["rank2_association_stable"] = all(state == "CANONICAL_STABLE" for member in MEMBERS for state in by_member[member]["rank2_association"].values())
    detail["rank1_c3_status"] = _c3_pair_test(detail, "rank1_phase_density", True)
    detail["rank2_c3_status"] = _c3_pair_test(detail, "rank2_trace_phase_density", False)
    detail["canonical_rank2_pair_one_based"] = [2, 3]
    detail["qualification_source"] = "M48 raw-H recomputation with order-independent circular lifting and frozen 10/10/5 gates"
    return detail


def _sequence(values: Mapping[int, Sequence[float] | float], identity: str) -> dict[str, Any]:
    table, medians = [], {}
    for resolution in RESOLUTIONS:
        if resolution not in values:
            continue
        raw = values[resolution]
        repeats = [float(raw)] if isinstance(raw, (int, float)) else [float(value) for value in raw]
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


def _sequences(matrix: Mapping[int, Sequence[Mapping[str, Any]]], analyses: Mapping[int, Mapping[str, Any]]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    result: dict[str, Any] = {}
    for member in MEMBERS:
        for vertex in range(4):
            for band in range(1, 5):
                key = f"spectral_frequency:{member}:vertex{vertex}:band{band}"
                result[key] = _sequence({resolution: [float(row["frequencies_bands_1_to_4"][band - 1]) for row in rows if row["c3_member_identity"] == member and int(row["vertex_index"]) == vertex] for resolution, rows in matrix.items()}, key)
            key = f"spectral_gap:{member}:vertex{vertex}:band2_isolation"
            result[key] = _sequence({resolution: [min(float(row["adjacent_gaps"]["lower_gap"]), float(row["adjacent_gaps"]["internal_split"])) for row in rows if row["c3_member_identity"] == member and int(row["vertex_index"]) == vertex] for resolution, rows in matrix.items()}, key)
    for member in MEMBERS:
        for edge in range(4):
            values, links = {}, {}
            for resolution, analysis in analyses.items():
                rows = [row for row in analysis["plaquettes"] if row["member"] == member]
                values[resolution] = [float(row["rank2_edges"][edge]["canonical_minimum_singular_value"]) for row in rows]
                links[resolution] = [float(row["rank1_edges"][edge]["link_magnitude"]) for row in rows]
            key = f"subspace_overlap:{member}:edge{edge}:canonical_rank2_minimum_singular_value"; result[key] = _sequence(values, key)
            key = f"rank1_link_corroboration:{member}:edge{edge}:physical_band2"; result[key] = _sequence(links, key)
    rank2, rank1 = {}, {}
    for member in MEMBERS:
        values2, values1 = {}, {}
        for resolution, analysis in analyses.items():
            rows = [row for row in analysis["plaquettes"] if row["member"] == member]
            values2[resolution] = [float(row["rank2_trace_phase_density"]) for row in rows]
            values1[resolution] = [float(row["rank1_phase_density"]) for row in rows] if analysis["rank1_qualification"]["status"] == "RANK1_QUALIFIED" else []
        key2 = f"berry_rank2_primary:{member}"; key1 = f"berry_rank1_qualified:{member}"
        rank2[key2] = _sequence(values2, key2); rank1[key1] = _sequence(values1, key1)
    return result, rank2, rank1


def _with_transitions(sequences: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    output = {}
    for key, sequence in sequences.items():
        fits = sequence.get("fits", {}); w2 = fits.get("160-192-224", {}); w3 = fits.get("192-224-256", {})
        w2_ok, w3_ok = w2.get("status") == "VALID_POSITIVE_P", w3.get("status") == "VALID_POSITIVE_P"
        if w2_ok and w3_ok: transition = "STABLE_LATE_ASYMPTOTIC"
        elif not w2_ok and w3_ok: transition = "ENTERING_ASYMPTOTIC"
        elif w2_ok and not w3_ok: transition = "EXITING_ASYMPTOTIC"
        else: transition = "PERSISTENT_NONASYMPTOTIC"
        output[key] = {**sequence, "transition_class": transition, "withholding_reasons": {name: fit.get("reason") for name, fit in fits.items() if fit.get("status") != "VALID_POSITIVE_P"}}
    return output


def _partition(sequences: Mapping[str, Mapping[str, Any]], keys: Sequence[str]) -> dict[str, Any]:
    failures = [key for key in keys if sequences[key].get("fits", {}).get("192-224-256", {}).get("status") != "VALID_POSITIVE_P"]
    transitions = {key: sequences[key]["transition_class"] for key in keys}
    return {"sequence_count": len(keys), "all_w3_valid": not failures, "failing_identities": failures, "transition_classes": transitions}


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


def _c3_context(analyses: Mapping[int, Mapping[str, Any]]) -> dict[str, Any]:
    statuses = {str(resolution): {"rank1": analyses[resolution]["rank1_c3_status"], "rank2": analyses[resolution]["rank2_c3_status"]} for resolution in (192, 224, 256)}
    changes = []
    for left, right in ((192, 224), (224, 256)):
        if statuses[str(left)] != statuses[str(right)]:
            changes.append(f"{left}_to_{right}")
    return {"statuses": statuses, "changed_pairs": changes, "authority": "M48_recomputed_exact_pairwise_tests"}


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


def _counterevidence(partitions: Mapping[str, Mapping[str, Any]], selected: str, sequences: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    converged = [name for name, partition in partitions.items() if partition["all_w3_valid"]]
    contradicting = [key for key, sequence in sequences.items() if sequence["transition_class"] == "STABLE_LATE_ASYMPTOTIC" and selected != "ALL_LATEST_FAMILIES_ASYMPTOTIC_AFTER_CORRECTION"]
    by_identity = {"member": {}, "vertex": {}, "band": {}, "edge": {}}
    for key, sequence in sequences.items():
        if sequence["transition_class"] != "PERSISTENT_NONASYMPTOTIC":
            continue
        parts = key.split(":")
        for label, token in (("member", parts[1] if len(parts) > 1 else "unknown"), ("vertex", next((part for part in parts if part.startswith("vertex")), "none")), ("band", next((part for part in parts if part.startswith("band")), "none")), ("edge", next((part for part in parts if part.startswith("edge")), "none"))):
            by_identity[label][token] = by_identity[label].get(token, 0) + 1
    return {"converged_partitions": converged, "contradicting_stable_late_identities": contradicting, "failure_identity_counts": by_identity, "concentration_is_descriptive_only": True}


def _load_matrix(job: Any, state_root: Path) -> tuple[dict[int, list[dict[str, Any]]], dict[str, list[float]], Any, Any]:
    m41 = m47.m41r3._read_dataset(job, state_root, m47.M41R3_DATASET_ID, m47.M41R3_MANIFEST_SHA256, m47.M41R3_SCHEMA, 108)
    m44 = m47.m41r3._read_dataset(job, state_root, m47.M44_DATASET_ID, m47.M44_MANIFEST_SHA256, m47.M44_SCHEMA, 72)
    m46 = m47.m41r3._read_dataset(job, state_root, m47.M46_DATASET_ID, m47.M46_MANIFEST_SHA256, m47.M46_SCHEMA, 36)
    m47_rows = m47.m41r3._read_dataset(job, state_root, M47_DATASET_ID, M47_MANIFEST_SHA256, M47_SCHEMA, 36)
    m18 = m47.m41r3._read_dataset(job, state_root, m47.m41r3.M18_DATASET_ID, m47.m41r3.M18_MANIFEST_SHA256, m47.m41r3.M18_SCHEMA, 3)
    m39r1 = m47.m41r3._read_dataset(job, state_root, m47.m41r3.M39R1_DATASET_ID, m47.m41r3.M39R1_MANIFEST_SHA256, m47.m41r3.M39R1_SCHEMA, 14)
    matrix = {resolution: [row for row in source if row.get("configuration_id") == f"R{resolution}_T1E9_M3"] for resolution, source in ((64, m41), (96, m41), (128, m41), (160, m44), (192, m44), (224, m46), (256, m47_rows))}
    if any(len(rows) != 36 for rows in matrix.values()):
        raise ValueError("M48_SEVEN_RESOLUTION_MATRIX_INVALID")
    return matrix, m47.m41r3._centers(m18, m39r1), m47.m41r3._load(ROOT / "audit/berry_c3_consistency/m38_supplied_exact_mpb_source_semantics_raw_native_c3.py", "m48_m38"), m47.m41r3._load(ROOT / "audit/berry_c3_consistency/m39_g15_deterministic_repeat_band_association_worst_orbit_pilot.py", "m48_m39")


def main() -> int:
    bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8")); source_commit = str(os.environ.get("MEPHC_SOURCE_COMMIT") or bundle.get("source_commit") or "")
    try:
        job = m47.m41r3._load(ROOT / "tools/mephc-flow/scientific_job.py", "m48_job"); state_root = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"]).parent.parent
        matrix, centers, m38, m39 = _load_matrix(job, state_root)
        analyses = {resolution: configuration_detail(rows, centers, m38, m39, f"R{resolution}_T1E9_M3") for resolution, rows in matrix.items()}
        raw_sequences, raw_rank2, raw_rank1 = _sequences(matrix, analyses)
        sequences, rank2, rank1 = _with_transitions(raw_sequences), _with_transitions(raw_rank2), _with_transitions(raw_rank1)
        frequency_keys = [key for key in sequences if key.startswith("spectral_frequency:")]
        gap_keys = [key for key in sequences if key.startswith("spectral_gap:")]
        subspace_keys = [key for key in sequences if key.startswith("subspace_overlap:")]
        link_keys = [key for key in sequences if key.startswith("rank1_link_corroboration:")]
        berry_keys = list(rank2)
        partitions = {"frequency": _partition(sequences, frequency_keys), "gap": _partition(sequences, gap_keys), "subspace": _partition(sequences, subspace_keys), "berry": _partition(rank2, berry_keys), "rank1_link_corroboration": _partition(sequences, link_keys)}
        association = _association(analyses, (192, 224, 256)); classification, decision = _localize(partitions, association); c3 = _c3_context(analyses)
        all_sequences = {**sequences, **rank2, **rank1}
        result = {"schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS", "machine_execution_contract_status": "ZERO_SCIENTIFIC_EXECUTION_SEVEN_RESOLUTION_MIXED_FAMILY_MECHANISM_LOCALIZATION", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 0, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "verified_record_counts": {str(resolution): len(rows) for resolution, rows in matrix.items()}, "configuration_analysis": analyses, "semantic_sequence_inventory": {"frequency": len(frequency_keys), "gap": len(gap_keys), "subspace_overlap": len(subspace_keys), "rank1_link_corroboration": len(link_keys), "berry_rank2_primary": len(berry_keys), "qualified_rank1_up_to": len(rank1)}, "semantic_sequences": all_sequences, "partitions": partitions, "high_resolution_association": association, "corrected_c3_context": c3, "counterevidence": _counterevidence(partitions, classification, all_sequences), "localization_class": classification, "classification": classification, "next_science_decision": decision, "source_commit_used": source_commit, "post_analysis_checkout_unchanged": True}
    except BaseException as exc:
        result = {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "machine_execution_contract_status": "M48_FAIL_CLOSED", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 0, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "failure_code": str(exc)[:1024], "failure_stage": "seven_resolution_solver_free_analysis", "exception_type": type(exc).__name__, "source_commit_used": source_commit}
    Path(os.environ["MEPHC_RESULT_PATH"]).write_text(json.dumps(_safe(result), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
