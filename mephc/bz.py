"""Generic reciprocal-lattice and first-Brillouin-zone geometry."""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np

from .bravais import BravaisLattice2D


def _signed_area(vertices: np.ndarray) -> float:
    return 0.5 * float(np.sum(vertices[:, 0] * np.roll(vertices[:, 1], -1) - vertices[:, 1] * np.roll(vertices[:, 0], -1)))


def _cross2d(left: np.ndarray, right: np.ndarray) -> float:
    """Return the scalar z-component of a 2-D cross product."""
    return float(left[0] * right[1] - left[1] * right[0])


def _clip_half_plane(polygon: np.ndarray, normal: np.ndarray, bound: float, tolerance: float) -> np.ndarray:
    """Clip a convex polygon against ``dot(normal, x) <= bound``."""

    if len(polygon) == 0:
        return polygon
    output: list[np.ndarray] = []

    def inside(point: np.ndarray) -> bool:
        return float(np.dot(normal, point)) <= bound + tolerance

    for start, end in zip(polygon, np.roll(polygon, -1, axis=0)):
        start_inside = inside(start)
        end_inside = inside(end)
        if start_inside:
            output.append(start)
        if start_inside != end_inside:
            denominator = float(np.dot(normal, end - start))
            if abs(denominator) <= np.finfo(float).eps:
                continue
            fraction = (bound - float(np.dot(normal, start))) / denominator
            output.append(start + fraction * (end - start))
    if not output:
        return np.empty((0, 2), dtype=float)
    return np.asarray(output, dtype=float)


def _reciprocal_vectors(basis: np.ndarray, shell: int) -> list[np.ndarray]:
    vectors = []
    for i in range(-shell, shell + 1):
        for j in range(-shell, shell + 1):
            if i == 0 and j == 0:
                continue
            vector = basis @ np.array([float(i), float(j)])
            vectors.append(vector)
    vectors.sort(key=lambda vector: (float(np.dot(vector, vector)), math.atan2(float(vector[1]), float(vector[0]))) )
    return vectors


def _canonicalize(vertices: np.ndarray, tolerance: float) -> np.ndarray:
    if len(vertices) < 3:
        raise ValueError("first Brillouin-zone clipping returned fewer than three vertices")
    clean: list[np.ndarray] = []
    for point in vertices:
        if not clean or not np.allclose(point, clean[-1], atol=tolerance, rtol=0.0):
            clean.append(point)
    if len(clean) > 1 and np.allclose(clean[0], clean[-1], atol=tolerance, rtol=0.0):
        clean.pop()
    result = np.asarray(clean, dtype=float)
    # Remove clipping-generated collinear vertices so the public polygon is a
    # strict convex open vertex list.
    changed = True
    while changed and len(result) > 3:
        changed = False
        keep = []
        for index in range(len(result)):
            previous = result[index - 1]
            current = result[index]
            following = result[(index + 1) % len(result)]
            cross = _cross2d(current - previous, following - current)
            if abs(float(cross)) <= tolerance:
                changed = True
            else:
                keep.append(current)
        if changed:
            result = np.asarray(keep, dtype=float)
    if _signed_area(result) < 0:
        result = result[::-1]
    start = min(range(len(result)), key=lambda index: (-result[index, 0], result[index, 1]))
    return np.roll(result, -start, axis=0)


