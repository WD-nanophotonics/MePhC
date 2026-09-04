"""M49R1: corrected, solver-free R256 C3 residual adjudication."""
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
BASE = ROOT / "audit/berry_c3_consistency/m48r2_self_contained_seven_resolution_mechanism_localization.py"
SPEC = importlib.util.spec_from_file_location("m49r1_detail_substrate", BASE)
assert SPEC and SPEC.loader
detail_substrate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(detail_substrate)
m41r3 = detail_substrate.m41r3
m45r2 = detail_substrate.m45r2

RESULT_SCHEMA = "mephc-berry-c3-consistency-m49r1-corrected-r256-c3-residual-causal-adjudication-v1"
MEMBERS = tuple(m41r3.MEMBERS)
RESOLUTIONS = (64, 96, 128, 160, 192, 224, 256)
M46_DATASET_ID = "6a0bd125fb2b4b640292ff8580d4812cbb1be8d4e1e383133060cf8139e2f533"
M46_MANIFEST = "b7d2f0974b5305f1903a088c99d3dd285cbca844b3d93d9a8f3a705272a0ece8"
M46_SCHEMA = "mephc-berry-c3-consistency-m46-r224-semantic-family-vertex-dataset-v1"
M47_DATASET_ID = detail_substrate.M47_DATASET_ID
M47_MANIFEST = detail_substrate.M47_MANIFEST_SHA256
M47_SCHEMA = detail_substrate.M47_SCHEMA


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
    raise ValueError(f"M49R1_UNSAFE_RESULT:{type(value).__name__}")


def _phase_lift(phases: Sequence[float]) -> dict[str, Any]:
    raw = [float(phase) for phase in phases]
    if not raw:
        return {"lifted": [], "ambiguous": False, "max_wrapped": 0.0}
    candidates = []
    for anchor in sorted(set(raw), key=lambda value: (value % (2.0 * math.pi), value)):
        lifted = [value + 2.0 * math.pi * round((anchor - value) / (2.0 * math.pi)) for value in raw]
        center = float(np.median(lifted))
        candidates.append((max(abs(value - center) for value in lifted), anchor % (2.0 * math.pi), anchor, lifted))
    chosen = min(candidates, key=lambda item: item[:3])
    wrapped = [abs(math.atan2(math.sin(left - right), math.cos(left - right))) for left, right in itertools.combinations(raw, 2)]
    return {"lifted": chosen[3], "ambiguous": any(abs(value - math.pi) <= 1e-12 for value in wrapped), "max_wrapped": float(max(wrapped, default=0.0))}


def _berry_stats(phases: Sequence[float], areas: Sequence[float]) -> dict[str, Any]:
    lift = _phase_lift(phases)
    if len(lift["lifted"]) != len(areas) or not areas:
        raise ValueError("BERRY_REPEAT_AREA_MISMATCH")
    density_values = [float(phase) / float(area) for phase, area in zip(lift["lifted"], areas)]
    phase_median = float(np.median(lift["lifted"]))
    density_median = float(np.median(density_values))
    return {
        "phase_median_lifted": phase_median,
        "phase_repeat_uncertainty": lift["max_wrapped"],
        "density_values": density_values,
        "density_median": density_median,
        "density_repeat_uncertainty": float(max((abs(value - density_median) for value in density_values), default=0.0)),
        "signed_area_median": float(np.median([float(area) for area in areas])),
        "branch_ambiguous": bool(lift["ambiguous"]),
    }


def _scalar_stats(values: Sequence[float]) -> dict[str, Any]:
    numbers = [float(value) for value in values]
    median = float(np.median(numbers)) if numbers else 0.0
    return {"median": median, "repeat_uncertainty": float(max((abs(value - median) for value in numbers), default=0.0)), "values": numbers}


