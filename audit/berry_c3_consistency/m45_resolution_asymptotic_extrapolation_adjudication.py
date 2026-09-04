"""M45: solver-free asymptotic resolution adjudication."""
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
M42_PATH = ROOT / "audit/berry_c3_consistency/m42_m41r3_corrected_uncertainty_cheapest_control_adjudication.py"
SPEC = importlib.util.spec_from_file_location("m45_m42_parent", M42_PATH)
assert SPEC and SPEC.loader
m42 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m42)
m41r3 = m42.m41r3

RESULT_SCHEMA = "mephc-berry-c3-consistency-m45-resolution-asymptotic-extrapolation-adjudication-v1"
M41R3_DATASET_ID = "a1edd5623ea1ed4413275a716d33258695d3d81c498a2d663b3608ab5355ed89"
M41R3_MANIFEST_SHA256 = "18dbf109891789d4e4c2f86753d4eae4c7b1ffcedb152459c26f6f9f1a8dbdab"
M41R3_SCHEMA = "mephc-berry-c3-consistency-m41r3-recovery-numerical-convergence-vertex-dataset-v1"
M44_DATASET_ID = "e96dcd141b4a099642edca0fef118b9984768a9b82edeff584cd8c44d37d7705"
M44_MANIFEST_SHA256 = "c5a0f3417ff88fa3092755079e9916a2f9e5fe6191986c481587b262e59a11ab"
M44_SCHEMA = "mephc-berry-c3-consistency-m44-high-resolution-plateau-vertex-dataset-v1"
RESOLUTIONS = (64, 96, 128, 160, 192)
TRIPLES = ((96, 128, 160), (128, 160, 192))
MEMBERS = m41r3.MEMBERS


def _safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)): return value
    if isinstance(value, float): return value if math.isfinite(value) else ("INF" if value > 0 else "-INF" if value < 0 else "NAN")
    if isinstance(value, np.generic): return _safe(value.item())
    if isinstance(value, complex): return [_safe(float(value.real)), _safe(float(value.imag))]
    if isinstance(value, np.ndarray): return _safe(value.tolist())
    if isinstance(value, Mapping): return {str(k): _safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)): return [_safe(v) for v in value]
    raise ValueError(f"M45_UNSAFE_RESULT:{type(value).__name__}")


def _fit_model(resolutions: Sequence[int], values: Sequence[float]) -> dict[str, Any]:
    """Fit y_inf+a*N^-p, withholding when no positive real p is supported."""
    if len(resolutions) != 3 or len(values) != 3 or any(not math.isfinite(float(v)) for v in values):
        return {"status": "NO_ASYMPTOTIC_MODEL", "reason": "invalid_triple"}
    n1, n2, n3 = [float(n) for n in resolutions]
    y1, y2, y3 = [float(v) for v in values]
    d12, d23 = y1 - y2, y2 - y3
    if d12 == 0.0 or d23 == 0.0 or d12 * d23 <= 0.0 or abs(d23) >= abs(d12):
        return {"status": "NO_ASYMPTOTIC_MODEL", "reason": "zero_sign_change_or_nonshrinking_increment", "differences": [d12, d23]}
    ratio = d12 / d23
    def model_ratio(p: float) -> float:
        return (n1 ** (-p) - n2 ** (-p)) / (n2 ** (-p) - n3 ** (-p))
    lo = 1e-12
    hi = 1.0
    target_at_lo = model_ratio(lo) - ratio
    for _ in range(80):
        if (model_ratio(hi) - ratio) * target_at_lo <= 0.0: break
        hi *= 2.0
    else:
        return {"status": "NO_ASYMPTOTIC_MODEL", "reason": "no_positive_real_root", "difference_ratio": ratio}
    for _ in range(160):
        mid = (lo + hi) / 2.0
        if (model_ratio(mid) - ratio) * target_at_lo <= 0.0: hi = mid
        else: lo = mid
    p = (lo + hi) / 2.0
    basis1, basis2 = n1 ** (-p), n2 ** (-p)
    amplitude = d12 / (basis1 - basis2)
    y_inf = y1 - amplitude * basis1
    return {"status": "VALID_POSITIVE_P", "p": p, "amplitude_a": amplitude, "y_inf": y_inf, "resolutions": list(map(int, resolutions)), "values": list(map(float, values)), "difference_ratio": ratio, "last_increment_shrinks": True}