def _polygon_valid(vertices: np.ndarray, reciprocal_basis: np.ndarray, tolerance: float) -> bool:
    reciprocal_basis = np.asarray(reciprocal_basis, dtype=float)
    if reciprocal_basis.shape != (2, 2) or not np.all(np.isfinite(reciprocal_basis)):
        return False
    if vertices.ndim != 2 or vertices.shape[1] != 2 or not np.all(np.isfinite(vertices)):
        return False
    if len(vertices) < 3 or len({tuple(row) for row in vertices}) != len(vertices):
        return False
    if np.allclose(vertices[0], vertices[-1], atol=tolerance, rtol=0.0):
        return False
    if _signed_area(vertices) <= tolerance:
        return False
    scale = max(1.0, float(np.max(np.linalg.norm(vertices, axis=1))))
    crosses = []
    for index in range(len(vertices)):
        previous = vertices[index - 1]
        current = vertices[index]
        following = vertices[(index + 1) % len(vertices)]
        crosses.append(_cross2d(current - previous, following - current))
    if any(value <= 100 * tolerance * scale * scale for value in crosses):
        return False
    # For a CCW polygon the origin must satisfy every edge half-plane.
    for start, end in zip(vertices, np.roll(vertices, -1, axis=0)):
        if _cross2d(end - start, -start) < -100 * tolerance * scale:
            return False
    target_area = abs(float(np.linalg.det(reciprocal_basis)))
    if abs(abs(_signed_area(vertices)) - target_area) > 1e-6 * max(1.0, target_area):
        return False
    for vector in _reciprocal_vectors(reciprocal_basis, 12):
        bound = 0.5 * float(np.dot(vector, vector))
        if np.max(vertices @ vector - bound) > 100 * tolerance:
            return False
    return True


@dataclass(frozen=True, slots=True, init=False)
class BrillouinZone2D:
    """Origin-centered Euclidean Wigner-Seitz cell of a reciprocal lattice.

    ``vertices`` is an open, counter-clockwise polygon.  The first vertex is
    the rightmost vertex, with the lowest y coordinate breaking ties.  The
    cell is reconstructed by reciprocal-lattice half-plane clipping, never by
    transforming an old named-lattice polygon.
    """

    _vertices: tuple[tuple[float, float], ...]
    reciprocal_basis: tuple[tuple[float, float], tuple[float, float]]
    shell: int
    tolerance: float

    def __init__(self, vertices, reciprocal_basis, shell: int, tolerance: float):
        values = np.asarray(vertices, dtype=float)
        if not _polygon_valid(values, np.asarray(reciprocal_basis, dtype=float), tolerance):
            raise ValueError("invalid first Brillouin-zone polygon")
        object.__setattr__(self, "_vertices", tuple(tuple(float(v) for v in row) for row in values))
        object.__setattr__(self, "reciprocal_basis", tuple(tuple(float(v) for v in row) for row in np.asarray(reciprocal_basis, dtype=float)))
        object.__setattr__(self, "shell", int(shell))
        object.__setattr__(self, "tolerance", float(tolerance))

    @property
    def vertices(self) -> np.ndarray:
        """Return a defensive copy of the open canonical vertex list."""

        return np.asarray(self._vertices, dtype=float)

    @property
    def area(self) -> float:
        """Return the positive polygon area."""

        return abs(_signed_area(self.vertices))

    @property
    def reciprocal_cell_area(self) -> float:
        """Return the area of the reciprocal primitive cell."""

        return abs(float(np.linalg.det(np.asarray(self.reciprocal_basis, dtype=float))))

    def metadata(self) -> dict[str, object]:
        """Return deterministic JSON-safe BZ metadata."""

        return {
            "type": "BrillouinZone2D",
            "vertices": self.vertices.tolist(),
            "reciprocal_basis": [list(row) for row in self.reciprocal_basis],
            "shell": self.shell,
            "tolerance": self.tolerance,
            "area": self.area,
            "reciprocal_cell_area": self.reciprocal_cell_area,
            "closure": "open",
            "winding": "counter_clockwise",
        }


