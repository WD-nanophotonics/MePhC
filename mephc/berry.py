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

    def _reshape_vector_field(self, field) -> np.ndarray:
        array = np.asarray(field)
        expected = self.resolution * self.resolution * 3
        if array.size == expected:
            return array.reshape(self.resolution, self.resolution, 3)
        if array.ndim == 4 and array.shape[-1] == 3 and array.shape[2] == 1:
            return array[:, :, 0, :]
        if array.ndim == 3 and array.shape[-1] == 3:
            return array
        raise ValueError(f"Cannot reshape MPB vector field with shape {array.shape} for resolution {self.resolution}.")

    def _reshape_epsilon(self, epsilon) -> np.ndarray:
        array = np.asarray(epsilon)
        expected = self.resolution * self.resolution
        if array.size == expected:
            return array.reshape(self.resolution, self.resolution)
        if array.ndim == 3 and array.shape[2] == 1:
            return array[:, :, 0]
        if array.ndim == 2:
            return array
        raise ValueError(f"Cannot reshape MPB epsilon with shape {array.shape} for resolution {self.resolution}.")

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

        eps = np.asarray(eps).reshape(1, self.resolution, self.resolution, 1)
        energy = (
            np.sum(eps * np.conj(e_fields) * e_fields, axis=(1, 2, 3))
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

        eps = np.asarray(eps).reshape(1, self.resolution, self.resolution, 1)
        overlap = (
            np.sum(eps * np.conj(e1) * e2, axis=(1, 2, 3))
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