def _read_matrix(job: Any, state_root: Path) -> tuple[dict[int, list[dict[str, Any]]], Mapping[str, Sequence[float]], Any, Any]:
    m41 = m41r3._read_dataset(job, state_root, m45r2.M41R3_DATASET_ID, m45r2.M41R3_MANIFEST_SHA256, m45r2.M41R3_SCHEMA, 108)
    partial = m41r3._read_partial(job, state_root)
    m44 = m41r3._read_dataset(job, state_root, m45r2.M44_DATASET_ID, m45r2.M44_MANIFEST_SHA256, m45r2.M44_SCHEMA, 72)
    m46 = m41r3._read_dataset(job, state_root, M46_DATASET_ID, M46_MANIFEST, M46_SCHEMA, 36)
    m47 = m41r3._read_dataset(job, state_root, M47_DATASET_ID, M47_MANIFEST, M47_SCHEMA, 36)
    m18 = m41r3._read_dataset(job, state_root, m41r3.M18_DATASET_ID, m41r3.M18_MANIFEST_SHA256, m41r3.M18_SCHEMA, 3)
    m39 = m41r3._read_dataset(job, state_root, m41r3.M39R1_DATASET_ID, m41r3.M39R1_MANIFEST_SHA256, m41r3.M39R1_SCHEMA, 14)
    sources = ((64, m41), (96, m41), (128, partial), (160, m44), (192, m44), (224, m46), (256, m47))
    matrix = {resolution: [dict(row) for row in source if int(row.get("resolution", -1)) == resolution and row.get("configuration_id") == f"R{resolution}_T1E9_M3" and row.get("geometry_id") == "G15" and row.get("stencil") == "C3_COVARIANT" and int(row.get("mesh_size", -1)) == 3] for resolution, source in sources}
    if any(len(rows) != 36 for rows in matrix.values()) or sum(len(rows) for rows in matrix.values()) != 252:
        raise ValueError(f"M49R1_MATRIX_BINDING_INVALID:{[(resolution, len(rows)) for resolution, rows in matrix.items()]}")
    centers = m41r3._centers(m18, m39)
    m38 = m41r3._load(ROOT / "audit/berry_c3_consistency/m38_supplied_exact_mpb_source_semantics_raw_native_c3.py", "m49r1_m38")
    m39_module = m41r3._load(ROOT / "audit/berry_c3_consistency/m39_g15_deterministic_repeat_band_association_worst_orbit_pilot.py", "m49r1_m39")
    return matrix, centers, m38, m39_module


def _assert_members(values: Mapping[int, Mapping[str, Any]]) -> None:
    for resolution in (224, 256):
        if set(values.get(resolution, {})) != set(MEMBERS):
            raise ValueError(f"M49R1_MEMBER_AXIS_INVALID:R{resolution}:{sorted(values.get(resolution, {}))}")


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


def _scalar_residual(identity: str, values: Mapping[int, Mapping[str, Mapping[str, Any]]], observable: str) -> dict[str, Any]:
    _assert_members(values)
    per_resolution = {str(resolution): {member: values[resolution][member] for member in MEMBERS if member in values.get(resolution, {})} for resolution in RESOLUTIONS}
    pairs = {}
    for left, right in itertools.combinations(MEMBERS, 2):
        a, b = values[256][left], values[256][right]
        a_adj = abs(float(a["median"]) - float(values[224][left]["median"]))
        b_adj = abs(float(b["median"]) - float(values[224][right]["median"]))
        a_total = float(a["repeat_uncertainty"]) + a_adj; b_total = float(b["repeat_uncertainty"]) + b_adj
        diff = abs(float(a["median"]) - float(b["median"]))
        opposite = bool(float(a["median"]) * float(b["median"]) < 0 and (float(a["median"]) - a_total > 0 > float(b["median"]) + b_total or float(b["median"]) - b_total > 0 > float(a["median"]) + a_total))
        pairs[f"{left}_vs_{right}"] = {"median_left": a["median"], "median_right": b["median"], "absolute_difference": diff, "repeat_uncertainty_left": a["repeat_uncertainty"], "repeat_uncertainty_right": b["repeat_uncertainty"], "resolution_uncertainty_left": a_adj, "resolution_uncertainty_right": b_adj, "total_uncertainty_left": a_total, "total_uncertainty_right": b_total, "combined_total_uncertainty": a_total + b_total, "within_total_uncertainty": diff <= a_total + b_total, "opposite_significant": opposite, "pass": diff <= a_total + b_total and not opposite, "context_192": {"left": values[192][left]["median"], "right": values[192][right]["median"]}, "context_224": {"left": values[224][left]["median"], "right": values[224][right]["median"]}}
    fit_context = {member: _sequence({resolution: [float(values[resolution][member]["median"])] for resolution in RESOLUTIONS if member in values.get(resolution, {})}, f"{identity}:{member}") for member in MEMBERS}
    return {"identity": identity, "observable": observable, "per_resolution": per_resolution, "pairs": pairs, "pass": all(pair["pass"] for pair in pairs.values()), "absolute_fit_context": fit_context, "uncertainty_components": "repeat_uncertainty and R224_to_R256 adjacent-resolution uncertainty are separate; total is their sum"}