def _sequence(values_by_resolution: Mapping[int, float]) -> dict[str, Any]:
    table = [{"resolution": int(resolution), "h": 1.0 / resolution, "value": float(values_by_resolution[resolution])} for resolution in RESOLUTIONS if resolution in values_by_resolution]
    for left, right in zip(table, table[1:]):
        left["next_resolution"] = right["resolution"]
        left["signed_difference_to_next"] = right["value"] - left["value"]
        left["absolute_difference_to_next"] = abs(left["signed_difference_to_next"])
    fits = {}
    for triple in TRIPLES:
        if all(resolution in values_by_resolution for resolution in triple):
            fits["-".join(map(str, triple))] = _fit_model(triple, [values_by_resolution[resolution] for resolution in triple])
    return {"table": table, "fits": fits, "repeat_uncertainty_separate": True}


def _continuum(fits: Mapping[str, Mapping[str, Any]], repeat_uncertainty: float) -> dict[str, Any]:
    early, late = fits.get("96-128-160", {}), fits.get("128-160-192", {})
    if early.get("status") != "VALID_POSITIVE_P" or late.get("status") != "VALID_POSITIVE_P":
        return {"status": "NO_TWO_TRIPLE_ASYMPTOTIC_SUPPORT", "repeat_uncertainty": repeat_uncertainty}
    envelope = max(abs(float(late["values"][-1]) - float(late["y_inf"])), abs(float(late["y_inf"]) - float(early["y_inf"])))
    return {"status": "TWO_TRIPLE_ASYMPTOTIC", "continuum_estimate": float(late["y_inf"]), "discretization_envelope": float(envelope), "repeat_uncertainty": float(repeat_uncertainty), "central_fit": "128-160-192"}


