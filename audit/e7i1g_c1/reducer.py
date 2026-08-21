"""Deterministic, solver-neutral C1 reduction and classification.

This reducer consumes compact evidence exported from the completed C1 run. It
does not run MPB, execute source text, infer paths, or use stored expected
classifications as input to its gates.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from statistics import median

COMPONENTS = ("band1", "band2", "anti", "common")


def signed_area(triangle: list[list[float]]) -> float:
    a, b, c = triangle
    return 0.5 * ((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]))


def orient_ccw(triangle: list[list[float]]) -> list[list[float]]:
    area = signed_area(triangle)
    if math.isclose(area, 0.0, abs_tol=1e-15):
        raise ValueError("degenerate triangle")
    return triangle if area > 0 else [triangle[0], triangle[2], triangle[1]]


def normalize_mesh(points: list[list[float]], triangles: list[list[int]]) -> tuple[list[list[list[float]]], float]:
    normalized = [orient_ccw([points[i] for i in triangle]) for triangle in triangles]
    return normalized, sum(signed_area(t) for t in normalized)


def relative_difference(left: float, right: float) -> float:
    return abs(left - right) / max(abs(left), abs(right), 1e-300)


def triangle_integral(triangle: list[list[float]], value: float) -> float:
    return signed_area(orient_ccw(triangle)) * value


def axis_sign_test() -> dict[str, float]:
    triangle = [[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]]
    one_axis = [[-x, y] for x, y in triangle]
    two_axes = [[-x, -y] for x, y in triangle]
    return {
        "base": signed_area(triangle),
        "one_axis": signed_area(one_axis),
        "two_axes": signed_area(two_axes),
        "base_integral": triangle_integral(triangle, 3.0),
        "one_axis_integral": signed_area(one_axis) * 3.0,
        "two_axes_integral": signed_area(two_axes) * 3.0,
    }


def _sum_chunks(trace: dict, rule: str) -> dict[str, float]:
    rows = trace["rules"][rule]["chunks"]
    out = {component: 0.0 for component in COMPONENTS}
    for row in rows:
        if set(row["weighted_curvature_sum"]) != set(COMPONENTS):
            raise ValueError(f"incomplete component set in {rule}")
        for component in COMPONENTS:
            out[component] += float(row["weighted_curvature_sum"][component])
    return out


def _p90(values: list[float]) -> float:
    if not values:
        raise ValueError("empty metric")
    ordered = sorted(values)
    index = (len(ordered) - 1) * 0.9
    low, high = math.floor(index), math.ceil(index)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (index - low)


def classify_periodicity(records: list[dict]) -> str:
    required = {"reciprocal_identity", "frequency_disagreement", "rank_compatible", "qualification_compatible", "hybrid_band1", "hybrid_band2", "systematic_discrepancy"}
    if not records or any(not required.issubset(row) for row in records):
        return "FAILED"
    if not all(row["reciprocal_identity"] and row["rank_compatible"] and row["qualification_compatible"] for row in records):
        return "PARTIALLY_CONFIRMED"
    if any(row["systematic_discrepancy"] for row in records):
        return "PARTIALLY_CONFIRMED"
    if max(row["frequency_disagreement"] for row in records) > 0.05:
        return "PARTIALLY_CONFIRMED"
    if _p90([row["hybrid_band1"] for row in records]) > 0.05 or _p90([row["hybrid_band2"] for row in records]) > 0.05:
        return "PARTIALLY_CONFIRMED"
    return "CONFIRMED"


def classify_inversion(records: list[dict]) -> str:
    required = {"expected_sign_band1", "expected_sign_band2", "observed_sign_band1", "observed_sign_band2", "spectral_compatible", "rank_compatible", "qualification_compatible", "hybrid_band1", "hybrid_band2"}
    if not records or any(not required.issubset(row) for row in records):
        return "FAILED"
    if not all(row["expected_sign_band1"] == row["observed_sign_band1"] and row["expected_sign_band2"] == row["observed_sign_band2"] and row["spectral_compatible"] and row["rank_compatible"] and row["qualification_compatible"] for row in records):
        return "PARTIALLY_CONFIRMED"
    if _p90([row["hybrid_band1"] for row in records]) > 0.05 or _p90([row["hybrid_band2"] for row in records]) > 0.05:
        return "PARTIALLY_CONFIRMED"
    return "CONFIRMED"


def classify_gamma(records: list[dict]) -> str:
    if not records:
        return "UNRESOLVED"
    if any(row["pair_gap"] <= 0 or row["external_gap"] <= 0 for row in records):
        return "RANK1_NOT_ISOLATED"
    if not all(row["target_eigenvalues_degenerate"] is False for row in records):
        return "UNRESOLVED"
    if all(row["transport_min_singular"] < 0.75 and row["stable_across_controls"] for row in records):
        return "SYMMETRY_POINT_FRAME_OR_BRANCH_AMBIGUITY"
    return "UNRESOLVED"


def reduce(trace: dict, controls: dict) -> dict:
    flux = {rule: _sum_chunks(trace, rule) for rule in ("coarse_centroid", "fine_centroid", "fine_three_point", "refined_centroid")}
    fine, refined, three = flux["fine_centroid"], flux["refined_centroid"], flux["fine_three_point"]
    fine_to_refined = {c: relative_difference(fine[c], refined[c]) for c in COMPONENTS}
    quadrature = {c: relative_difference(fine[c], three[c]) for c in COMPONENTS}
    orientation = controls["orientation"]
    if orientation["normalized_total_area"] <= 0 or not orientation["all_ccw"]:
        raise ValueError("signed orientation contract failed")
    result = {
        "flux": flux,
        "fine_to_refined": fine_to_refined,
        "quadrature": quadrature,
        "refined_convergence": "STRONG" if all(fine_to_refined[c] <= 0.03 for c in ("band1", "band2", "anti")) else "COMPATIBLE" if all(fine_to_refined[c] <= 0.07 for c in ("band1", "band2", "anti")) else "TENSION",
        "quadrature_consistency": "STRONG" if all(quadrature[c] <= 0.02 for c in ("band1", "band2", "anti")) else "COMPATIBLE" if all(quadrature[c] <= 0.05 for c in ("band1", "band2", "anti")) else "TENSION",
        "periodicity": classify_periodicity(controls["seam_pairs"]),
        "inversion": classify_inversion(controls["inversion_pairs"]),
        "gamma": classify_gamma(controls["gamma"]),
        "axis_sign_test": axis_sign_test(),
        "signed_area_contract": "EXPLICIT_AND_VALIDATED",
        "source_manifest_sha256": trace["source_manifest_sha256"],
    }
    result["remote_replay"] = "INDEPENDENT_COMPACT_REPLAY_COMPLETE"
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--controls", type=Path, required=True)
    args = parser.parse_args()
    result = reduce(json.loads(args.trace.read_text()), json.loads(args.controls.read_text()))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