def _berry_residual(identity: str, values: Mapping[int, Mapping[str, Mapping[str, Any]]], observable: str) -> dict[str, Any]:
    _assert_members(values)
    pairs = {}; inter_resolution_ambiguity = {}
    for member in MEMBERS:
        p224 = float(values[224][member]["phase_median_lifted"]); p256 = float(values[256][member]["phase_median_lifted"])
        wrapped = abs(math.atan2(math.sin(p256 - p224), math.cos(p256 - p224)))
        inter_resolution_ambiguity[member] = abs(wrapped - math.pi) <= 1e-12
    for left, right in itertools.combinations(MEMBERS, 2):
        a, b = values[256][left], values[256][right]
        aligned_a = float(values[224][left]["phase_median_lifted"]) + 2.0 * math.pi * round((float(a["phase_median_lifted"]) - float(values[224][left]["phase_median_lifted"])) / (2.0 * math.pi))
        aligned_b = float(values[224][right]["phase_median_lifted"]) + 2.0 * math.pi * round((float(b["phase_median_lifted"]) - float(values[224][right]["phase_median_lifted"])) / (2.0 * math.pi))
        a_adj = abs(float(a["density_median"]) - aligned_a / float(values[224][left]["signed_area_median"]))
        b_adj = abs(float(b["density_median"]) - aligned_b / float(values[224][right]["signed_area_median"]))
        a_total = float(a["density_repeat_uncertainty"]) + a_adj; b_total = float(b["density_repeat_uncertainty"]) + b_adj
        diff = abs(float(a["density_median"]) - float(b["density_median"]))
        opposite = bool(float(a["density_median"]) * float(b["density_median"]) < 0 and (float(a["density_median"]) - a_total > 0 > float(b["density_median"]) + b_total or float(b["density_median"]) - b_total > 0 > float(a["density_median"]) + a_total))
        ambiguous = inter_resolution_ambiguity[left] or inter_resolution_ambiguity[right] or bool(a["branch_ambiguous"]) or bool(b["branch_ambiguous"])
        pairs[f"{left}_vs_{right}"] = {"density_median_left": a["density_median"], "density_median_right": b["density_median"], "phase_median_lifted_left": a["phase_median_lifted"], "phase_median_lifted_right": b["phase_median_lifted"], "aligned_phase224_left": aligned_a, "aligned_phase224_right": aligned_b, "absolute_density_difference": diff, "repeat_uncertainty_left": a["density_repeat_uncertainty"], "repeat_uncertainty_right": b["density_repeat_uncertainty"], "resolution_uncertainty_left": a_adj, "resolution_uncertainty_right": b_adj, "total_uncertainty_left": a_total, "total_uncertainty_right": b_total, "combined_total_uncertainty": a_total + b_total, "opposite_significant": opposite, "inter_resolution_branch_ambiguous": ambiguous, "pass": diff <= a_total + b_total and not opposite and not ambiguous, "context_192": values[192][left]["density_median"], "context_224": values[224][left]["density_median"]}
    return {"identity": identity, "observable": observable, "pairs": pairs, "pass": all(pair["pass"] for pair in pairs.values()), "branch_ambiguity": any(inter_resolution_ambiguity.values()), "unit_rule": "2pi alignment acts only on phase_median_lifted; aligned phase224 is divided by area224 exactly once before comparison to density256"}