def first_brillouin_zone(
    lattice: BravaisLattice2D,
    *,
    tolerance: float = 1e-10,
    max_shell: int = 12,
) -> BrillouinZone2D:
    """Construct and validate a generic 2-D reciprocal Wigner-Seitz cell.

    Neighbor shells are increased until both area and polygon vertex count are
    stable and the reciprocal primitive-cell area is recovered.  Failure to
    stabilize before ``max_shell`` raises ``RuntimeError`` rather than
    returning an under-clipped polygon.
    """

    if not isinstance(lattice, BravaisLattice2D):
        raise TypeError("lattice must be a BravaisLattice2D")
    if tolerance <= 0 or not np.isfinite(tolerance):
        raise ValueError("tolerance must be positive and finite")
    reciprocal = lattice.reciprocal_basis
    scale = max(1.0, float(np.max(np.linalg.norm(reciprocal, axis=0))))
    radius = 16.0 * scale
    initial = np.array([[-radius, -radius], [radius, -radius], [radius, radius], [-radius, radius]], dtype=float)
    target_area = abs(float(np.linalg.det(reciprocal)))
    previous_area = None
    previous_count = None
    accepted = None
    for shell in range(1, int(max_shell) + 1):
        polygon = initial.copy()
        for vector in _reciprocal_vectors(reciprocal, shell):
            polygon = _clip_half_plane(polygon, vector, 0.5 * float(np.dot(vector, vector)), tolerance)
            if len(polygon) < 3:
                break
        if len(polygon) < 3:
            raise RuntimeError(f"reciprocal clipping failed at shell {shell}")
        canonical = _canonicalize(polygon, tolerance)
        area = abs(_signed_area(canonical))
        area_error = abs(area - target_area) / max(target_area, np.finfo(float).eps)
        stable = previous_area is not None and abs(area - previous_area) <= tolerance * max(1.0, target_area)
        if area_error <= 100 * tolerance and stable and len(canonical) == previous_count:
            accepted = (canonical, shell)
            break
        previous_area = area
        previous_count = len(canonical)
    if accepted is None:
        raise RuntimeError("reciprocal neighbor shells did not stabilize a valid first Brillouin zone")
    vertices, shell = accepted
    if abs(abs(_signed_area(vertices)) - target_area) > 100 * tolerance * max(1.0, target_area):
        raise RuntimeError("first Brillouin-zone area does not match reciprocal primitive-cell area")
    return BrillouinZone2D(vertices, reciprocal, shell, tolerance)


def tracked_landmark(
    lattice: BravaisLattice2D,
    *,
    reference_cartesian=(2.0 / 3.0, 0.0),
    label: str = "tracked_K1",
    tolerance: float = 1e-10,
) -> dict[str, object]:
    """Select a deterministic current-BZ vertex tracked from a reference point.

    The predictor is ``F^{-T} @ reference_cartesian``. The current
    Wigner-Seitz vertices are searched by Euclidean distance, with ties broken
    by their canonical vertex index.
    """

    if not isinstance(lattice, BravaisLattice2D):
        raise TypeError("lattice must be a BravaisLattice2D")
    reference = np.asarray(reference_cartesian, dtype=float)
    if reference.shape != (2,) or not np.all(np.isfinite(reference)):
        raise ValueError("reference_cartesian must be a finite 2D point")
    bz = first_brillouin_zone(lattice, tolerance=tolerance)
    predictor = np.linalg.inv(lattice.deformation_matrix).T @ reference
    vertices = bz.vertices
    distances = np.linalg.norm(vertices - predictor, axis=1)
    selected_index = min(
        range(len(vertices)),
        key=lambda index: (float(distances[index]), int(index)),
    )
    selected = vertices[selected_index]
    return {
        "landmark_kind": "legacy_K" if lattice.is_identity else str(label),
        "display_label": "K" if lattice.is_identity else str(label),
        "reference_cartesian": reference.copy(),
        "predictor_cartesian": predictor,
        "cartesian": reference.copy() if lattice.is_identity else selected.copy(),
        "selected_vertex": selected.copy(),
        "selected_vertex_index": int(selected_index),
        "vertex_distances": distances,
        "selection_strategy": "nearest_current_bz_vertex_to_F_inverse_transpose_reference_plus_x_K",
        "tie_break": "lowest canonical vertex index after distance",
        "tie_tolerance": float(tolerance),
        "bz": bz,
    }
