from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from shapely.geometry import Point, Polygon

from .bravais import BravaisLattice2D
from .bz import first_brillouin_zone


@dataclass(frozen=True)
class HighSymmetryPath:
    """Piecewise-linear k-space path used for band-structure calculations.

    ``points`` are Cartesian reciprocal coordinates. ``labels`` are shown at
    the matching path vertices.
    """

    points: tuple[tuple[float, float], ...]
    labels: tuple[str, ...]

    def __post_init__(self):
        if len(self.points) != len(self.labels):
            raise ValueError("points and labels must have the same length.")
        if len(self.points) < 2:
            raise ValueError("A high-symmetry path needs at least two points.")

    def interpolate(self, n_per_segment: int):
        """Sample each segment and return points plus plotting positions.

        The result contains ``segments * n_per_segment + 1`` k-points.
        """
        if n_per_segment < 1:
            raise ValueError("n_per_segment must be >= 1.")

        points = [np.asarray(point, dtype=float) for point in self.points]
        path = []
        for start, end in zip(points[:-1], points[1:]):
            for i in range(n_per_segment):
                t = i / n_per_segment
                path.append(start + t * (end - start))
        path.append(points[-1].copy())
        path = np.asarray(path, dtype=float)

        diffs = np.diff(path, axis=0)
        segment_lengths = np.linalg.norm(diffs, axis=1)
        distances = np.concatenate([[0.0], np.cumsum(segment_lengths)])
        tick_indices = np.arange(len(points)) * n_per_segment
        tick_positions = distances[tick_indices]
        return path, distances, tick_indices, tick_positions

    def offset_high_symmetry_point(self, k_point, step: float, atol: float = 1e-12):
        """Move an exact path vertex away from a Berry plaquette singularity."""
        k = np.asarray(k_point, dtype=float)
        for point in self.points[:-1]:
            if np.allclose(k, np.asarray(point, dtype=float), atol=atol, rtol=0.0):
                return k + np.array([0.5 * step, 0.5 * step])
        return k


def triangular_gkm_path() -> HighSymmetryPath:
    """Return the triangular-lattice Gamma-K-M-Gamma band path."""
    return HighSymmetryPath(
        points=((0.0, 0.0), (2.0 / 3.0, 0.0), (0.5, np.sqrt(3.0) / 6.0), (0.0, 0.0)),
        labels=("Gamma", "K", "M", "Gamma"),
    )


def generic_bz_path(lattice_model: BravaisLattice2D) -> HighSymmetryPath:
    """Return a conservative Gamma-to-BZ-vertices path for a current lattice.

    The labels deliberately use ``BZ1``, ``BZ2`` rather than claiming that
    tracked reference vertices remain current K/M high-symmetry points.
    """
    polygon = np.asarray(first_brillouin_zone(lattice_model).vertices, dtype=float)
    points = [(0.0, 0.0)] + [tuple(map(float, point)) for point in polygon] + [(0.0, 0.0)]
    labels = ("Gamma",) + tuple(f"BZ{i}" for i in range(1, len(polygon) + 1)) + ("Gamma",)
    return HighSymmetryPath(tuple(points), labels)


def square_gxm_path() -> HighSymmetryPath:
    """Return the square-lattice Gamma-X-M-Gamma band path."""
    return HighSymmetryPath(
        points=((0.0, 0.0), (0.5, 0.0), (0.5, 0.5), (0.0, 0.0)),
        labels=("Gamma", "X", "M", "Gamma"),
    )


def polygon_around_position(n: int, position=(0.0, 0.0), radius: float = 1.0, rotation_degrees: float = 0.0):
    angles = np.linspace(0, 2 * np.pi, n, endpoint=False) + np.radians(rotation_degrees)
    x = position[0] + radius * np.cos(angles)
    y = position[1] + radius * np.sin(angles)
    return [(float(xi), float(yi)) for xi, yi in zip(x, y)]


def _contains(point, polygon, tolerance=1e-5) -> bool:
    return Polygon(polygon).buffer(tolerance).contains(Point(point))


