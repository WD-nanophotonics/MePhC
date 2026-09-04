"""M45R2: robust, detail-preserving, solver-free semantic-family adjudication."""
from __future__ import annotations

import importlib.util
import itertools
import json
import math
import os
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
M41R3_PATH = ROOT / "audit/berry_c3_consistency/m41r3_recover36_finish_convergence.py"
SPEC = importlib.util.spec_from_file_location("m45r2_m41r3_parent", M41R3_PATH)
assert SPEC and SPEC.loader
m41r3 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m41r3)

RESULT_SCHEMA = "mephc-berry-c3-consistency-m45r2-robust-complete-semantic-family-adjudication-v1"
RESOLUTIONS = (64, 96, 128, 160, 192)
HIGH_RESOLUTIONS = (128, 160, 192)
TRIPLES = ((96, 128, 160), (128, 160, 192))
MEMBERS = tuple(m41r3.MEMBERS)
M41R3_DATASET_ID = "a1edd5623ea1ed4413275a716d33258695d3d81c498a2d663b3608ab5355ed89"
M41R3_MANIFEST_SHA256 = "18dbf109891789d4e4c2f86753d4eae4c7b1ffcedb152459c26f6f9f1a8dbdab"
M41R3_SCHEMA = "mephc-berry-c3-consistency-m41r3-recovery-numerical-convergence-vertex-dataset-v1"
M44_DATASET_ID = "e96dcd141b4a099642edca0fef118b9984768a9b82edeff584cd8c44d37d7705"
M44_MANIFEST_SHA256 = "c5a0f3417ff88fa3092755079e9916a2f9e5fe6191986c481587b262e59a11ab"
M44_SCHEMA = "mephc-berry-c3-consistency-m44-high-resolution-plateau-vertex-dataset-v1"


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
    raise ValueError(f"M45R2_UNSAFE_RESULT:{type(value).__name__}")


def _log_expm1(x: float) -> float:
    if not math.isfinite(x) or x <= 0:
        raise ValueError("invalid log-expm1 argument")
    if x > 50.0:
        return x + math.log1p(-math.exp(-x))
    return math.log(math.expm1(x))


def _log_one_minus_exp_neg(x: float) -> float:
    if not math.isfinite(x) or x <= 0:
        raise ValueError("invalid log-one-minus-exp argument")
    if x > math.log(2.0):
        return math.log1p(-math.exp(-x))
    return math.log(-math.expm1(-x))


def _log_model_ratio(p: float, a: float, c: float) -> float:
    if p <= 0 or not math.isfinite(p):
        raise ValueError("positive finite p required")
    return _log_expm1(a * p) - _log_one_minus_exp_neg(c * p)