def _pairwise_continuum(member_values: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    pairs = {}
    for left, right in itertools.combinations(sorted(member_values), 2):
        a, b = member_values[left], member_values[right]
        difference = abs(a["continuum_estimate"] - b["continuum_estimate"])
        bound = a["discretization_envelope"] + b["discretization_envelope"] + a["repeat_uncertainty"] + b["repeat_uncertainty"]
        pairs[f"{left}_vs_{right}"] = {"absolute_difference": difference, "combined_envelope_and_repeat_uncertainty": bound, "within_envelope": difference <= bound}
    return {"pairs": pairs, "status": "PASS" if all(item["within_envelope"] for item in pairs.values()) else "FAIL"}


def classify(spectral_support: bool, berry_support: bool, association_unstable: bool, continuum_c3: str | None) -> tuple[str, str]:
    if association_unstable: return "HIGH_RESOLUTION_ASSOCIATION_INSTABILITY", "ADAPTIVE_VALIDATED_SUBSPACE_BERRY_TRANSPORT_USING_EXISTING_R128_R160_R192_RAW_BANDS"
    if spectral_support and not berry_support: return "SPECTRAL_ASYMPTOTIC_BERRY_NONASYMPTOTIC", "BOUND_PLAQUETTE_STEP_CONVERGENCE_AT_R192"
    if not spectral_support and not berry_support: return "FULL_NONASYMPTOTIC_RESOLUTION_REGIME", "R224_PLUS_CONDITIONAL_R256_RESOLUTION_EXTENSION"
    if continuum_c3 == "PASS": return "ASYMPTOTIC_RESOLUTION_CONVERGENCE_WITH_CONTINUUM_C3_PASS", "SINGLE_R224_PREDICTION_VALIDATION_THEN_FINITE_CONTROL_SELECTION"
    if continuum_c3 == "FAIL": return "ASYMPTOTIC_RESOLUTION_CONVERGENCE_WITH_CONTINUUM_C3_FAIL", "BOUND_PLAQUETTE_STEP_CONVERGENCE_AT_R192"
    if berry_support: return "ASYMPTOTIC_RESOLUTION_CONVERGENCE_CONTINUUM_C3_PROVISIONAL", "SINGLE_R224_PREDICTION_VALIDATION"
    return "MIXED_OR_UNRESOLVED_CONVERGENCE_EVIDENCE", "TARGETED_NEXT_DISCRIMINANT_FROM_M45_EVIDENCE"


def _result(bundle: Mapping[str, Any], source_commit: str, analyses: Mapping[str, Any], sequences: Mapping[str, Any], continuum: Mapping[str, Any], classification: str, decision: str, counts=(0, 0, 0, 0)) -> dict[str, Any]:
    return {"schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS", "machine_execution_contract_status": "ZERO_SCIENTIFIC_EXECUTION_RESOLUTION_ASYMPTOTIC_COMPLETE", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": counts[0], "provider_execution_count": counts[1], "solver_execution_count": counts[2], "dataset_record_count": counts[3], "verified_resolutions": list(RESOLUTIONS), "configuration_analysis": analyses, "resolution_sequences": sequences, "continuum_envelopes": continuum, "classification": classification, "next_science_decision": decision, "source_datasets": {"m41r3": M41R3_DATASET_ID, "m44": M44_DATASET_ID}, "source_commit_used": source_commit, "post_analysis_checkout_unchanged": True}


def main() -> int:
    bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8"))
    source_commit = str(os.environ.get("MEPHC_SOURCE_COMMIT") or bundle.get("source_commit") or "")
    try:
        job = m41r3._load(ROOT / "tools/mephc-flow/scientific_job.py", "m45_job")
        m39 = m41r3._load(ROOT / "audit/berry_c3_consistency/m39_g15_deterministic_repeat_band_association_worst_orbit_pilot.py", "m45_m39")
        m38 = m41r3._load(ROOT / "audit/berry_c3_consistency/m38_supplied_exact_mpb_source_semantics_raw_native_c3.py", "m45_m38")
        state_root = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"]).parent.parent
        partial = m41r3._read_partial(job, state_root)
        m41 = m41r3._read_dataset(job, state_root, M41R3_DATASET_ID, M41R3_MANIFEST_SHA256, M41R3_SCHEMA, 108)
        m44 = m41r3._read_dataset(job, state_root, M44_DATASET_ID, M44_MANIFEST_SHA256, M44_SCHEMA, 72)
        m18 = m41r3._read_dataset(job, state_root, m41r3.M18_DATASET_ID, m41r3.M18_MANIFEST_SHA256, m41r3.M18_SCHEMA, 3)
        m39r1 = m41r3._read_dataset(job, state_root, m41r3.M39R1_DATASET_ID, m41r3.M39R1_MANIFEST_SHA256, m41r3.M39R1_SCHEMA, 14)
        centers = m41r3._centers(m18, m39r1)
        matrix = {64: [r for r in m41 if r.get("configuration_id") == "R64_T1E9_M3"], 96: [r for r in m41 if r.get("configuration_id") == "R96_T1E9_M3"], 128: partial, 160: [r for r in m44 if r.get("configuration_id") == "R160_T1E9_M3"], 192: [r for r in m44 if r.get("configuration_id") == "R192_T1E9_M3"]}
        if any(len(rows) != 36 for rows in matrix.values()): raise ValueError("M45_RESOLUTION_MATRIX_INVALID")
        analyses = {f"R{resolution}_T1E9_M3": m42._configuration(rows, m38, m39, f"R{resolution}_T1E9_M3") for resolution, rows in matrix.items()}
        sequences: dict[str, Any] = {}
        for member in MEMBERS:
            sequences[f"{member}:rank2_trace_phase_density"] = _sequence({resolution: analyses[f"R{resolution}_T1E9_M3"]["member_summary"][member]["rank2_trace_phase_density"]["median"] for resolution in RESOLUTIONS})
            sequences[f"{member}:rank1_phase_density"] = _sequence({resolution: analyses[f"R{resolution}_T1E9_M3"]["member_summary"][member]["rank1_phase_density"]["median"] for resolution in RESOLUTIONS})
            sequences[f"{member}:gap_signal"] = _sequence({resolution: analyses[f"R{resolution}_T1E9_M3"]["member_summary"][member]["gap_signal"] for resolution in RESOLUTIONS})
        continuum = {}
        berry_support = True
        for member in MEMBERS:
            key = f"{member}:rank2_trace_phase_density"
            fits = sequences[key]["fits"]
            envelope = _continuum(fits, analyses["R192_T1E9_M3"]["member_summary"][member]["rank2_trace_phase_density"]["uncertainty"])
            continuum[key] = envelope
            berry_support = berry_support and envelope["status"] == "TWO_TRIPLE_ASYMPTOTIC"
        members_with_support = {member: continuum[f"{member}:rank2_trace_phase_density"] for member in MEMBERS if continuum[f"{member}:rank2_trace_phase_density"].get("status") == "TWO_TRIPLE_ASYMPTOTIC"}
        continuum_c3 = _pairwise_continuum(members_with_support)["status"] if len(members_with_support) == 3 else None
        spectral_support = all(sequences[f"{member}:gap_signal"]["fits"].get("128-160-192", {}).get("status") == "VALID_POSITIVE_P" for member in MEMBERS)
        association_unstable = any(not analysis["rank2_association_stable"] for analysis in analyses.values())
        classification, decision = classify(spectral_support, berry_support, association_unstable, continuum_c3)
        result = _result(bundle, source_commit, analyses, sequences, {"per_member": continuum, "continuum_c3": continuum_c3}, classification, decision)
    except BaseException as exc:
        result = {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "machine_execution_contract_status": "ZERO_SCIENTIFIC_EXECUTION_FAIL_CLOSED", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 0, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "failure_code": str(exc)[:1024], "failure_stage": "read_only_resolution_reanalysis", "exception_type": type(exc).__name__, "source_commit_used": source_commit}
    Path(os.environ["MEPHC_RESULT_PATH"]).write_text(json.dumps(_safe(result), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__": raise SystemExit(main())
