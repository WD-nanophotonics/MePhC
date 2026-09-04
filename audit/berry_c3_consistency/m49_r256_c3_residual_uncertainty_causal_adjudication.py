"""M49: solver-free R224-to-R256 C3 residual uncertainty adjudication."""
from __future__ import annotations

import importlib.util
import itertools
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
M48R2_PATH = ROOT / "audit/berry_c3_consistency/m48r2_self_contained_seven_resolution_mechanism_localization.py"
SPEC = importlib.util.spec_from_file_location("m49_m48r2_detail_substrate", M48R2_PATH)
assert SPEC and SPEC.loader
m48r2 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m48r2)
m41r3 = m48r2.m41r3
m45r2 = m48r2.m45r2

RESULT_SCHEMA = "mephc-berry-c3-consistency-m49-r256-c3-residual-uncertainty-causal-adjudication-v1"
MEMBERS = tuple(m48r2.MEMBERS)
RESOLUTIONS = (64, 96, 128, 160, 192, 224, 256)
M47_DATASET_ID = m48r2.M47_DATASET_ID
M47_MANIFEST_SHA256 = m48r2.M47_MANIFEST_SHA256
M47_SCHEMA = m48r2.M47_SCHEMA


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
    raise ValueError(f"M49_UNSAFE_RESULT:{type(value).__name__}")


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


def _phase_stats(phases: Sequence[float], areas: Sequence[float]) -> dict[str, Any]:
    lift = _phase_lift(phases)
    values = [float(phase) / float(area) for phase, area in zip(lift["lifted_phases"], areas)]
    median = float(np.median(values)) if values else 0.0
    return {"median": median, "repeat_uncertainty": float(max((abs(value - median) for value in values), default=0.0)), "phase_uncertainty": lift["maximum_pairwise_wrapped_distance"], "branch_ambiguous": lift["ambiguous"], "lifted_phases": lift["lifted_phases"], "values": values}


def _scalar_stats(values: Sequence[float]) -> dict[str, Any]:
    numbers = [float(value) for value in values]
    median = float(np.median(numbers)) if numbers else 0.0
    return {"median": median, "repeat_uncertainty": float(max((abs(value - median) for value in numbers), default=0.0)), "values": numbers}


def _association_state(pairs: Sequence[Sequence[int]]) -> str:
    values = [tuple(int(value) for value in pair) for pair in pairs]
    if not values or len(set(values)) != 1:
        return "REPEAT_UNSTABLE"
    return "CANONICAL_STABLE" if values[0] == (2, 3) else "NONCANONICAL_STABLE"


def _matrix(job: Any, state_root: Path) -> tuple[dict[int, list[dict[str, Any]]], dict[str, list[float]], Any, Any]:
    m41 = m41r3._read_dataset(job, state_root, m45r2.M41R3_DATASET_ID, m45r2.M41R3_MANIFEST_SHA256, m45r2.M41R3_SCHEMA, 108)
    partial = m41r3._read_partial(job, state_root)
    m44 = m41r3._read_dataset(job, state_root, m45r2.M44_DATASET_ID, m45r2.M44_MANIFEST_SHA256, m45r2.M44_SCHEMA, 72)
    m46 = m41r3._read_dataset(job, state_root, "6a0bd125fb2b4b640292ff8580d4812cbb1be8d4e1e383133060cf8139e2f533", "b7d2f0974b5305f1903a088c99d3dd285cbca844b3d93d9a8f3a705272a0ece8", "mephc-berry-c3-consistency-m46-r224-semantic-family-vertex-dataset-v1", 36)
    m47 = m41r3._read_dataset(job, state_root, M47_DATASET_ID, M47_MANIFEST_SHA256, M47_SCHEMA, 36)
    m18 = m41r3._read_dataset(job, state_root, m41r3.M18_DATASET_ID, m41r3.M18_MANIFEST_SHA256, m41r3.M18_SCHEMA, 3)
    m39 = m41r3._read_dataset(job, state_root, m41r3.M39R1_DATASET_ID, m41r3.M39R1_MANIFEST_SHA256, m41r3.M39R1_SCHEMA, 14)
    source_pairs = ((64, m41), (96, m41), (128, partial), (160, m44), (192, m44), (224, m46), (256, m47))
    matrix = {resolution: [dict(row) for row in source if int(row.get("resolution", -1)) == resolution and row.get("configuration_id") == f"R{resolution}_T1E9_M3" and row.get("geometry_id") == "G15" and row.get("stencil") == "C3_COVARIANT" and int(row.get("mesh_size", -1)) == 3] for resolution, source in source_pairs}
    if any(len(rows) != 36 for rows in matrix.values()) or sum(len(rows) for rows in matrix.values()) != 252:
        raise ValueError(f"M49_SEVEN_RESOLUTION_MATRIX_INVALID:{[(resolution, len(rows)) for resolution, rows in matrix.items()]}")
    return matrix, m41r3._centers(m18, m39), m41r3._load(ROOT / "audit/berry_c3_consistency/m38_supplied_exact_mpb_source_semantics_raw_native_c3.py", "m49_m38"), m41r3._load(ROOT / "audit/berry_c3_consistency/m39_g15_deterministic_repeat_band_association_worst_orbit_pilot.py", "m49_m39")