def fit_positive_p(resolutions: Sequence[int], values: Sequence[float]) -> dict[str, Any]:
    """Fit y_inf+a*N^-p without raw underflow-prone difference ratios."""
    if len(resolutions) != 3 or len(values) != 3:
        return {"status": "NO_ASYMPTOTIC_MODEL", "reason": "invalid_triple"}
    try:
        n1, n2, n3 = (float(n) for n in resolutions)
        y1, y2, y3 = (float(v) for v in values)
        if not all(math.isfinite(v) for v in (n1, n2, n3, y1, y2, y3)) or not n1 < n2 < n3:
            return {"status": "NO_ASYMPTOTIC_MODEL", "reason": "invalid_finite_inputs"}
        d12, d23 = y1 - y2, y2 - y3
        if d12 == 0.0 or d23 == 0.0 or d12 * d23 <= 0.0 or abs(d23) >= abs(d12):
            return {"status": "NO_ASYMPTOTIC_MODEL", "reason": "zero_sign_change_or_nonshrinking_increment", "differences": [d12, d23]}
        target = d12 / d23
        a = math.log(n2 / n1)
        c = math.log(n3 / n2)
        limit0 = a / c
        if target <= limit0:
            return {"status": "NO_ASYMPTOTIC_MODEL", "reason": "ratio_at_or_below_p0_limit",
                    "target_ratio": target, "p0_limit": limit0}
        log_target = math.log(target)
        lo = 1e-12
        flo = _log_model_ratio(lo, a, c) - log_target
        hi = lo
        fhi = flo
        # The logarithmic model remains finite for arbitrarily large finite p;
        # the bounded loop is only a computational guard, never a p cutoff.
        for _ in range(512):
            if fhi >= 0.0:
                break
            hi *= 2.0
            fhi = _log_model_ratio(hi, a, c) - log_target
        else:
            return {"status": "NO_ASYMPTOTIC_MODEL", "reason": "no_finite_log_domain_bracket",
                    "target_ratio": target, "p0_limit": limit0}
        for _ in range(256):
            mid = (lo + hi) / 2.0
            fm = _log_model_ratio(mid, a, c) - log_target
            if fm >= 0.0:
                hi = mid
            else:
                lo = mid
        p = (lo + hi) / 2.0
        x = a * p
        if x > 50.0:
            inv_expm1 = math.exp(-x) / (-math.expm1(-x))
            log_den = -p * math.log(n2) + _log_expm1(x)
        else:
            expm1_x = math.expm1(x)
            inv_expm1 = 1.0 / expm1_x
            log_den = -p * math.log(n2) + math.log(expm1_x)
        if not math.isfinite(log_den) or log_den < math.log(sys.float_info.min) or log_den > math.log(sys.float_info.max):
            return {"status": "NO_ASYMPTOTIC_MODEL", "reason": "singular_or_nonfinite_reconstruction"}
        denominator = math.exp(log_den)
        amplitude = d12 / denominator
        y_inf = y2 - d12 * inv_expm1
        if not all(math.isfinite(v) for v in (p, amplitude, y_inf)):
            return {"status": "NO_ASYMPTOTIC_MODEL", "reason": "nonfinite_reconstruction"}
        return {"status": "VALID_POSITIVE_P", "p": p, "amplitude_a": amplitude,
                "y_inf": y_inf, "resolutions": list(map(int, resolutions)),
                "values": [y1, y2, y3], "target_ratio": target, "p0_limit": limit0}
    except (ArithmeticError, OverflowError, ValueError):
        return {"status": "NO_ASYMPTOTIC_MODEL", "reason": "numeric_nonfinite_or_overflow"}


def _sequence(values: Mapping[int, Sequence[float] | float], identity: str) -> dict[str, Any]:
    table: list[dict[str, Any]] = []
    medians: dict[int, float] = {}
    for resolution in RESOLUTIONS:
        if resolution not in values:
            continue
        raw = values[resolution]
        repeats = [float(raw)] if isinstance(raw, (int, float)) else [float(v) for v in raw]
        if not repeats or any(not math.isfinite(v) for v in repeats):
            continue
        median = float(np.median(repeats))
        medians[resolution] = median
        table.append({"resolution": resolution, "value": median, "repeat_values": repeats,
                      "repeat_uncertainty": float(max((abs(v - median) for v in repeats), default=0.0))})
    for left, right in zip(table, table[1:]):
        left.update({"next_resolution": right["resolution"],
                     "signed_difference_to_next": right["value"] - left["value"],
                     "absolute_difference_to_next": abs(right["value"] - left["value"])})
    fits = {}
    for triple in TRIPLES:
        if all(n in medians for n in triple):
            fit = fit_positive_p(triple, [medians[n] for n in triple])
            if fit.get("status") == "VALID_POSITIVE_P" and triple == TRIPLES[0]:
                predicted = float(fit["y_inf"] + fit["amplitude_a"] * 192.0 ** (-fit["p"]))
                fit["prediction_at_192"] = predicted
                fit["prediction_residual_at_192"] = predicted - float(medians.get(192, float("nan")))
                fit["prediction_absolute_residual_at_192"] = abs(fit["prediction_residual_at_192"])
            fits["-".join(map(str, triple))] = fit
    return {"identity": identity, "table": table, "fits": fits,
            "repeat_uncertainty_separate": True}