def _draw_points(points, outlines=None, *, show=True, save_path=None, figsize=(5, 5), dpi=120, s=12, color="black"):
    points = np.asarray(points, dtype=float)
    fig, ax = plt.subplots(figsize=figsize, dpi=dpi)
    if len(points):
        ax.scatter(points[:, 0], points[:, 1], s=s, color=color)
    for outline in outlines or []:
        poly = np.asarray(outline, dtype=float)
        if len(poly):
            closed = np.vstack([poly, poly[0]])
            ax.plot(closed[:, 0], closed[:, 1], color="0.3", linewidth=1.0)
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel("kx")
    ax.set_ylabel("ky")
    ax.grid(True, linestyle=":", linewidth=0.5)
    fig.tight_layout()
    if save_path is not None:
        save_path = Path(save_path)
        save_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(save_path, bbox_inches="tight")
    if show:
        plt.show()
    else:
        plt.close(fig)
    return fig, ax


@dataclass(frozen=True)
class SquareKSpace:
    """Regular Cartesian reciprocal-space grids for a square lattice.

    ``N`` is the number of samples along each axis, including both domain
    endpoints.
    """

    N: int
    lattice_model: BravaisLattice2D | None = None

    def __post_init__(self):
        if self.N < 1:
            raise ValueError("N must be >= 1.")

    def full_grid(self, extent: float = 0.5) -> list[tuple[float, float]]:
        """Return an ``N x N`` grid over ``[-extent, extent]`` on both axes."""
        values = np.linspace(-float(extent), float(extent), int(self.N))
        return [(float(kx), float(ky)) for kx in values for ky in values]

    def first_bz(self) -> list[tuple[float, float]]:
        """Return the legacy square grid or the current validated BZ grid.

        The identity square lattice keeps the historical [-0.5, 0.5]^2
        ordering. A deformed model uses its reconstructed Wigner-Seitz cell.
        """
        if self.lattice_model is not None and not self.lattice_model.is_identity:
            return self.current_bz()
        return self.full_grid(extent=0.5)

    def current_bz(self, lattice_model: BravaisLattice2D | None = None) -> list[tuple[float, float]]:
        """Sample the current Wigner-Seitz BZ in Cartesian reciprocal space.

        N controls the spacing relative to the shortest reciprocal basis
        vector. Points are filtered by the actual polygon and ordered by
        increasing kx then ky; a bounding rectangle is never claimed to be
        the BZ.
        """
        model = lattice_model or self.lattice_model
        if model is None:
            raise ValueError("current_bz requires a BravaisLattice2D model")
        polygon = np.asarray(first_brillouin_zone(model).vertices, dtype=float)
        reciprocal = np.asarray(model.reciprocal_basis, dtype=float)
        spacing = min(float(np.linalg.norm(reciprocal[:, 0])), float(np.linalg.norm(reciprocal[:, 1]))) / float(self.N)
        if not np.isfinite(spacing) or spacing <= 0:
            raise ValueError("current BZ sampling spacing must be positive")
        lower = polygon.min(axis=0) - 0.5 * spacing
        upper = polygon.max(axis=0) + 0.5 * spacing
        x_values = np.arange(np.ceil(lower[0] / spacing), np.floor(upper[0] / spacing) + 1.0) * spacing
        y_values = np.arange(np.ceil(lower[1] / spacing), np.floor(upper[1] / spacing) + 1.0) * spacing
        polygon_shape = Polygon(polygon)
        tolerance = 1e-10 * max(1.0, float(np.max(np.linalg.norm(polygon, axis=1))))
        accepted = []
        for kx in x_values:
            for ky in y_values:
                if polygon_shape.buffer(tolerance).covers(Point(float(kx), float(ky))):
                    accepted.append((float(kx), float(ky)))
        if not accepted:
            raise ValueError("current BZ sampling produced no points; increase N")
        return accepted

    @property
    def first_bz_poly(self) -> list[tuple[float, float]]:
        """Return the canonical generic square first-BZ polygon."""
        model = self.lattice_model or BravaisLattice2D.square()
        return first_brillouin_zone(model).vertices.tolist()

    def c4_quadrant(self, extent: float = 1.0) -> list[tuple[float, float]]:
        """Return the ``N x N`` first-quadrant grid used for C4 reduction.

        This is the full ``0 <= kx, ky <= extent`` quadrant, not a triangular
        wedge below the diagonal.
        """
        values = np.linspace(0.0, float(extent), int(self.N))
        return [(float(kx), float(ky)) for kx in values for ky in values]

    def c4_expand(self, k_points, values, tolerance: float = 1e-10):
        """Expand points and values by proper C4 rotations.

        Values are copied without a sign change under 0, 90, 180, and 270
        degree rotations. Coincident axis/origin points are deduplicated using
        ``tolerance``. An ``N x N`` quadrant becomes a
        ``(2*N - 1) x (2*N - 1)`` full square grid.
        """
        points = np.asarray(k_points, dtype=float)
        values = np.asarray(values)
        if points.ndim != 2 or points.shape[1] != 2:
            raise ValueError("k_points must have shape (N, 2).")
        if values.shape[0] != points.shape[0]:
            raise ValueError("values must have the same first dimension as k_points.")
        rotations = (
            np.array([[1.0, 0.0], [0.0, 1.0]]),
            np.array([[0.0, -1.0], [1.0, 0.0]]),
            np.array([[-1.0, 0.0], [0.0, -1.0]]),
            np.array([[0.0, 1.0], [-1.0, 0.0]]),
        )
        expanded_points = []
        expanded_values = []
        seen = set()
        scale = 1.0 / float(tolerance)
        for rotation in rotations:
            rotated = points @ rotation.T
            for point, value in zip(rotated, values):
                key = tuple(np.round(point * scale).astype(int).tolist())
                if key in seen:
                    continue
                seen.add(key)
                expanded_points.append((float(point[0]), float(point[1])))
                expanded_values.append(np.array(value, copy=True))
        return np.asarray(expanded_points, dtype=float), np.asarray(expanded_values, dtype=values.dtype)

    def draw(self, points=None, outlines=None, **kwargs):
        """Draw a k-space point set; default to :meth:`full_grid`."""
        return _draw_points(self.full_grid() if points is None else points, outlines=outlines, **kwargs)