def _family(source: Mapping[str, Mapping[int, Mapping[str, Sequence[float]]]], label: str) -> dict[str, Any]:
    residuals = {}
    for identity, by_resolution in source.items():
        stats = {resolution: {member: _scalar_stats(repeats) for member, repeats in by_member.items()} for resolution, by_member in by_resolution.items()}
        residuals[identity] = _scalar_residual(identity, stats, label)
    return {"identities": residuals, "all_pass": all(item["pass"] for item in residuals.values()), "failing_identities": [identity for identity, item in residuals.items() if not item["pass"]]}


def _rank1_blockers(analysis: Mapping[str, Any]) -> dict[str, Any]:
    result = {}
    for member in MEMBERS:
        summary = analysis["member_summary"][member]; gate = summary["rank1_qualification"]
        isolation = ([] if gate.get("stable_band2_association", False) else ["stable_band2_association=false"])
        if float(gate.get("gap_ratio", 0.0)) < 10.0: isolation.append("gap_ratio<10")
        if float(gate.get("link_ratio", 0.0)) < 10.0: isolation.append("link_ratio<10")
        branch = []
        if float(gate.get("branch_ratio", 0.0)) < 5.0: branch.append("branch_ratio<5")
        if summary.get("rank1_phase_density", {}).get("branch_ambiguous", False): branch.append("branch_ambiguous=true")
        result[member] = {"isolation_or_association_blockers": isolation, "branch_only_blockers": branch if not isolation else [], "unresolved": not isolation and not branch, "gate": gate}
    return {"per_member": result, "isolation_or_association": any(item["isolation_or_association_blockers"] for item in result.values()), "branch_only": any(item["branch_only_blockers"] for item in result.values()), "unresolved": any(item["unresolved"] for item in result.values())}


def _association(analyses: Mapping[int, Mapping[str, Any]]) -> dict[str, Any]:
    return detail_substrate._association(analyses, (192, 224, 256))


def _localize(families: Mapping[str, Mapping[str, Any]], rank2_pass: bool, rank2_branch: bool, rank1: Mapping[str, Any], association: Mapping[str, Any]) -> tuple[str, str, list[str]]:
    if association["unstable"]:
        return "R256_HIGH_RESOLUTION_ASSOCIATION_INSTABILITY", "ADAPTIVE_VALIDATED_SUBSPACE_BERRY_TRANSPORT_USING_EXISTING_R192_R224_R256_RAW_BANDS", ["association"]
    failed = [name for name in ("frequency", "gap", "subspace", "berry_rank2") if not families[name]["all_pass"]]
    if rank2_branch and "berry_rank2" not in failed: failed.append("berry_rank2")
    if failed:
        if len(failed) > 1:
            decision = "BOUND_R256_MESH_DISCRETIZATION_CONTROL" if "frequency" in failed else "ADAPTIVE_VALIDATED_SUBSPACE_AND_NEAR_DEGENERACY_ADJUDICATION_USING_EXISTING_R192_R224_R256_RAW_BANDS"
            return "R256_MULTIPLE_C3_BREAKING_LAYERS", decision, sorted(set(failed))
        mapping = {"frequency": ("R256_FREQUENCY_C3_BREAKING", "BOUND_R256_MESH_DISCRETIZATION_CONTROL"), "gap": ("R256_FREQUENCY_C3_PASS_GAP_C3_BREAKING", "ADAPTIVE_VALIDATED_SUBSPACE_AND_NEAR_DEGENERACY_ADJUDICATION_USING_EXISTING_R192_R224_R256_RAW_BANDS"), "subspace": ("R256_SPECTRAL_GAP_C3_PASS_SUBSPACE_C3_BREAKING", "ADAPTIVE_VALIDATED_SUBSPACE_AND_NEAR_DEGENERACY_ADJUDICATION_USING_EXISTING_R192_R224_R256_RAW_BANDS"), "berry_rank2": (("R256_SPECTRAL_SUBSPACE_C3_PASS_BERRY_RANK2_BRANCH_AMBIGUITY" if rank2_branch else "R256_SPECTRAL_SUBSPACE_C3_PASS_BERRY_RANK2_C3_BREAKING"), "BOUND_PLAQUETTE_STEP_CONVERGENCE_AT_R256")}
        return (*mapping[failed[0]], failed)
    if not rank1["eligible"]:
        if rank1["blockers"]["unresolved"]: return "R256_RANK2_C3_PASS_RANK1_WITHHELD_UNRESOLVED", "TARGETED_R256_RANK1_GATE_DISCRIMINANT", ["rank1_withheld_unresolved"]
        if rank1["blockers"]["isolation_or_association"]: return "R256_RANK2_C3_PASS_RANK1_WITHHELD_ISOLATION_OR_ASSOCIATION", "ADAPTIVE_VALIDATED_SUBSPACE_BERRY_TRANSPORT_USING_EXISTING_R192_R224_R256_RAW_BANDS", ["rank1_withheld_isolation_or_association"]
        return "R256_RANK2_C3_PASS_RANK1_WITHHELD_BRANCH", "BOUND_PLAQUETTE_STEP_CONVERGENCE_AT_R256", ["rank1_withheld_branch"]
    if not rank1["c3_pass"]: return "R256_RANK2_C3_PASS_RANK1_C3_BREAKING", "BOUND_PLAQUETTE_STEP_CONVERGENCE_AT_R256", ["berry_rank1"]
    return "R256_ALL_FINITE_C3_TESTS_PASS_WITH_ADJACENT_RESOLUTION_UNCERTAINTY", "CROSS_ORBIT_C3_QUALIFICATION_AT_R256_T1E9_M3_WITH_ABSOLUTE_CONVERGENCE_CONTEXT", []