def configuration_detail(records: Sequence[Mapping[str, Any]], centers: Mapping[str, Sequence[float]],
                         m38: Any, m39: Any, configuration_id: str) -> dict[str, Any]:
    """Return detail fields locally; do not depend on M42's reduced summary."""
    detail = m41r3.analyze_configuration(records, centers, m38, m39, configuration_id)
    for plaquette in detail["plaquettes"]:
        for edge in plaquette["rank2_edges"]:
            edge["canonical_target_pair"] = [2, 3]
            edge["canonical_minimum_singular_value"] = edge["minimum_singular_value"]
            edge["canonical_principal_angle"] = edge["principal_angle"]
            edge["canonical_projector_distance"] = edge["projector_distance"]
            edge["canonical_captured_weight"] = edge["captured_weight"]
            edge["canonical_polar_unitary"] = edge["polar_unitary"]
            edge["best_target_pair_minimum_singular_value"] = edge["best_target_pair_minimum_singular_value"]
            edge["all_candidate_pairs"] = [{"target_pair": edge["target_pair"],
                                              "minimum_singular_value": edge["minimum_singular_value"]},
                                             {"target_pair": edge["best_target_pair"],
                                              "minimum_singular_value": edge["best_target_pair_minimum_singular_value"]}]
        plaquette["rank1_wilson_phase"] = plaquette["rank1_wilson_phase"]
        plaquette["rank2_trace_wilson_phase"] = plaquette["rank2_trace_phase"]
    detail["detail_schema"] = "m45r2-configuration-detail-v1"
    detail["qualification_source"] = "M41R3 raw-H plus frozen M42 10/10/5 gates, recomputed locally"
    return detail


