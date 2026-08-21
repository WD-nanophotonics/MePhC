"""Fail-closed C4 reducer for structured exact-domain evidence."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

COMPONENTS = ("band1", "band2", "anti", "common")
SPECTRAL_TOL = 1e-6
HYBRID_TOL = 0.05


def signed_area(triangle):
    a, b, c = triangle
    return 0.5 * ((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]))


def relative_difference(left, right):
    return abs(left - right) / max(abs(left), abs(right), 1e-300)


def axis_sign_test():
    triangle = [[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]]
    one = [[-x, y] for x, y in triangle]
    two = [[-x, -y] for x, y in triangle]
    return {"base": signed_area(triangle), "one_axis": signed_area(one), "two_axes": signed_area(two)}


def _p90(values):
    ordered = sorted(values)
    if not ordered:
        raise ValueError("empty metric")
    index = 0.9 * (len(ordered) - 1)
    lo, hi = math.floor(index), math.ceil(index)
    return ordered[lo] if lo == hi else ordered[lo] + (ordered[hi] - ordered[lo]) * (index - lo)


def _qualified(record):
    return record.get("production_decision") == "QUALIFIED_VALUE"


def _omega(record, band):
    values = record.get("omega_bands_q")
    if not values or len(values) < band:
        raise ValueError("missing raw omega band")
    return float(values[band - 1])


def _hybrid(left, right):
    return abs(left - right) / max(abs(left), abs(right), 1e-300)


def _spectral(left, right):
    lf, rf = left.get("frequencies"), right.get("frequencies")
    if not lf or not rf or len(lf) != len(rf):
        raise ValueError("frequency shape mismatch")
    frequency = max(abs(float(a) - float(b)) for lrow, rrow in zip(lf, rf) for a, b in zip(lrow, rrow))
    return frequency, abs(float(left["pair_gap"]) - float(right["pair_gap"])), abs(float(left["external_gap"]) - float(right["external_gap"]))


def _periodicity_metrics(row):
    left, right = row["a"], row["b"]
    frequency, pair_gap, external_gap = _spectral(left, right)
    return {
        "reciprocal_identity": bool(row.get("reciprocal_identity")),
        "frequency_disagreement": frequency,
        "pair_gap_disagreement": pair_gap,
        "external_gap_disagreement": external_gap,
        "rank_compatible": left.get("rank") == right.get("rank"),
        "qualification_compatible": _qualified(left) and _qualified(right),
        "hybrid_band1": _hybrid(_omega(left, 1), _omega(right, 1)),
        "hybrid_band2": _hybrid(_omega(left, 2), _omega(right, 2)),
    }


def classify_periodicity(records, spectral_tolerance=SPECTRAL_TOL):
    try:
        metrics = [_periodicity_metrics(row) for row in records]
    except (KeyError, TypeError, ValueError):
        return "FAILED"
    if not metrics:
        return "FAILED"
    if not all(row["reciprocal_identity"] and row["rank_compatible"] and row["qualification_compatible"] for row in metrics):
        return "PARTIALLY_CONFIRMED"
    if any(max(row["frequency_disagreement"], row["pair_gap_disagreement"], row["external_gap_disagreement"]) > spectral_tolerance for row in metrics):
        return "PARTIALLY_CONFIRMED"
    if _p90([row["hybrid_band1"] for row in metrics]) > HYBRID_TOL or _p90([row["hybrid_band2"] for row in metrics]) > HYBRID_TOL:
        return "PARTIALLY_CONFIRMED"
    return "CONFIRMED"


def _scale(row, band):
    return abs(float(row.get(f"scale_band{band}", 1.0)))


def classify_inversion(records, spectral_tolerance=SPECTRAL_TOL):
    try:
        metrics = []
        for row in records:
            base, plus = row["base"], row["plus"]
            frequency, pair_gap, external_gap = _spectral(base, plus)
            bands = {}
            for band in (1, 2):
                minus_value, plus_value = _omega(base, band), _omega(plus, band)
                floor = 0.1 * _scale(row, band)
                bands[band] = {
                    "resolved": max(abs(minus_value), abs(plus_value)) >= floor,
                    "sign_reversed": plus_value == 0 or minus_value == 0 or math.copysign(1.0, plus_value) != math.copysign(1.0, minus_value),
                    "antisymmetry": abs(plus_value + minus_value) / max(abs(minus_value), abs(plus_value), floor),
                }
            metrics.append({"spectral": max(frequency, pair_gap, external_gap) <= spectral_tolerance, "rank": base.get("rank") == plus.get("rank"), "qualified": _qualified(base) and _qualified(plus), "bands": bands})
    except (KeyError, TypeError, ValueError):
        return "FAILED"
    if any(not row["spectral"] or not row["rank"] or not row["qualified"] for row in metrics):
        return "PARTIALLY_CONFIRMED"
    if any(value["resolved"] and not value["sign_reversed"] for row in metrics for value in row["bands"].values()):
        return "PARTIALLY_CONFIRMED"
    if any(_p90([row["bands"][band]["antisymmetry"] for row in metrics]) > HYBRID_TOL for band in (1, 2)):
        return "PARTIALLY_CONFIRMED"
    return "CONFIRMED"


def classify_gamma(records):
    if not records:
        return "UNRESOLVED"
    if any(row["pair_gap"] <= 0 or row["external_gap"] <= 0 for row in records):
        return "RANK1_NOT_ISOLATED"
    if not all(row["target_eigenvalues_degenerate"] is False for row in records):
        return "UNRESOLVED"
    if all(row["transport_min_singular"] < 0.75 and row["stable_across_controls"] for row in records):
        return "SYMMETRY_POINT_FRAME_OR_BRANCH_AMBIGUITY"
    return "UNRESOLVED"


def validate_trace(trace, expected_area=1.0 / math.sqrt(3.0)):
    if trace.get("trace_version") != "c4-structured-v1" or not trace.get("source_raw_manifest_sha256"):
        raise ValueError("trace identity is incomplete")
    result = {}
    for rule, payload in trace.get("rules", {}).items():
        chunks = payload.get("chunks", [])
        if [chunk.get("chunk_index") for chunk in chunks] != list(range(len(chunks))):
            raise ValueError(f"chunk order failure: {rule}")
        if len({chunk.get("chunk_index") for chunk in chunks}) != len(chunks):
            raise ValueError(f"duplicate chunk index: {rule}")
        count = sum(int(chunk["input_record_count"]) for chunk in chunks)
        qualified = sum(int(chunk["qualified_count"]) for chunk in chunks)
        weight = sum(float(chunk["signed_weight_sum"]) for chunk in chunks)
        flux = {component: sum(float(chunk["weighted_curvature_sum"][component]) for chunk in chunks) for component in COMPONENTS}
        if count != int(payload["total_record_count"]) or qualified != int(payload["qualified_count"]):
            raise ValueError(f"count closure failure: {rule}")
        if not math.isclose(weight, float(payload["sum_signed_weights"]), rel_tol=0.0, abs_tol=1e-12):
            raise ValueError(f"weight closure failure: {rule}")
        if any(not math.isclose(flux[c], float(payload["resulting_flux"][c]), rel_tol=0.0, abs_tol=1e-10) for c in COMPONENTS):
            raise ValueError(f"flux closure failure: {rule}")
        if payload.get("exact_domain") and not math.isclose(weight, expected_area, rel_tol=0.0, abs_tol=1e-9):
            raise ValueError(f"exact-domain area failure: {rule}")
        result[rule] = {"flux": flux, "weight": weight, "count": count, "qualified": qualified}
    return result


def reduce(trace, controls):
    checked = validate_trace(trace)
    required = ("coarse_centroid", "fine_centroid", "fine_three_point", "refined_centroid")
    if any(name not in checked for name in required):
        raise ValueError("missing exact-domain rule")
    flux = {name: checked[name]["flux"] for name in required}
    coarse, fine, three, refined = (flux[name] for name in ("coarse_centroid", "fine_centroid", "fine_three_point", "refined_centroid"))
    ctf = {c: relative_difference(coarse[c], fine[c]) for c in COMPONENTS}
    ftr = {c: relative_difference(fine[c], refined[c]) for c in COMPONENTS}
    quad = {c: relative_difference(fine[c], three[c]) for c in COMPONENTS}
    convergence = "STRONG" if all(ftr[c] <= 0.03 for c in ("band1", "band2", "anti")) else "COMPATIBLE" if all(ftr[c] <= 0.07 for c in ("band1", "band2", "anti")) else "TENSION"
    quadrature = "STRONG" if all(quad[c] <= 0.02 for c in ("band1", "band2", "anti")) else "COMPATIBLE" if all(quad[c] <= 0.05 for c in ("band1", "band2", "anti")) else "TENSION"
    orientation = controls["orientation"]
    if not orientation["all_ccw"] or not math.isclose(float(orientation["normalized_total_area"]), float(orientation["expected_total_area"]), rel_tol=0.0, abs_tol=1e-9):
        raise ValueError("orientation contract failed")
    return {"flux": flux, "coarse_to_fine": ctf, "fine_to_refined": ftr, "quadrature": quad, "refined_convergence": convergence, "quadrature_consistency": quadrature, "periodicity": classify_periodicity(controls["seam_pairs"]), "inversion": classify_inversion(controls["inversion_pairs"]), "gamma": classify_gamma(controls["gamma"]), "axis_sign_test": axis_sign_test(), "signed_area_contract": "EXPLICIT_AND_VALIDATED", "source_manifest_sha256": trace["source_raw_manifest_sha256"], "remote_replay": "COMPACT_TRACE_REPLAY_COMPLETE", "trace_validation": "STRUCTURALLY_VERIFIABLE"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--controls", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(reduce(json.loads(args.trace.read_text()), json.loads(args.controls.read_text())), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