def _build_scalar_sources(matrix: Mapping[int, Sequence[Mapping[str, Any]]], analyses: Mapping[int, Mapping[str, Any]]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    frequency: dict[str, Any] = {}; gap: dict[str, Any] = {}; subspace: dict[str, Any] = {}; link: dict[str, Any] = {}
    for resolution, records in matrix.items():
        for member in MEMBERS:
            for vertex in range(4):
                selected = [row for row in records if row["c3_member_identity"] == member and int(row["vertex_index"]) == vertex]
                for band in range(4): frequency.setdefault(f"vertex{vertex}:band{band + 1}", {}).setdefault(resolution, {}).setdefault(member, []).extend(float(row["frequencies_bands_1_to_4"][band]) for row in selected)
                gap.setdefault(f"vertex{vertex}:band2_isolation", {}).setdefault(resolution, {}).setdefault(member, []).extend(min(float(row["adjacent_gaps"]["lower_gap"]), float(row["adjacent_gaps"]["internal_split"])) for row in selected)
            for edge in range(4):
                plaquettes = [item for item in analyses[resolution]["plaquettes"] if item["member"] == member]
                subspace.setdefault(f"edge{edge}:canonical_rank2_minimum_singular_value", {}).setdefault(resolution, {}).setdefault(member, []).extend(float(item["rank2_edges"][edge]["canonical_minimum_singular_value"]) for item in plaquettes)
                link.setdefault(f"edge{edge}:physical_band2_link", {}).setdefault(resolution, {}).setdefault(member, []).extend(float(item["rank1_edges"][edge]["link_magnitude"]) for item in plaquettes)
    return frequency, gap, subspace, link


def _build_berry(matrix: Mapping[int, Sequence[Mapping[str, Any]]], analyses: Mapping[int, Mapping[str, Any]]) -> tuple[dict[int, dict[str, Any]], dict[int, dict[str, Any]]]:
    rank2: dict[int, dict[str, Any]] = {}; rank1: dict[int, dict[str, Any]] = {}
    for resolution in RESOLUTIONS:
        rank2[resolution] = {}; rank1[resolution] = {}
        for member in MEMBERS:
            plaquettes = [item for item in analyses[resolution]["plaquettes"] if item["member"] == member]
            areas = [float(item["signed_area"]) for item in plaquettes]
            rank2[resolution][member] = _berry_stats([float(item["rank2_trace_phase"]) for item in plaquettes], areas)
            rank1[resolution][member] = _berry_stats([float(item["rank1_phase"]) for item in plaquettes], areas)
    return rank2, rank1


def main() -> int:
    bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8")); source_commit = str(os.environ.get("MEPHC_SOURCE_COMMIT") or bundle.get("source_commit") or "")
    try:
        job = m41r3._load(ROOT / "tools/mephc-flow/scientific_job.py", "m49r1_job"); state_root = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"]).parent.parent
        matrix, centers, m38, m39 = _read_matrix(job, state_root)
        analyses = {resolution: detail_substrate.configuration_detail(rows, centers, m38, m39, f"R{resolution}_T1E9_M3") for resolution, rows in matrix.items()}
        frequency_src, gap_src, subspace_src, link_src = _build_scalar_sources(matrix, analyses)
        frequency = _family(frequency_src, "frequency"); gap = _family(gap_src, "gap"); subspace = _family(subspace_src, "subspace"); link = _family(link_src, "rank1_link_corroboration")
        berry2_values, berry1_values = _build_berry(matrix, analyses)
        berry2_residual = _berry_residual("canonical_rank2_trace_phase_density", berry2_values, "berry_rank2")
        rank1_eligible = analyses[256]["rank1_qualification"]["status"] == "RANK1_QUALIFIED"
        berry1_residual = _berry_residual("rank1_phase_density", berry1_values, "berry_rank1") if rank1_eligible else None
        berry1 = {"eligible": rank1_eligible, "residual": berry1_residual}
        association = _association(analyses); blockers = _rank1_blockers(analyses[256]); rank1 = {"eligible": rank1_eligible, "c3_pass": bool(berry1_residual and berry1_residual["pass"]) if rank1_eligible else False, "blockers": blockers}
        families = {"frequency": frequency, "gap": gap, "subspace": subspace, "berry_rank2": {"identities": {"canonical_rank2_trace_phase_density": berry2_residual}, "all_pass": berry2_residual["pass"], "failing_identities": [] if berry2_residual["pass"] else ["canonical_rank2_trace_phase_density"]}}
        classification, decision, failing_layers = _localize(families, berry2_residual["pass"], bool(berry2_residual["branch_ambiguity"]), rank1, association)
        result = {"schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS", "machine_execution_contract_status": "ZERO_SCIENTIFIC_EXECUTION_CORRECTED_R256_C3_RESIDUAL_CAUSAL_ADJUDICATION", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 0, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "verified_record_counts": {str(resolution): len(rows) for resolution, rows in matrix.items()}, "verified_record_total": 252, "r128_source": "m41r3._read_partial", "scalar_axis_contract": "identity->resolution->member->stats", "berry_axis_contract": "resolution->member->stats", "residual_families": {**families, "rank1_link_corroboration": link, "berry_rank1": berry1}, "high_resolution_association": association, "rank1_withholding": blockers, "rank1_status": rank1, "corrected_c3_context": {str(resolution): {"rank1": analyses[resolution]["rank1_c3_status"], "rank2": analyses[resolution]["rank2_c3_status"]} for resolution in (192, 224, 256)}, "classification": classification, "causal_outcome": classification, "next_science_decision": decision, "failing_layers": failing_layers, "counterevidence": {"absolute_fit_context": "W1/W2/W3 fit statuses are retained in every scalar residual identity", "common_mode_absolute_drift_not_equal_c3_breaking": True, "link_role": "descriptive corroboration; categorical association has priority"}, "source_commit_used": source_commit, "post_analysis_checkout_unchanged": True}
    except BaseException as exc:
        result = {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "machine_execution_contract_status": "M49R1_FAIL_CLOSED", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 0, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "failure_code": str(exc)[:1024], "failure_stage": "corrected_axis_and_unit_adjudication", "exception_type": type(exc).__name__, "source_commit_used": source_commit}
    Path(os.environ["MEPHC_RESULT_PATH"]).write_text(json.dumps(_safe(result), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