@dataclass(frozen=True)
class TriangularKSpace:
    """Triangular reciprocal grids and commonly used subdomains.

    ``N`` sets grid density through primitive sampling vectors scaled by
    ``1/N``. ``shrinking`` moves the HBZ boundary inward to avoid numerically
    delicate boundary points.
    """

    N: int
    shrinking: float = 0.01
    lattice_model: BravaisLattice2D | None = None

    def __post_init__(self):
        if self.N < 1:
            raise ValueError("N must be >= 1.")

    @property
    def second_bz_poly(self):
        if self.lattice_model is not None and not self.lattice_model.supports_legacy("hbz"):
            raise ValueError("second BZ is an identity triangular reference construction")
        return polygon_around_position(6, (0.0, 0.0), 2 * np.sqrt(3.0) / 3.0, rotation_degrees=30)

    @property
    def first_bz_poly(self):
        model = self.lattice_model or BravaisLattice2D.triangular()
        return first_brillouin_zone(model).vertices.tolist()

    @property
    def hbz_poly(self):
        if self.lattice_model is not None and not self.lattice_model.supports_legacy("hbz"):
            raise ValueError("HBZ is only defined for the identity triangular lattice")
        return polygon_around_position(3, (2.0 / 3.0, 0.0), 2.0 / 3.0, rotation_degrees=60)

    @property
    def minpoly_by_c3(self):
        if self.lattice_model is not None and not self.lattice_model.supports_legacy("c3"):
            raise ValueError("C3 mini-space is only defined for the identity triangular lattice")
        return [(0.0, 0.0), (0.5, np.sqrt(3.0) / 6.0), (2.0 / 3.0, 0.0), (0.5, -np.sqrt(3.0) / 6.0)]

    @property
    def shrunken_hbz_poly(self):
        if self.lattice_model is not None and not self.lattice_model.supports_legacy("hbz"):
            raise ValueError("shrunken HBZ is only defined for the identity triangular lattice")
        return polygon_around_position(3, (2.0 / 3.0, 0.0), 2.0 / 3.0 - self.shrinking, rotation_degrees=60)

    def full_grid(self, range_x=(-1.5, 1.5), range_y=(-1.5, 1.5)) -> list[tuple[float, float]]:
        """Return triangular-grid points inside the Cartesian x/y bounds."""
        if self.lattice_model is not None and not self.lattice_model.is_identity:
            # Sample the current reciprocal primitive basis.  The old
            # triangular Cartesian mesh is retained only for identity data.
            basis = self.lattice_model.reciprocal_basis
            scale = max(1, int(self.N))
            points = []
            for i in range(-3 * scale, 3 * scale + 1):
                for j in range(-3 * scale, 3 * scale + 1):
                    point = (i * basis[:, 0] + j * basis[:, 1]) / scale
                    if range_x[0] <= point[0] <= range_x[1] and range_y[0] <= point[1] <= range_y[1]:
                        points.append((float(point[0]), float(point[1])))
            return points
        step = 1 / self.N
        a1 = np.array([1.0, 0.0]) * step
        a2 = np.array([0.5, np.sqrt(3.0) / 2.0]) * step
        min_x, max_x = range_x
        min_y, max_y = range_y
        points = []
        for i in range(int(np.floor(min_x / step)), int(np.ceil(max_x / step))):
            for j in range(int(np.floor(min_y / step)), int(np.ceil(max_y / step))):
                point = i * a1 + j * a2
                if min_x <= point[0] <= max_x and min_y <= point[1] <= max_y:
                    points.append((float(point[0]), float(point[1])))
        return points

    def first_bz(self):
        """Return sampled points inside the first hexagonal Brillouin zone."""
        return [point for point in self.full_grid() if _contains(point, self.first_bz_poly)]

    def full_bz(self):
        """Return samples inside the current validated Wigner-Seitz BZ."""
        vertices = np.asarray(self.first_bz_poly, dtype=float)
        bounds = ((float(vertices[:, 0].min()), float(vertices[:, 0].max())),
                  (float(vertices[:, 1].min()), float(vertices[:, 1].max())))
        return [point for point in self.full_grid(bounds[0], bounds[1]) if _contains(point, vertices)]

    def second_bz(self):
        """Return sampled points inside the larger second-zone hexagon."""
        return [point for point in self.full_grid() if _contains(point, self.second_bz_poly)]

    def hbz(self):
        """Return points in the K-centered half-Brillouin-zone triangle."""
        return [point for point in self.full_grid() if _contains(point, self.hbz_poly)]

    def shrunken_hbz(self):
        """Return HBZ points after moving its boundary inward."""
        return [point for point in self.full_grid() if _contains(point, self.shrunken_hbz_poly)]

    def mini_space(self):
        """Return the C3-reduced K-centered domain used by MPBBC logic."""
        if self.lattice_model is not None and not self.lattice_model.supports_legacy("mini_space"):
            raise ValueError("C3 mini-space is not valid for a deformed triangular lattice")
        return [
            point
            for point in self.full_grid()
            if _contains(point, self.minpoly_by_c3) and _contains(point, self.shrunken_hbz_poly)
        ]

    def c3_expand(self, k_points, values, origin=(2.0 / 3.0, 0.0), tolerance: float = 1e-10):
        """Expand points and values by proper C3 rotations about ``origin``."""
        if self.lattice_model is not None and not self.lattice_model.supports_legacy("c3"):
            raise ValueError("C3 expansion is only valid for the identity triangular lattice")
        points = np.asarray(k_points, dtype=float)
        values = np.asarray(values)
        if points.ndim != 2 or points.shape[1] != 2:
            raise ValueError("k_points must have shape (N, 2).")
        if values.shape[0] != points.shape[0]:
            raise ValueError("values must have the same first dimension as k_points.")
        origin = np.asarray(origin, dtype=float)
        expanded_points = []
        expanded_values = []
        seen = set()
        scale = 1.0 / float(tolerance)
        for angle in (0.0, 2 * np.pi / 3, 4 * np.pi / 3):
            rotation = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
            rotated = (points - origin) @ rotation.T + origin
            for point, value in zip(rotated, values):
                key = tuple(np.round(point * scale).astype(int).tolist())
                if key in seen:
                    continue
                seen.add(key)
                expanded_points.append((float(point[0]), float(point[1])))
                expanded_values.append(np.array(value, copy=True))
        return np.asarray(expanded_points, dtype=float), np.asarray(expanded_values, dtype=values.dtype)

    def draw(self, points=None, outlines=None, **kwargs):
        """Draw points with first-BZ and HBZ outlines by default."""
        if outlines is None:
            outlines = [self.first_bz_poly, self.hbz_poly]
        return _draw_points(self.full_grid() if points is None else points, outlines=outlines, **kwargs)


# Compatibility wrappers for older examples/scripts.
def triangular_full_grid_points(N: int, range_x=(-1.5, 1.5), range_y=(-1.5, 1.5)) -> list[tuple[float, float]]:
    return TriangularKSpace(N).full_grid(range_x=range_x, range_y=range_y)


def square_full_zone_points(N: int, extent: float = 0.5) -> list[tuple[float, float]]:
    return SquareKSpace(N).full_grid(extent=extent)


def triangular_reduced_zone_points(N: int, shrinking: float = 0.01) -> list[tuple[float, float]]:
    return TriangularKSpace(N=N, shrinking=shrinking).mini_space()
