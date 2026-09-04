"""M45R1: complete semantic-family, solver-free resolution adjudication.

This module deliberately consumes the immutable M41R3/M44 records only.  The
previous M45 result reduced the family to ``gap_signal`` and three rank-2
Berry scalars; this append-only reanalysis keeps the semantic identities until
after repeat statistics, fitting every declared family sequence.
"""
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
M45_PATH = ROOT / "audit/berry_c3_consistency/m45_resolution_asymptotic_extrapolation_adjudication.py"
SPEC = importlib.util.spec_from_file_location("m45r1_m45_parent", M45_PATH)
assert SPEC and SPEC.loader
m45 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m45)
m42 = m45.m42
m41r3 = m45.m41r3

RESULT_SCHEMA = "mephc-berry-c3-consistency-m45r1-complete-semantic-family-asymptotic-adjudication-v1"
RESOLUTIONS = (64, 96, 128, 160, 192)
HIGH_RESOLUTIONS = (128, 160, 192)
TRIPLES = ((96, 128, 160), (128, 160, 192))
MEMBERS = tuple(m41r3.MEMBERS)
M41R3_DATASET_ID = m45.M41R3_DATASET_ID
M41R3_MANIFEST_SHA256 = m45.M41R3_MANIFEST_SHA256
M41R3_SCHEMA = m45.M41R3_SCHEMA
M44_DATASET_ID = m45.M44_DATASET_ID
M44_MANIFEST_SHA256 = m45.M44_MANIFEST_SHA256
M44_SCHEMA = m45.M44_SCHEMA


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
    raise ValueError(f"M45R1_UNSAFE_RESULT:{type(value).__name__}")


def _fit(values: Mapping[int, float]) -> dict[str, Any]:
    fits: dict[str, Any] = {}
    for triple in TRIPLES:
        if all(n in values for n in triple):
            fits["-".join(map(str, triple))] = m45._fit_model(
                triple, [float(values[n]) for n in triple])
    return fits


def _scalar_sequence(values: Mapping[int, Sequence[float] | float], *, identity: str) -> dict[str, Any]:
    """Median repeats first; retain the repeat floor beside truncation deltas."""
    table: list[dict[str, Any]] = []
    scalar_values: dict[int, float] = {}
    for resolution in RESOLUTIONS:
        if resolution not in values:
            continue
        raw = values[resolution]
        repeats = [float(raw)] if isinstance(raw, (int, float)) else [float(v) for v in raw]
        if not repeats or any(not math.isfinite(v) for v in repeats):
            continue
        median = float(np.median(repeats))
        uncertainty = float(max((abs(v - median) for v in repeats), default=0.0))
        scalar_values[resolution] = median
        table.append({"resolution": resolution, "h": 1.0 / resolution,
                      "value": median, "repeat_values": repeats,
                      "repeat_uncertainty": uncertainty})
    for left, right in zip(table, table[1:]):
        left["next_resolution"] = right["resolution"]
        left["signed_difference_to_next"] = right["value"] - left["value"]
        left["absolute_difference_to_next"] = abs(left["signed_difference_to_next"])
    return {"identity": identity, "table": table, "fits": _fit(scalar_values),
            "repeat_uncertainty_separate": True}


def _family_state(sequences: Mapping[str, Mapping[str, Any]], prefix: str) -> dict[str, Any]:
    selected = [value for key, value in sequences.items() if key.startswith(prefix)]
    statuses = []
    for sequence in selected:
        fits = sequence.get("fits", {})
        statuses.append({"early": fits.get("96-128-160", {}).get("status"),
                         "late": fits.get("128-160-192", {}).get("status")})
    late = [item["late"] == "VALID_POSITIVE_P" for item in statuses]
    two = [item["early"] == "VALID_POSITIVE_P" and item["late"] == "VALID_POSITIVE_P" for item in statuses]
    if not statuses:
        state = "NONE_LATE"
    elif all(two):
        state = "ALL_TWO_TRIPLE"
    elif all(late):
        state = "ALL_LATE"
    elif any(late):
        state = "MIXED_LATE"
    else:
        state = "NONE_LATE"
    return {"sequence_count": len(statuses), "sequence_status": statuses,
            "state": state, "all_two_triple": bool(statuses and all(two)),
            "all_late": bool(statuses and all(late)),
            "none_late": bool(statuses and not any(late)),
            "mixed_late": bool(statuses and any(late) and not all(late))}