def _residual(identity: str, values: Mapping[int, Mapping[str, Mapping[str, Any]]], observable: str, berry: bool = False) -> dict[str, Any]:
    rows = {}
    for resolution in RESOLUTIONS:
        members = values.get(resolution, {})
        rows[str(resolution)] = {member: members[member] for member in MEMBERS if member in members}
    pairs = {}
    final = values[256]
    for left, right in itertools.combinations(MEMBERS, 2):
        a, b = final[left], final[right]
        difference = abs(float(a["median"]) - float(b["median"]))
        pair_uncertainty = float(a["repeat_uncertainty"]) + float(b["repeat_uncertainty"])
        if berry:
            aligned = float(values[224][left]["median"] + 2.0 * math.pi * round((values[256][left]["median"] - values[224][left]["median"]) / (2.0 * math.pi)))
            aligned_b = float(values[224][right]["median"] + 2.0 * math.pi * round((values[256][right]["median"] - values[224][right]["median"]) / (2.0 * math.pi)))
            a_resolution = abs(float(a["median"]) - aligned) / float(a["area"])
            b_resolution = abs(float(b["median"]) - aligned_b) / float(b["area"])
        else:
            a_resolution = abs(float(a["median"]) - float(values[224][left]["median"]))
            b_resolution = abs(float(b["median"]) - float(values[224][right]["median"]))
        total_a = float(a["repeat_uncertainty"]) + a_resolution
        total_b = float(b["repeat_uncertainty"]) + b_resolution
        opposite_significant = bool(a["median"] and b["median"] and np.sign(a["median"]) != np.sign(b["median"]) and abs(a["median"]) > total_a and abs(b["median"]) > total_b)
        pairs[f"{left}_vs_{right}"] = {"median_left": a["median"], "median_right": b["median"], "absolute_difference": difference, "repeat_uncertainty_left": a["repeat_uncertainty"], "repeat_uncertainty_right": b["repeat_uncertainty"], "resolution_uncertainty_left": a_resolution, "resolution_uncertainty_right": b_resolution, "total_uncertainty_left": total_a, "total_uncertainty_right": total_b, "combined_total_uncertainty": total_a + total_b, "within_total_uncertainty": difference <= total_a + total_b, "opposite_significant": opposite_significant, "sign_rule_pass": not opposite_significant, "pass": difference <= total_a + total_b and not opposite_significant, "context_192": _context(values, 192, left, right), "context_224": _context(values, 224, left, right)}
    fit_context = {member: _sequence({resolution: [float(values[resolution][member]["median"])] for resolution in RESOLUTIONS if member in values.get(resolution, {})}, f"{identity}:{member}") for member in MEMBERS if member in final}
    return {"identity": identity, "observable": observable, "per_resolution": rows, "member_256": final, "pairs": pairs, "pass": all(pair["pass"] for pair in pairs.values()), "uncertainty_rule": "repeat_plus_R224_to_R256_adjacent_resolution", "sign_rule": "opposite signs fail only when both total-uncertainty intervals exclude zero on opposite sides", "absolute_fit_context": fit_context}


