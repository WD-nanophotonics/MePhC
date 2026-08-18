from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import meep as mp
from meep import mpb
import numpy as np


@dataclass
class BerryCurvatureResult:
    """Batch Berry-curvature values at Cartesian reciprocal k-points."""

    k_points: np.ndarray
    values: np.ndarray
    band_index: int | None
    step: float


class BerryCurvatureCalculator:
    """Plaquette Berry curvature calculator for 2D MPB fields.

    Public k-points are Cartesian reciprocal coordinates. They are converted to
    MPB reciprocal-lattice coordinates before constructing the ModeSolver.
    """

    def __init__(
        self,
        geometry,
        geometry_lattice,
        resolution: int,
        num_bands: int,
        polarization=mp.TE,
        run_band_func=mpb.fix_efield_phase,
        default_material=mp.air,
        verbose: bool = False,
        overlap_tol: float = 1e-14,
    ):
        """Configure an Abelian, single-band plaquette calculation.

        ``geometry`` and ``geometry_lattice`` are Meep objects used by MPB.
        ``polarization`` is the MPB parity selector. ``run_band_func`` is an
        optional phase callback; ``None`` disables it. ``overlap_tol`` is the
        smallest accepted field norm or link magnitude.
        """
        self.geometry = geometry
        self.geometry_lattice = geometry_lattice
        self.resolution = int(resolution)
        self.num_bands = int(num_bands)
        self.polarization = polarization
        self.run_band_func = run_band_func
        self.default_material = default_material
        self.verbose = verbose
        self.overlap_tol = overlap_tol
        self.eps = None

    def cartesian_to_reciprocal(self, k_point) -> mp.Vector3:
        point = np.asarray(k_point, dtype=float)
        if point.shape[0] < 2:
            raise ValueError("k_point must contain at least x and y coordinates.")
        z = float(point[2]) if point.shape[0] > 2 else 0.0
        return mp.cartesian_to_reciprocal(mp.Vector3(float(point[0]), float(point[1]), z), self.geometry_lattice)

    def build_solver(self, reciprocal_k_point) -> mpb.ModeSolver:
        return mpb.ModeSolver(
            geometry=self.geometry,
            geometry_lattice=self.geometry_lattice,
            k_points=[reciprocal_k_point],
            resolution=self.resolution,
            num_bands=self.num_bands,
            default_material=self.default_material,
            verbose=self.verbose,
        )

    def _run_solver(self, ms: mpb.ModeSolver) -> None:
        if self.run_band_func is None:
            ms.run_parity(self.polarization, False)
        else:
            ms.run_parity(self.polarization, False, self.run_band_func)

    def _spatial_shape(self) -> tuple[int, int]:
        size = getattr(self.geometry_lattice, "size", None)
        if size is None or not hasattr(size, "x") or not hasattr(size, "y"):
            raise ValueError("geometry_lattice must expose a 2D size for MPB field validation.")
        lattice_size = np.asarray([float(size.x), float(size.y)], dtype=float)
        if not np.all(np.isfinite(lattice_size)) or np.any(lattice_size <= 0.0):
            raise ValueError(f"geometry_lattice has invalid 2D size {tuple(lattice_size)}.")
        scaled = lattice_size * self.resolution
        rounded = np.rint(scaled).astype(int)
        if not np.allclose(scaled, rounded, rtol=0.0, atol=1e-12) or np.any(rounded < 1):
            raise ValueError(
                f"geometry_lattice size {tuple(lattice_size)} and resolution {self.resolution} "
                "do not define integral positive spatial dimensions."
            )
        return int(rounded[0]), int(rounded[1])

    @staticmethod
    def _require_finite(array, kind):
        try:
            finite = np.all(np.isfinite(array))
        except TypeError as error:
            raise ValueError(f"{kind} field contains values that are not finite numeric data.") from error
        if not finite:
            raise ValueError(f"{kind} field contains non-finite values.")

    def _shape_error(self, kind, array) -> ValueError:
        return ValueError(
            f"Cannot reshape MPB {kind} field with received shape {array.shape}; "
            f"expected spatial shape {self._spatial_shape()} for geometry_lattice size "
            f"{self.geometry_lattice.size} at resolution {self.resolution}."
        )

    def _reshape_vector_field(self, field) -> np.ndarray:
        array = np.asarray(field)
        nx, ny = self._spatial_shape()
        expected_count = nx * ny * 3
        result = None
        if array.ndim == 1 and array.size == expected_count:
            result = array.reshape(nx, ny, 3)
        elif array.ndim == 2 and array.shape == (nx * ny, 3):
            result = array.reshape(nx, ny, 3)
        elif array.ndim == 4 and array.shape[2:] == (1, 3) and array.shape[:2] == (nx, ny):
            result = array[:, :, 0, :]
        elif array.ndim == 3 and array.shape == (nx, ny, 3):
            result = array
        if result is None:
            raise self._shape_error("vector", array)
        self._require_finite(result, "vector")
        return result

    def _reshape_epsilon(self, epsilon) -> np.ndarray:
        array = np.asarray(epsilon)
        nx, ny = self._spatial_shape()
        expected_count = nx * ny
        result = None
        if array.ndim == 1 and array.size == expected_count:
            result = array.reshape(nx, ny)
        elif array.ndim == 3 and array.shape[2:] == (1,) and array.shape[:2] == (nx, ny):
            result = array[:, :, 0]
        elif array.ndim == 2 and array.shape == (nx, ny):
            result = array
        if result is None:
            raise self._shape_error("epsilon", array)
        self._require_finite(result, "epsilon")
        return result

    def _validate_field_shapes(self, e_fields, h_fields, eps, operation):
        e_fields = np.asarray(e_fields)
        h_fields = np.asarray(h_fields)
        expected = self._spatial_shape()
        if e_fields.ndim != 4 or e_fields.shape[3] != 3:
            raise ValueError(f"{operation} requires E fields with shape (bands, nx, ny, 3); received {e_fields.shape}.")
        if h_fields.ndim != 4 or h_fields.shape[3] != 3:
            raise ValueError(f"{operation} requires H fields with shape (bands, nx, ny, 3); received {h_fields.shape}.")
        if e_fields.shape != h_fields.shape:
            raise ValueError(f"{operation} requires matching E/H shapes; received {e_fields.shape} and {h_fields.shape}.")
        if e_fields.shape[1:3] != expected:
            raise ValueError(f"{operation} received E/H spatial shape {e_fields.shape[1:3]}; expected spatial shape {expected}.")
        eps = self._reshape_epsilon(eps)
        if eps.shape != expected:
            raise ValueError(f"{operation} received epsilon spatial shape {eps.shape}; expected spatial shape {expected}.")
        self._require_finite(e_fields, "E")
        self._require_finite(h_fields, "H")
        return e_fields, h_fields, eps

    def calculate_fields(self, k_point):
        """Return E and H fields for all bands at one Cartesian k-point."""
        reciprocal_k = self.cartesian_to_reciprocal(k_point)
        ms = self.build_solver(reciprocal_k)
        self._run_solver(ms)

        e_fields = []
        h_fields = []
        for band in range(1, self.num_bands + 1):
            e_fields.append(self._reshape_vector_field(ms.get_efield(band, bloch_phase=False)))
            h_fields.append(self._reshape_vector_field(ms.get_hfield(band, bloch_phase=False)))

        self.eps = self._reshape_epsilon(ms.get_epsilon())
        return np.asarray(e_fields), np.asarray(h_fields)

    def normalize_fields(self, e_fields, h_fields, eps=None):
        """Energy-normalize every band's electric and magnetic fields."""
        if eps is None:
            if self.eps is None:
                raise RuntimeError("epsilon is unavailable; call calculate_fields first or pass eps explicitly.")
            eps = self.eps

        e_fields, h_fields, eps = self._validate_field_shapes(
            e_fields, h_fields, eps, "field normalization"
        )
        eps_weight = eps[None, :, :, None]
        energy = (
            np.sum(eps_weight * np.conj(e_fields) * e_fields, axis=(1, 2, 3))
            + np.sum(np.conj(h_fields) * h_fields, axis=(1, 2, 3))
        )
        norm = np.sqrt(np.real(energy))
        if np.any(norm <= self.overlap_tol):
            raise FloatingPointError("Encountered a near-zero field norm during Berry curvature normalization.")
        return e_fields / norm[:, None, None, None], h_fields / norm[:, None, None, None]

    def link_overlap(self, e1, h1, e2, h2, eps=None):
        """Return unit-magnitude links between neighboring k-point fields."""
        if eps is None:
            if self.eps is None:
                raise RuntimeError("epsilon is unavailable; call calculate_fields first or pass eps explicitly.")
            eps = self.eps

        e1, h1, eps = self._validate_field_shapes(e1, h1, eps, "link overlap")
        e2, h2, _ = self._validate_field_shapes(e2, h2, eps, "link overlap")
        eps_weight = eps[None, :, :, None]
        overlap = (
            np.sum(eps_weight * np.conj(e1) * e2, axis=(1, 2, 3))
            + np.sum(np.conj(h1) * h2, axis=(1, 2, 3))
        )
        magnitude = np.abs(overlap)
        if np.any(magnitude <= self.overlap_tol):
            raise FloatingPointError("Encountered a near-zero link overlap while computing Berry curvature.")
        return overlap / magnitude

    def calculate(self, k_point, step: float, band_index: int | None = None):
        """Calculate curvature on a counterclockwise square plaquette.

        ``k_point`` is the lower-left corner in Cartesian reciprocal
        coordinates. ``step`` is the side length in the same coordinates.
        ``band_index`` is Python 0-based; ``None`` returns all configured bands.
        """
        if band_index is not None and (band_index < 0 or band_index >= self.num_bands):
            raise ValueError(f"band_index must be between 0 and {self.num_bands - 1}")

        k = np.asarray(k_point, dtype=float)
        if k.shape[0] < 2:
            raise ValueError("k_point must contain at least x and y coordinates.")
        k = k[:2]
        step = float(step)

        plaquette = [
            k,
            k + np.array([step, 0.0]),
            k + np.array([step, step]),
            k + np.array([0.0, step]),
        ]

        fields = []
        for point in plaquette:
            e_fields, h_fields = self.calculate_fields(point)
            e_fields, h_fields = self.normalize_fields(e_fields, h_fields)
            fields.append((e_fields, h_fields, self.eps.copy()))

        def compute_one_band(idx: int) -> float:
            links = []
            for i in range(4):
                e1, h1, eps1 = fields[i]
                e2, h2, _ = fields[(i + 1) % 4]
                links.append(
                    self.link_overlap(
                        e1[idx : idx + 1],
                        h1[idx : idx + 1],
                        e2[idx : idx + 1],
                        h2[idx : idx + 1],
                        eps=eps1,
                    )
                )
            flux = np.angle(links[0] * links[1] * links[2] * links[3])
            curvature = flux / (step * step)
            curvature /= (2 * np.pi) ** 2
            return float(np.real(curvature[0]))

        if band_index is not None:
            return compute_one_band(band_index)
        return tuple(compute_one_band(idx) for idx in range(self.num_bands))

    def calculate_grid(self, k_points: Iterable[Any], step: float, band_index: int | None = None) -> BerryCurvatureResult:
        """Evaluate :meth:`calculate` for an arbitrary k-point sequence."""
        points = np.asarray(list(k_points), dtype=float)
        values = [self.calculate(point, step=step, band_index=band_index) for point in points]
        return BerryCurvatureResult(
            k_points=points,
            values=np.asarray(values, dtype=float),
            band_index=band_index,
            step=float(step),
        )