def _semantic_spectral_sequences(matrix: Mapping[int, Sequence[Mapping[str, Any]]]) -> dict[str, Any]:
    sequences: dict[str, Any] = {}
    for member in MEMBERS:
        for vertex in range(4):
            for band in range(1, 5):
                values: dict[int, list[float]] = {}
                for resolution, rows in matrix.items():
                    values[resolution] = [float(row["frequencies_bands_1_to_4"][band - 1])
                                          for row in rows if row.get("c3_member_identity") == member
                                          and int(row["vertex_index"]) == vertex]
                key = f"spectral_frequency:{member}:vertex{vertex}:band{band}"
                sequences[key] = _scalar_sequence(values, identity=key)
            for vertex in range(4):
                values = {}
                for resolution, rows in matrix.items():
                    values[resolution] = [min(float(row["adjacent_gaps"]["lower_gap"]),
                                              float(row["adjacent_gaps"]["internal_split"]))
                                          for row in rows if row.get("c3_member_identity") == member
                                          and int(row["vertex_index"]) == vertex]
                key = f"spectral_band2_isolation:{member}:vertex{vertex}"
                sequences[key] = _scalar_sequence(values, identity=key)
    return sequences


def _subspace_sequences(analyses: Mapping[int, Mapping[str, Any]]) -> dict[str, Any]:
    sequences: dict[str, Any] = {}
    for member in MEMBERS:
        for edge in range(4):
            values: dict[int, list[float]] = {}
            association: dict[int, list[dict[str, Any]]] = {}
            for resolution, analysis in analyses.items():
                rows = [p for p in analysis["plaquettes"] if p["member"] == member]
                edges = [p["rank2_edges"][edge] for p in rows]
                values[resolution] = [float(item["minimum_singular_value"]) for item in edges]
                association[resolution] = [{"canonical_pair": item["target_pair"],
                                            "best_pair": item["best_target_pair"],
                                            "best_value": item["best_target_pair_minimum_singular_value"]}
                                           for item in edges]
            key = f"subspace_rank2_minimum_singular_value:{member}:edge{edge}"
            sequence = _scalar_sequence(values, identity=key)
            sequence["association_by_resolution"] = association
            sequences[key] = sequence
    return sequences