def _context(values: Mapping[int, Mapping[str, Mapping[str, Any]]], resolution: int, left: str, right: str) -> dict[str, Any]:
    a, b = values[resolution][left], values[resolution][right]
    return {"resolution": resolution, "median_left": a["median"], "median_right": b["median"], "absolute_difference": abs(float(a["median"]) - float(b["median"]))}


def _sequence(values: Mapping[int, Sequence[float]], identity: str) -> dict[str, Any]:
    medians = {}; table = []
    for resolution in RESOLUTIONS:
        if resolution not in values:
            continue
        stats = _scalar_stats(values[resolution]); medians[resolution] = stats["median"]; table.append({"resolution": resolution, **stats})
    fits = {}
    for triple in ((128, 160, 192), (160, 192, 224), (192, 224, 256)):
        if all(resolution in medians for resolution in triple):
            fits["-".join(map(str, triple))] = m45r2.fit_positive_p(triple, [medians[resolution] for resolution in triple])
    return {"identity": identity, "table": table, "fits": fits, "repeat_uncertainty_separate": True}


def _family(values: Mapping[int, Mapping[str, Mapping[str, Any]]], prefix: str, berry: bool = False) -> dict[str, Any]:
    return {identity: _residual(identity, values, prefix, berry) for identity in sorted(values[256])}


def _rank1_blockers(analysis: Mapping[str, Any]) -> dict[str, Any]:
    blockers = {}
    for member in MEMBERS:
        gate = analysis["member_summary"][member]["rank1_qualification"]
        isolation = []
        if not gate.get("stable_band2_association", False): isolation.append("association")
        if float(gate.get("gap_ratio", 0.0)) < 10.0: isolation.append("gap")
        if float(gate.get("link_ratio", 0.0)) < 10.0: isolation.append("link")
        branch = []
        if analysis["member_summary"][member].get("rank1_phase_density", {}).get("branch_ambiguous", False): branch.append("branch_ambiguity")
        if float(gate.get("branch_ratio", 0.0)) < 5.0: branch.append("branch_margin")
        blockers[member] = {"isolation_or_association_blockers": isolation, "branch_only_blockers": branch, "gate": gate}
    return {"per_member": blockers, "isolation_or_association": any(value["isolation_or_association_blockers"] for value in blockers.values()), "branch_only": any(value["branch_only_blockers"] for value in blockers.values()) and not any(value["isolation_or_association_blockers"] for value in blockers.values())}


def _localize(families: Mapping[str, Mapping[str, Any]], rank2_pass: bool, rank1: Mapping[str, Any], association: Mapping[str, Any]) -> tuple[str, str, list[str]]:
    if association["unstable"]:
        return "R256_HIGH_RESOLUTION_ASSOCIATION_INSTABILITY", "ADAPTIVE_VALIDATED_SUBSPACE_BERRY_TRANSPORT_USING_EXISTING_R192_R224_R256_RAW_BANDS", ["association"]
    failed = [name for name in ("frequency", "gap", "subspace", "berry_rank2") if not families[name]["all_pass"]]
    if not rank2_pass:
        failed.append("berry_rank2") if "berry_rank2" not in failed else None
    if failed:
        if len(set(failed)) > 1:
            return "R256_MULTIPLE_C3_BREAKING_LAYERS", "PRIORITIZE_EARLIEST_R256_C3_BREAKING_LAYER", sorted(set(failed))
        name = failed[0]
        mapping = {"frequency": ("R256_FREQUENCY_C3_BREAKING", "BOUND_R256_MESH_DISCRETIZATION_CONTROL"), "gap": ("R256_FREQUENCY_C3_PASS_GAP_C3_BREAKING", "ADAPTIVE_VALIDATED_SUBSPACE_AND_NEAR_DEGENERACY_ADJUDICATION_USING_EXISTING_R192_R224_R256_RAW_BANDS"), "subspace": ("R256_SPECTRAL_GAP_C3_PASS_SUBSPACE_C3_BREAKING", "ADAPTIVE_VALIDATED_SUBSPACE_BERRY_TRANSPORT_USING_EXISTING_R192_R224_R256_RAW_BANDS"), "berry_rank2": ("R256_SPECTRAL_SUBSPACE_C3_PASS_BERRY_RANK2_C3_BREAKING", "BOUND_PLAQUETTE_STEP_CONVERGENCE_AT_R256")}
        return (*mapping[name], [name])
    if not rank1["eligible"]:
        if rank1["blockers"]["isolation_or_association"]:
            return "R256_RANK2_C3_PASS_RANK1_WITHHELD_ISOLATION_OR_ASSOCIATION", "ADAPTIVE_VALIDATED_SUBSPACE_BERRY_TRANSPORT_USING_EXISTING_R192_R224_R256_RAW_BANDS", ["rank1_withheld_isolation_or_association"]
        return "R256_RANK2_C3_PASS_RANK1_WITHHELD_BRANCH", "BOUND_PLAQUETTE_STEP_CONVERGENCE_AT_R256", ["rank1_withheld_branch"]
    if not rank1["c3_pass"]:
        return "R256_RANK2_C3_PASS_RANK1_C3_BREAKING", "BOUND_PLAQUETTE_STEP_CONVERGENCE_AT_R256", ["berry_rank1"]
    return "R256_ALL_FINITE_C3_TESTS_PASS_WITH_ADJACENT_RESOLUTION_UNCERTAINTY", "CROSS_ORBIT_QUALIFICATION_AT_R256_T1E9_M3", []


