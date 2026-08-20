"""Canonical local plaquette geometry and provenance semantics.

This module is solver-neutral.  It distinguishes the centered production
definition from the historical forward/reproduction convention without
interpreting either one as a scientific qualification by itself.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from numbers import Real
from typing import Any, Mapping, Sequence

import numpy as np


CENTERED_CCW = "CENTERED_CCW"
LEGACY_FORWARD_CCW = "LEGACY_FORWARD_CCW"
PLAQUETTE_CONVENTIONS = frozenset({CENTERED_CCW, LEGACY_FORWARD_CCW})


def _vector(value: Any, *, name: str) -> tuple[float, float]:
    array = np.asarray(value)
    if array.ndim != 1 or array.size != 2 or array.dtype.kind not in "iuf":
        raise ValueError(f"{name} must be a finite real 2-vector")
    values = tuple(float(item) for item in array)
    if not all(math.isfinite(item) for item in values):
        raise ValueError(f"{name} must be finite")
    return values


def _positive(value: Any, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a positive real number")
    result = float(value)
    if not math.isfinite(result) or result <= 0.0:
        raise ValueError(f"{name} must be a positive real number")
    return result


def polygon_signed_area(vertices: Sequence[Sequence[float]]) -> float:
    """Return the signed Cartesian area of an ordered polygon."""
    points = np.asarray(vertices, dtype=float)
    if points.ndim != 2 or points.shape != (4, 2) or not np.all(np.isfinite(points)):
        raise ValueError("vertices must be four finite Cartesian 2-vectors")
    return float(0.5 * np.sum(
        points[:, 0] * np.roll(points[:, 1], -1)
        - points[:, 1] * np.roll(points[:, 0], -1)
    ))


@dataclass(frozen=True)
class LocalPlaquetteGeometry:
    requested_k: tuple[float, float]
    geometric_center: tuple[float, float]
    convention: str
    ordered_vertices: tuple[tuple[float, float], ...]
    dx: tuple[float, float]
    dy: tuple[float, float]
    signed_area: float
    orientation: str

    def __post_init__(self) -> None:
        requested = _vector(self.requested_k, name="requested_k")
        center = _vector(self.geometric_center, name="geometric_center")
        dx = _vector(self.dx, name="dx")
        dy = _vector(self.dy, name="dy")
        if self.convention not in PLAQUETTE_CONVENTIONS:
            raise ValueError(f"unsupported plaquette convention: {self.convention}")
        vertices = tuple(_vector(point, name="ordered_vertices[]") for point in self.ordered_vertices)
        if len(vertices) != 4:
            raise ValueError("a local plaquette requires exactly four vertices")
        area = polygon_signed_area(vertices)
        if abs(area) <= 0.0:
            raise ValueError("plaquette area must be non-zero")
        expected_center = tuple(float(value) for value in np.mean(np.asarray(vertices), axis=0))
        if not np.allclose(center, expected_center, rtol=0.0, atol=1e-12):
            raise ValueError("geometric_center must equal the vertex arithmetic mean")
        if not np.allclose(float(self.signed_area), area, rtol=0.0, atol=1e-12):
            raise ValueError("signed_area does not match ordered_vertices")
        orientation = "CCW" if area > 0.0 else "CW"
        if self.orientation != orientation:
            raise ValueError("orientation does not match signed_area")
        object.__setattr__(self, "requested_k", requested)
        object.__setattr__(self, "geometric_center", center)
        object.__setattr__(self, "dx", dx)
        object.__setattr__(self, "dy", dy)
        object.__setattr__(self, "ordered_vertices", vertices)
        object.__setattr__(self, "signed_area", area)

    @property
    def area(self) -> float:
        return self.signed_area

    def to_dict(self) -> dict[str, Any]:
        return {
            "requested_k": list(self.requested_k),
            "geometric_center": list(self.geometric_center),
            "convention": self.convention,
            "ordered_vertices": [list(point) for point in self.ordered_vertices],
            "dx": list(self.dx),
            "dy": list(self.dy),
            "signed_area": self.signed_area,
            "orientation": self.orientation,
        }


def build_local_plaquette(
    requested_k: Sequence[float],
    dx: Sequence[float] | float,
    dy: Sequence[float] | float | None = None,
    *,
    convention: str = CENTERED_CCW,
) -> LocalPlaquetteGeometry:
    """Build a centered or legacy forward parallelogram in Cartesian k space.

    Scalar ``dx``/``dy`` values are accepted as axis-aligned displacements for
    compatibility with square-grid callers.  Vector displacements support
    nonorthogonal reciprocal-coordinate studies.
    """
    requested = _vector(requested_k, name="requested_k")
    if isinstance(dx, Real) and not isinstance(dx, bool):
        x_step = _positive(dx, name="dx")
        if dy is None:
            y_step = x_step
        elif isinstance(dy, Real) and not isinstance(dy, bool):
            y_step = _positive(dy, name="dy")
        else:
            raise ValueError("scalar dx requires scalar dy")
        dx_vector, dy_vector = (x_step, 0.0), (0.0, y_step)
    else:
        dx_vector = _vector(dx, name="dx")
        if dy is None:
            raise ValueError("vector dx requires vector dy")
        dy_vector = _vector(dy, name="dy")
    if convention not in PLAQUETTE_CONVENTIONS:
        raise ValueError(f"unsupported plaquette convention: {convention}")
    k = np.asarray(requested, dtype=float)
    dx_array = np.asarray(dx_vector, dtype=float)
    dy_array = np.asarray(dy_vector, dtype=float)
    cross = float(dx_array[0] * dy_array[1] - dx_array[1] * dy_array[0])
    if not math.isfinite(cross) or cross == 0.0:
        raise ValueError("dx and dy must span a nondegenerate parallelogram")
    if convention == CENTERED_CCW:
        half_x, half_y = dx_array / 2.0, dy_array / 2.0
        vertices = (k - half_x - half_y, k + half_x - half_y,
                    k + half_x + half_y, k - half_x + half_y)
    else:
        vertices = (k, k + dx_array, k + dx_array + dy_array, k + dy_array)
    points = tuple(tuple(float(item) for item in point) for point in vertices)
    center = tuple(float(item) for item in np.mean(np.asarray(points), axis=0))
    area = polygon_signed_area(points)
    return LocalPlaquetteGeometry(
        requested_k=requested,
        geometric_center=center,
        convention=convention,
        ordered_vertices=points,
        dx=dx_vector,
        dy=dy_vector,
        signed_area=area,
        orientation="CCW" if area > 0.0 else "CW",
    )


__all__ = [
    "CENTERED_CCW",
    "LEGACY_FORWARD_CCW",
    "PLAQUETTE_CONVENTIONS",
    "LocalPlaquetteGeometry",
    "build_local_plaquette",
    "polygon_signed_area",
]