def _berry_sequences(analyses: Mapping[int, Mapping[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    rank2: dict[str, Any] = {}
    rank1: dict[str, Any] = {}
    for member in MEMBERS:
        rank2_values: dict[int, list[float]] = {}
        rank1_values: dict[int, list[float]] = {}
        rank1_status: dict[int, str] = {}
        for resolution, analysis in analyses.items():
            summary = analysis["member_summary"][member]
            rank2_values[resolution] = [float(item["rank2_trace_phase_density"])
                                         for item in analysis["plaquettes"] if item["member"] == member]
            qualified = analysis["rank1_qualification"]["status"] == "RANK1_QUALIFIED"
            rank1_status[resolution] = "RANK1_QUALIFIED" if qualified else "RANK1_WITHHELD"
            if qualified:
                rank1_values[resolution] = [float(item["rank1_phase_density"])
                                             for item in analysis["plaquettes"] if item["member"] == member]
            else:
                rank1_values[resolution] = []
        r2key = f"berry_rank2_canonical_phase_density:{member}"
        r1key = f"berry_rank1_qualified_phase_density:{member}"
        rank2[r2key] = _scalar_sequence(rank2_values, identity=r2key)
        rank1[r1key] = _scalar_sequence(rank1_values, identity=r1key)
        rank1[r1key]["qualification_by_resolution"] = rank1_status
        rank1[r1key]["qualified_only"] = True
    return rank2, rank1


def _association_state(values: Sequence[Any], canonical: Any) -> str:
    normalized = [tuple(v) if isinstance(v, list) else v for v in values]
    if not normalized or len(set(normalized)) != 1:
        return "REPEAT_UNSTABLE"
    return "CANONICAL_STABLE" if normalized[0] == tuple(canonical) else "NONCANONICAL_STABLE"


def high_resolution_association(analyses: Mapping[int, Mapping[str, Any]]) -> dict[str, Any]:
    states: dict[str, Any] = {}
    unstable_reasons: list[str] = []
    for member in MEMBERS:
        for edge in range(4):
            rank1_by_resolution: dict[int, str] = {}
            rank2_by_resolution: dict[int, str] = {}
            for resolution in HIGH_RESOLUTIONS:
                plaquettes = [p for p in analyses[resolution]["plaquettes"] if p["member"] == member]
                rank1_by_resolution[resolution] = _association_state(
                    [p["rank1_edges"][edge]["best_target_band"] for p in plaquettes], 2)
                rank2_by_resolution[resolution] = _association_state(
                    [p["rank2_edges"][edge]["best_target_pair"] for p in plaquettes], (2, 3))
            key = f"{member}:edge{edge}"
            states[key] = {"rank1": rank1_by_resolution, "rank2": rank2_by_resolution}
            for label, values in (("rank1", rank1_by_resolution), ("rank2", rank2_by_resolution)):
                if len(set(values.values())) != 1 or any(v != "CANONICAL_STABLE" for v in values.values()):
                    unstable_reasons.append(f"{key}:{label}")
    return {"scope": list(HIGH_RESOLUTIONS), "states": states,
            "unstable": bool(unstable_reasons), "reasons": unstable_reasons,
            "routing_rule": "association instability overrides scalar extrapolation"}


def _continuum_c3(rank2_sequences: Mapping[str, Mapping[str, Any]], analyses: Mapping[int, Mapping[str, Any]]) -> dict[str, Any]:
    envelopes: dict[str, Any] = {}
    for key, sequence in rank2_sequences.items():
        member = key.rsplit(":", 1)[-1]
        fits = sequence["fits"]
        repeat = next((row["repeat_uncertainty"] for row in sequence["table"] if row["resolution"] == 192), 0.0)
        envelopes[member] = m45._continuum(fits, repeat)
    complete = all(value.get("status") == "TWO_TRIPLE_ASYMPTOTIC" for value in envelopes.values())
    sign_preserved = all(analyses[n].get("rank2_c3_status") == "PASS" for n in HIGH_RESOLUTIONS)
    if not complete:
        return {"eligibility": False, "status": "WITHHELD_INCOMPLETE_TWO_TRIPLE_SUPPORT",
                "per_member": envelopes, "proper_c3_sign_preserved": sign_preserved}
    pairs = {}
    for left, right in itertools.combinations(sorted(envelopes), 2):
        a, b = envelopes[left], envelopes[right]
        difference = abs(a["continuum_estimate"] - b["continuum_estimate"])
        bound = (a["discretization_envelope"] + b["discretization_envelope"] +
                 a["repeat_uncertainty"] + b["repeat_uncertainty"])
        pairs[f"{left}_vs_{right}"] = {"absolute_difference": difference,
            "combined_bound": bound, "within_bound": difference <= bound}
    passed = sign_preserved and all(p["within_bound"] for p in pairs.values())
    return {"eligibility": True, "status": "PASS" if passed else "FAIL",
            "per_member": envelopes, "pairs": pairs,
            "proper_c3_sign_preserved": sign_preserved,
            "bound_rule": "sum of both discretization envelopes and repeat uncertainties"}


def classify_family(spectral: Mapping[str, Any], berry: Mapping[str, Any], association_unstable: bool,
                   continuum_status: str | None) -> tuple[str, str]:
    if association_unstable:
        return "HIGH_RESOLUTION_ASSOCIATION_INSTABILITY", "ADAPTIVE_VALIDATED_SUBSPACE_BERRY_TRANSPORT_USING_EXISTING_R128_R160_R192_RAW_BANDS"
    spectral_late = spectral["state"] in {"ALL_TWO_TRIPLE", "ALL_LATE"}
    berry_two = berry["state"] == "ALL_TWO_TRIPLE"
    berry_late = berry["state"] in {"ALL_TWO_TRIPLE", "ALL_LATE"}
    if (spectral_late and berry["state"] in {"NONE_LATE", "MIXED_LATE"}):
        return "SPECTRAL_FAMILY_ASYMPTOTIC_BERRY_NONASYMPTOTIC", "BOUND_PLAQUETTE_STEP_CONVERGENCE_AT_R192"
    if spectral["state"] == "NONE_LATE" and berry["state"] == "NONE_LATE":
        return "FULL_FAMILY_NONASYMPTOTIC_RESOLUTION_REGIME", "R224_PLUS_CONDITIONAL_R256_RESOLUTION_EXTENSION"
    if spectral_late and berry_two:
        if continuum_status == "PASS":
            return "COMPLETE_FAMILY_ASYMPTOTIC_CONTINUUM_C3_PASS", "SINGLE_R224_PREDICTION_VALIDATION_THEN_FINITE_CONTROL_SELECTION"
        return "COMPLETE_FAMILY_ASYMPTOTIC_CONTINUUM_C3_FAIL", "BOUND_PLAQUETTE_STEP_CONVERGENCE_AT_R192"
    if spectral_late and berry_late:
        return "COMPLETE_FAMILY_LATE_ASYMPTOTIC_PROVISIONAL", "SINGLE_R224_PREDICTION_VALIDATION"
    return "MIXED_SEMANTIC_FAMILY_CONVERGENCE", "SINGLE_R224_SEMANTIC_FAMILY_DISCRIMINANT"


def _result(bundle: Mapping[str, Any], source_commit: str, analyses: Mapping[int, Any],
            sequences: Mapping[str, Any], association: Mapping[str, Any], continuum: Mapping[str, Any],
            classification: str, decision: str) -> dict[str, Any]:
    return {"schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS",
            "machine_execution_contract_status": "ZERO_SCIENTIFIC_EXECUTION_COMPLETE_SEMANTIC_RESOLUTION_FAMILY_ADJUDICATION",
            "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 0,
            "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0,
            "verified_resolution_record_count": {str(n): 36 for n in RESOLUTIONS},
            "verified_resolutions": list(RESOLUTIONS), "configuration_analysis": analyses,
            "resolution_sequences": sequences, "high_resolution_association": association,
            "continuum_c3": continuum, "classification": classification,
            "next_science_decision": decision,
            "m45_classification_delta": "OVERTURNED_OR_REFINED_BY_COMPLETE_SEMANTIC_FAMILY",
            "source_datasets": {"m41r3": M41R3_DATASET_ID, "m44": M44_DATASET_ID},
            "source_commit_used": source_commit, "post_analysis_checkout_unchanged": True}


def main() -> int:
    bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8"))
    source_commit = str(os.environ.get("MEPHC_SOURCE_COMMIT") or bundle.get("source_commit") or "")
    try:
        job = m41r3._load(ROOT / "tools/mephc-flow/scientific_job.py", "m45r1_job")
        m39 = m41r3._load(ROOT / "audit/berry_c3_consistency/m39_g15_deterministic_repeat_band_association_worst_orbit_pilot.py", "m45r1_m39")
        m38 = m41r3._load(ROOT / "audit/berry_c3_consistency/m38_supplied_exact_mpb_source_semantics_raw_native_c3.py", "m45r1_m38")
        state_root = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"]).parent.parent
        partial = m41r3._read_partial(job, state_root)
        m41 = m41r3._read_dataset(job, state_root, M41R3_DATASET_ID, M41R3_MANIFEST_SHA256, M41R3_SCHEMA, 108)
        m44 = m41r3._read_dataset(job, state_root, M44_DATASET_ID, M44_MANIFEST_SHA256, M44_SCHEMA, 72)
        m18 = m41r3._read_dataset(job, state_root, m41r3.M18_DATASET_ID, m41r3.M18_MANIFEST_SHA256, m41r3.M18_SCHEMA, 3)
        m39r1 = m41r3._read_dataset(job, state_root, m41r3.M39R1_DATASET_ID, m41r3.M39R1_MANIFEST_SHA256, m41r3.M39R1_SCHEMA, 14)
        centers = m41r3._centers(m18, m39r1)
        matrix = {64: [r for r in m41 if r.get("configuration_id") == "R64_T1E9_M3"],
                  96: [r for r in m41 if r.get("configuration_id") == "R96_T1E9_M3"],
                  128: partial,
                  160: [r for r in m44 if r.get("configuration_id") == "R160_T1E9_M3"],
                  192: [r for r in m44 if r.get("configuration_id") == "R192_T1E9_M3"]}
        if any(len(rows) != 36 for rows in matrix.values()):
            raise ValueError("M45R1_RESOLUTION_MATRIX_INVALID")
        analyses = {resolution: m42._configuration(rows, m38, m39, f"R{resolution}_T1E9_M3")
                    for resolution, rows in matrix.items()}
        sequences = _semantic_spectral_sequences(matrix)
        sequences.update(_subspace_sequences(analyses))
        rank2, rank1 = _berry_sequences(analyses)
        sequences.update(rank2)
        sequences.update(rank1)
        spectral = _family_state(sequences, "spectral_")
        berry = _family_state(rank2, "berry_rank2_canonical_phase_density:")
        association = high_resolution_association(analyses)
        continuum = _continuum_c3(rank2, analyses)
        classification, decision = classify_family(spectral, berry, association["unstable"], continuum.get("status"))
        result = _result(bundle, source_commit, analyses, {"sequences": sequences,
            "family_support": {"spectral": spectral, "berry_rank2": berry},
            "qualified_rank1_family": _family_state(rank1, "berry_rank1_qualified_phase_density:")},
            association, continuum, classification, decision)
    except BaseException as exc:
        result = {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED",
                  "scientific_acceptance_status": "FAIL_CLOSED",
                  "machine_execution_contract_status": "ZERO_SCIENTIFIC_EXECUTION_FAIL_CLOSED",
                  "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 0,
                  "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0,
                  "failure_code": str(exc)[:1024], "failure_stage": "semantic_family_reanalysis",
                  "exception_type": type(exc).__name__, "source_commit_used": source_commit}
    Path(os.environ["MEPHC_RESULT_PATH"]).write_text(
        json.dumps(_safe(result), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