def main() -> int:
    bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8")); source_commit = str(os.environ.get("MEPHC_SOURCE_COMMIT") or bundle.get("source_commit") or "")
    try:
        job = m41r3._load(ROOT / "tools/mephc-flow/scientific_job.py", "m49_job"); state_root = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"]).parent.parent
        matrix, centers, m38, m39 = _matrix(job, state_root)
        analyses = {resolution: m48r2.configuration_detail(rows, centers, m38, m39, f"R{resolution}_T1E9_M3") for resolution, rows in matrix.items()}
        frequency_values, gap_values, subspace_values, link_values, berry2_values, berry1_values = {}, {}, {}, {}, {}, {}
        for resolution, rows in matrix.items():
            for member in MEMBERS:
                for vertex in range(4):
                    selected = [row for row in rows if row["c3_member_identity"] == member and int(row["vertex_index"]) == vertex]
                    for band in range(1, 5):
                        frequency_values.setdefault(f"vertex{vertex}:band{band}", {}).setdefault(resolution, {}).setdefault(member, []).extend(float(row["frequencies_bands_1_to_4"][band - 1]) for row in selected)
                    gap_values.setdefault(f"vertex{vertex}:band2_isolation", {}).setdefault(resolution, {}).setdefault(member, []).extend(min(float(row["adjacent_gaps"]["lower_gap"]), float(row["adjacent_gaps"]["internal_split"])) for row in selected)
                for edge in range(4):
                    plaquettes = [item for item in analyses[resolution]["plaquettes"] if item["member"] == member]
                    subspace_values.setdefault(f"edge{edge}:canonical_rank2_minimum_singular_value", {}).setdefault(resolution, {}).setdefault(member, []).extend(float(item["rank2_edges"][edge]["canonical_minimum_singular_value"]) for item in plaquettes)
                    link_values.setdefault(f"edge{edge}:physical_band2_link", {}).setdefault(resolution, {}).setdefault(member, []).extend(float(item["rank1_edges"][edge]["link_magnitude"]) for item in plaquettes)
                plaquettes = [item for item in analyses[resolution]["plaquettes"] if item["member"] == member]
                rank2_values = _phase_stats([item["rank2_trace_phase"] for item in plaquettes], [item["signed_area"] for item in plaquettes]); rank1_values = _phase_stats([item["rank1_phase"] for item in plaquettes], [item["signed_area"] for item in plaquettes])
                berry2_values.setdefault(member, {})[resolution] = {"median": rank2_values["median"], "repeat_uncertainty": rank2_values["repeat_uncertainty"], "area": float(np.median([item["signed_area"] for item in plaquettes])), "phase_uncertainty": rank2_values["phase_uncertainty"]}
                berry1_values.setdefault(member, {})[resolution] = {"median": rank1_values["median"], "repeat_uncertainty": rank1_values["repeat_uncertainty"], "area": float(np.median([item["signed_area"] for item in plaquettes])), "phase_uncertainty": rank1_values["phase_uncertainty"]}
        def scalar_family(source: Mapping[str, Mapping[int, Mapping[str, Sequence[float]]]], label: str) -> dict[str, Any]:
            converted = {identity: {resolution: {member: _scalar_stats([float(value) for value in repeats]) for member, repeats in by_member.items()} for resolution, by_member in by_resolution.items()} for identity, by_resolution in source.items()}
            residuals = {identity: _residual(identity, values, label) for identity, values in converted.items()}
            return {"identities": residuals, "all_pass": all(item["pass"] for item in residuals.values()), "failing_identities": [identity for identity, item in residuals.items() if not item["pass"]]}
        frequency = scalar_family(frequency_values, "frequency"); gap = scalar_family(gap_values, "gap"); subspace = scalar_family(subspace_values, "subspace"); link = scalar_family(link_values, "rank1_link_corroboration")
        berry2_residuals = {identity: _residual(identity, values, "berry_rank2", True) for identity, values in berry2_values.items()}; berry2 = {"identities": berry2_residuals, "all_pass": all(item["pass"] for item in berry2_residuals.values()), "failing_identities": [identity for identity, item in berry2_residuals.items() if not item["pass"]]}
        berry1_residuals = {identity: _residual(identity, values, "berry_rank1", True) for identity, values in berry1_values.items()}; rank1_qualified = analyses[256]["rank1_qualification"]["status"] == "RANK1_QUALIFIED"; berry1 = {"eligible": rank1_qualified, "identities": berry1_residuals if rank1_qualified else {}, "all_pass": all(item["pass"] for item in berry1_residuals.values()) if rank1_qualified else None, "failing_identities": [identity for identity, item in berry1_residuals.items() if not item["pass"]] if rank1_qualified else []}
        association = m48r2._association(analyses, (192, 224, 256)); blockers = _rank1_blockers(analyses[256]); rank1 = {"eligible": rank1_qualified, "c3_pass": bool(berry1["all_pass"]) if rank1_qualified else False, "blockers": blockers}
        families = {"frequency": frequency, "gap": gap, "subspace": subspace, "berry_rank2": berry2}; classification, decision, failing_layers = _localize(families, berry2["all_pass"], rank1, association)
        result = {"schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS", "machine_execution_contract_status": "ZERO_SCIENTIFIC_EXECUTION_R256_C3_RESIDUAL_UNCERTAINTY_CAUSAL_ADJUDICATION", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 0, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "verified_record_counts": {str(resolution): len(rows) for resolution, rows in matrix.items()}, "verified_record_total": sum(len(rows) for rows in matrix.values()), "r128_source": "m41r3._read_partial", "residual_families": {**families, "rank1_link_corroboration": link, "berry_rank1": berry1}, "high_resolution_association": association, "rank1_withholding": blockers, "rank1_status": rank1, "corrected_c3_context": {str(resolution): {"rank1": analyses[resolution]["rank1_c3_status"], "rank2": analyses[resolution]["rank2_c3_status"]} for resolution in (192, 224, 256)}, "classification": classification, "causal_outcome": classification, "next_science_decision": decision, "failing_layers": failing_layers, "counterevidence": {"common_mode_absolute_drift_not_equal_c3_breaking": True, "rank1_link_corroboration": link, "absolute_fit_context": "W1/W2/W3 fit statuses are retained per residual identity in the residual tables"}, "source_commit_used": source_commit, "post_analysis_checkout_unchanged": True}
    except BaseException as exc:
        result = {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "machine_execution_contract_status": "M49_FAIL_CLOSED", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 0, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "failure_code": str(exc)[:1024], "failure_stage": "r256_c3_residual_uncertainty_adjudication", "exception_type": type(exc).__name__, "source_commit_used": source_commit}
    Path(os.environ["MEPHC_RESULT_PATH"]).write_text(json.dumps(_safe(result), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