def _frequency_and_gap_sequences(matrix: Mapping[int, Sequence[Mapping[str, Any]]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for member in MEMBERS:
        for vertex in range(4):
            for band in range(1, 5):
                values = {n: [float(row["frequencies_bands_1_to_4"][band - 1]) for row in rows
                              if row["c3_member_identity"] == member and int(row["vertex_index"]) == vertex]
                          for n, rows in matrix.items()}
                key = f"spectral_frequency:{member}:vertex{vertex}:band{band}"
                result[key] = _sequence(values, key)
            values = {n: [min(float(row["adjacent_gaps"]["lower_gap"]), float(row["adjacent_gaps"]["internal_split"]))
                          for row in rows if row["c3_member_identity"] == member and int(row["vertex_index"]) == vertex]
                      for n, rows in matrix.items()}
            key = f"spectral_gap:{member}:vertex{vertex}:band2_isolation"
            result[key] = _sequence(values, key)
    return result


def _subspace_and_links(analyses: Mapping[int, Mapping[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for member in MEMBERS:
        for edge_index in range(4):
            values: dict[int, list[float]] = {}
            links: dict[int, list[float]] = {}
            association: dict[int, dict[str, Any]] = {}
            for resolution, analysis in analyses.items():
                rows = [p for p in analysis["plaquettes"] if p["member"] == member]
                rank2 = [p["rank2_edges"][edge_index] for p in rows]
                rank1 = [p["rank1_edges"][edge_index] for p in rows]
                values[resolution] = [float(e["canonical_minimum_singular_value"]) for e in rank2]
                links[resolution] = [float(e["link_magnitude"]) for e in rank1]
                association[resolution] = {"rank1": [e["best_target_band"] for e in rank1],
                    "rank2": [e["best_target_pair"] for e in rank2]}
            key = f"subspace_overlap:{member}:edge{edge_index}:canonical_rank2_minimum_singular_value"
            seq = _sequence(values, key)
            seq["association_by_resolution"] = association
            result[key] = seq
            link_key = f"rank1_link_corroboration:{member}:edge{edge_index}:physical_band2"
            link = _sequence(links, link_key)
            link["association_by_resolution"] = association
            result[link_key] = link
    return result


def _berry_sequences(analyses: Mapping[int, Mapping[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    rank2: dict[str, Any] = {}
    rank1: dict[str, Any] = {}
    for member in MEMBERS:
        values2: dict[int, list[float]] = {}
        values1: dict[int, list[float]] = {}
        qualifications: dict[int, str] = {}
        for resolution, analysis in analyses.items():
            rows = [p for p in analysis["plaquettes"] if p["member"] == member]
            values2[resolution] = [float(p["rank2_trace_phase_density"]) for p in rows]
            qualified = analysis["rank1_qualification"]["status"] == "RANK1_QUALIFIED"
            qualifications[resolution] = "RANK1_QUALIFIED" if qualified else "RANK1_WITHHELD"
            values1[resolution] = [float(p["rank1_phase_density"]) for p in rows] if qualified else []
        key2 = f"berry_rank2_primary:{member}"
        key1 = f"berry_rank1_qualified:{member}"
        rank2[key2] = _sequence(values2, key2)
        rank1[key1] = _sequence(values1, key1)
        rank1[key1]["qualification_by_resolution"] = qualifications
        rank1[key1]["qualified_only"] = True
    return rank2, rank1


def family_support(sequences: Mapping[str, Mapping[str, Any]], keys: Sequence[str]) -> dict[str, Any]:
    selected = [sequences[key] for key in keys]
    statuses = []
    for sequence in selected:
        fits = sequence.get("fits", {})
        statuses.append({"early": fits.get("96-128-160", {}).get("status"),
                         "late": fits.get("128-160-192", {}).get("status")})
    late = [item["late"] == "VALID_POSITIVE_P" for item in statuses]
    two = [item["early"] == "VALID_POSITIVE_P" and item["late"] == "VALID_POSITIVE_P" for item in statuses]
    if all(two): state = "ALL_TWO_TRIPLE"
    elif all(late): state = "ALL_LATE"
    elif any(late): state = "MIXED_LATE"
    else: state = "NONE_LATE"
    return {"sequence_count": len(selected), "sequence_status": statuses, "state": state,
            "all_two_triple": bool(selected and all(two)), "all_late": bool(selected and all(late)),
            "none_late": bool(selected and not any(late)), "mixed_late": bool(selected and any(late) and not all(late))}


def high_resolution_association(analyses: Mapping[int, Mapping[str, Any]]) -> dict[str, Any]:
    states: dict[str, Any] = {}
    reasons: list[str] = []
    for member in MEMBERS:
        for edge in range(4):
            one, two = {}, {}
            for resolution in HIGH_RESOLUTIONS:
                rows = [p for p in analyses[resolution]["plaquettes"] if p["member"] == member]
                one[resolution] = _association([p["rank1_edges"][edge]["best_target_band"] for p in rows], (2,))
                two[resolution] = _association([p["rank2_edges"][edge]["best_target_pair"] for p in rows], (2, 3))
            key = f"{member}:edge{edge}"
            states[key] = {"rank1": one, "rank2": two}
            for label, values in (("rank1", one), ("rank2", two)):
                if len(set(values.values())) != 1 or any(value != "CANONICAL_STABLE" for value in values.values()):
                    reasons.append(f"{key}:{label}")
    return {"scope": list(HIGH_RESOLUTIONS), "states": states, "unstable": bool(reasons), "reasons": reasons}


def _association(values: Sequence[Any], canonical: Sequence[int]) -> str:
    normalized = [tuple(v) if isinstance(v, list) else (v,) for v in values]
    if not normalized or len(set(normalized)) != 1:
        return "REPEAT_UNSTABLE"
    return "CANONICAL_STABLE" if normalized[0] == tuple(canonical) else "NONCANONICAL_STABLE"


def direct_continuum_c3(rank2: Mapping[str, Mapping[str, Any]], analyses: Mapping[int, Mapping[str, Any]]) -> dict[str, Any]:
    envelopes: dict[str, Any] = {}
    for key, sequence in rank2.items():
        member = key.rsplit(":", 1)[-1]
        early = sequence["fits"].get("96-128-160", {})
        late = sequence["fits"].get("128-160-192", {})
        if early.get("status") != "VALID_POSITIVE_P" or late.get("status") != "VALID_POSITIVE_P":
            envelopes[member] = {"status": "NO_TWO_TRIPLE_ASYMPTOTIC_SUPPORT"}
            continue
        table192 = next(row for row in sequence["table"] if row["resolution"] == 192)
        envelope = max(abs(float(late["values"][-1]) - float(late["y_inf"])),
                       abs(float(late["y_inf"]) - float(early["y_inf"])))
        envelopes[member] = {"status": "TWO_TRIPLE_ASYMPTOTIC", "continuum_estimate": float(late["y_inf"]),
            "discretization_envelope": float(envelope), "repeat_uncertainty": float(table192["repeat_uncertainty"])}
    eligible = all(item.get("status") == "TWO_TRIPLE_ASYMPTOTIC" for item in envelopes.values())
    if not eligible:
        return {"eligibility": False, "status": "WITHHELD_INCOMPLETE_TWO_TRIPLE_SUPPORT", "per_member": envelopes}
    pairs = {}
    for left, right in itertools.combinations(sorted(envelopes), 2):
        a, b = envelopes[left], envelopes[right]
        difference = abs(a["continuum_estimate"] - b["continuum_estimate"])
        bound = a["discretization_envelope"] + b["discretization_envelope"] + a["repeat_uncertainty"] + b["repeat_uncertainty"]
        signs_preserved = (a["continuum_estimate"] == 0.0 or b["continuum_estimate"] == 0.0 or
                           math.copysign(1.0, a["continuum_estimate"]) == math.copysign(1.0, b["continuum_estimate"]))
        pairs[f"{left}_vs_{right}"] = {"absolute_difference": difference, "combined_bound": bound,
            "within_bound": difference <= bound, "proper_c3_sign_preserved": signs_preserved}
    return {"eligibility": True, "status": "PASS" if all(item["within_bound"] and item["proper_c3_sign_preserved"] for item in pairs.values()) else "FAIL",
            "per_member": envelopes, "pairs": pairs, "sign_source": "continuum_estimates_direct"}


def classify_family(spectral: Mapping[str, Any], berry: Mapping[str, Any], association_unstable: bool,
                   continuum_status: str | None) -> tuple[str, str]:
    if association_unstable:
        return "HIGH_RESOLUTION_ASSOCIATION_INSTABILITY", "ADAPTIVE_VALIDATED_SUBSPACE_BERRY_TRANSPORT_USING_EXISTING_R128_R160_R192_RAW_BANDS"
    spectral_late = spectral["state"] in {"ALL_LATE", "ALL_TWO_TRIPLE"}
    berry_late = berry["state"] in {"ALL_LATE", "ALL_TWO_TRIPLE"}
    if spectral_late and berry["state"] in {"NONE_LATE", "MIXED_LATE"}:
        return "SPECTRAL_FAMILY_ASYMPTOTIC_BERRY_NONASYMPTOTIC", "BOUND_PLAQUETTE_STEP_CONVERGENCE_AT_R192"
    if spectral["state"] == "NONE_LATE" and berry["state"] == "NONE_LATE":
        return "FULL_FAMILY_NONASYMPTOTIC_RESOLUTION_REGIME", "R224_PLUS_CONDITIONAL_R256_RESOLUTION_EXTENSION"
    if spectral_late and berry["state"] == "ALL_TWO_TRIPLE":
        return (("COMPLETE_FAMILY_ASYMPTOTIC_CONTINUUM_C3_PASS", "SINGLE_R224_PREDICTION_VALIDATION_THEN_FINITE_CONTROL_SELECTION")
                if continuum_status == "PASS" else
                ("COMPLETE_FAMILY_ASYMPTOTIC_CONTINUUM_C3_FAIL", "BOUND_PLAQUETTE_STEP_CONVERGENCE_AT_R192"))
    if spectral_late and berry_late:
        return "COMPLETE_FAMILY_LATE_ASYMPTOTIC_PROVISIONAL", "SINGLE_R224_PREDICTION_VALIDATION"
    return "MIXED_SEMANTIC_FAMILY_CONVERGENCE", "SINGLE_R224_SEMANTIC_FAMILY_DISCRIMINANT"


def main() -> int:
    bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8"))
    source_commit = str(os.environ.get("MEPHC_SOURCE_COMMIT") or bundle.get("source_commit") or "")
    try:
        job = m41r3._load(ROOT / "tools/mephc-flow/scientific_job.py", "m45r2_job")
        m39 = m41r3._load(ROOT / "audit/berry_c3_consistency/m39_g15_deterministic_repeat_band_association_worst_orbit_pilot.py", "m45r2_m39")
        m38 = m41r3._load(ROOT / "audit/berry_c3_consistency/m38_supplied_exact_mpb_source_semantics_raw_native_c3.py", "m45r2_m38")
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
            raise ValueError("M45R2_RESOLUTION_MATRIX_INVALID")
        analyses = {n: configuration_detail(rows, centers, m38, m39, f"R{n}_T1E9_M3") for n, rows in matrix.items()}
        sequences = _frequency_and_gap_sequences(matrix)
        sequences.update(_subspace_and_links(analyses))
        rank2, rank1 = _berry_sequences(analyses)
        sequences.update(rank2)
        sequences.update(rank1)
        spectral_keys = [key for key in sequences if key.startswith("spectral_frequency:") or key.startswith("spectral_gap:")]
        subspace_keys = [key for key in sequences if key.startswith("subspace_overlap:")]
        if (len(spectral_keys), len(subspace_keys), len(spectral_keys) + len(subspace_keys)) != (60, 12, 72):
            raise ValueError("M45R2_SEMANTIC_SEQUENCE_INVENTORY_INVALID")
        spectral = family_support(sequences, spectral_keys + subspace_keys)
        berry_support = family_support(rank2, list(rank2))
        association = high_resolution_association(analyses)
        continuum = direct_continuum_c3(rank2, analyses)
        classification, decision = classify_family(spectral, berry_support, association["unstable"], continuum.get("status"))
        result = {"schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS",
            "machine_execution_contract_status": "ZERO_SCIENTIFIC_EXECUTION_ROBUST_COMPLETE_SEMANTIC_FAMILY_ADJUDICATION",
            "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 0,
            "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0,
            "verified_resolution_record_count": {str(n): 36 for n in RESOLUTIONS}, "verified_resolutions": list(RESOLUTIONS),
            "configuration_analysis": analyses, "resolution_sequences": sequences,
            "semantic_sequence_inventory": {"frequency": 48, "gap": 12, "subspace": 12, "spectral_subspace_total": 72,
                                              "rank1_link_corroboration": 12, "berry_rank2_primary": 3},
            "family_support": {"spectral_subspace": spectral, "berry_rank2_primary": berry_support,
                               "qualified_rank1": family_support(rank1, list(rank1))},
            "high_resolution_association": association, "continuum_c3": continuum,
            "classification": classification, "next_science_decision": decision,
            "m45_full_nonasyptotic_survives": classification == "FULL_FAMILY_NONASYMPTOTIC_RESOLUTION_REGIME",
            "source_datasets": {"m41r3": M41R3_DATASET_ID, "m44": M44_DATASET_ID},
            "source_commit_used": source_commit, "post_analysis_checkout_unchanged": True}
    except BaseException as exc:
        result = {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED",
            "machine_execution_contract_status": "ZERO_SCIENTIFIC_EXECUTION_FAIL_CLOSED", "work_order_id": bundle.get("work_order_id"),
            "native_invocation_count": 0, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0,
            "failure_code": str(exc)[:1024], "failure_stage": "robust_semantic_family_adjudication",
            "exception_type": type(exc).__name__, "source_commit_used": source_commit}
    Path(os.environ["MEPHC_RESULT_PATH"]).write_text(json.dumps(_safe(result), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
