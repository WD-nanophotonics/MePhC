"""Deterministic polygon-set equivalence for realized photonic geometries."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import permutations

import numpy as np


def _polygon(values) -> np.ndarray:
    array = np.asarray(values, dtype=float)
    if array.ndim != 2 or array.shape[1] != 2 or len(array) < 3 or not np.all(np.isfinite(array)):
        raise ValueError("each polygon must be a finite (N, 2) array with at least three vertices")
    return array


def _canonical_shape(values: np.ndarray) -> np.ndarray:
    center = np.mean(values, axis=0)
    centered = values - center
    candidates = []
    for orientation in (centered, centered[::-1]):
        for offset in range(len(orientation)):
            candidates.append(np.roll(orientation, -offset, axis=0))
    return min(candidates, key=lambda item: tuple(np.round(item.reshape(-1), 14)))


def _shape_cost(left: np.ndarray, right: np.ndarray) -> float:
    if len(left) != len(right):
        return float("inf")
    return float(np.max(np.linalg.norm(left - right, axis=1)))


@dataclass(frozen=True, slots=True)
class GeometryEquivalence:
    """Equivalence result for two polygon sets."""

    equivalent: bool
    reason: str
    assignment: tuple[int, ...]
    maximum_shape_error: float
    maximum_position_error: float
    tolerance: float
    shape_only: bool

    def metadata(self) -> dict[str, object]:
        return {
            "equivalent": self.equivalent,
            "reason": self.reason,
            "assignment": list(self.assignment),
            "maximum_shape_error": self.maximum_shape_error,
            "maximum_position_error": self.maximum_position_error,
            "tolerance": self.tolerance,
            "shape_only": self.shape_only,
        }


def match_geometry(reference, candidate, *, tolerance: float = 1e-9, shape_only: bool = False) -> GeometryEquivalence:
    """Match polygon sets independent of polygon and vertex ordering.

    ``shape_only=True`` compares each polygon after centering it at its own
    centroid.  The default additionally requires polygon centroids to agree,
    so a translated/deformed geometry cannot silently be called identical.
    """

    tolerance = float(tolerance)
    if not np.isfinite(tolerance) or tolerance < 0:
        raise ValueError("geometry tolerance must be finite and non-negative")
    left = [_polygon(item) for item in reference]
    right = [_polygon(item) for item in candidate]
    if len(left) != len(right):
        return GeometryEquivalence(False, "polygon_count_mismatch", tuple(), float("inf"), float("inf"), tolerance, shape_only)
    left_shapes = [_canonical_shape(item) for item in left]
    right_shapes = [_canonical_shape(item) for item in right]
    left_centers = [np.mean(item, axis=0) for item in left]
    right_centers = [np.mean(item, axis=0) for item in right]
    costs = np.asarray([[_shape_cost(a, b) for b in right_shapes] for a in left_shapes], dtype=float)
    position_costs = np.asarray([[float(np.linalg.norm(left_centers[i] - right_centers[j])) for j in range(len(right))] for i in range(len(left))], dtype=float)
    if len(left) <= 8:
        candidates = list(permutations(range(len(left))))
        shape_errors = [max((costs[i, candidate[i]] for i in range(len(left))), default=0.0) for candidate in candidates]
        best_shape = min(shape_errors, default=0.0)
        eligible = [candidate for candidate, error in zip(candidates, shape_errors) if error <= best_shape + max(tolerance, 1e-12)]
        assignment = min(eligible, key=lambda candidate: sum(position_costs[i, candidate[i]] for i in range(len(left))))
    else:
        from scipy.optimize import linear_sum_assignment

        rows, columns = linear_sum_assignment(costs)
        assignment_array = np.empty(len(left), dtype=int)
        assignment_array[rows] = columns
        assignment = tuple(int(item) for item in assignment_array)
    shape_error = float(max((costs[i, assignment[i]] for i in range(len(left))), default=0.0))
    position_error = float(max((position_costs[i, assignment[i]] for i in range(len(left))), default=0.0))
    equivalent = shape_error <= tolerance and (shape_only or position_error <= tolerance)
    if equivalent:
        reason = "EQUIVALENT_SHAPE" if shape_only else "EQUIVALENT_ABSOLUTE"
    elif shape_error > tolerance:
        reason = "polygon_shape_difference"
    else:
        reason = "polygon_position_difference"
    return GeometryEquivalence(bool(equivalent), reason, tuple(int(item) for item in assignment), shape_error, position_error, tolerance, shape_only)


__all__ = ["GeometryEquivalence", "match_geometry"]
