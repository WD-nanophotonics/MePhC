"""Canonical centered local-Berry execution facade.

The historical :mod:`mephc.berry` calculator remains available for explicit
legacy callers.  Band-facing production construction uses this subclass,
whose default request point is the geometric center of the plaquette.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .berry import BerryCurvatureCalculator
from .berry_units import OMEGA_PHYS_OVER_A2, Q_COORDINATE_SPACE, curvature_unit_provenance
from .plaquette_semantics import (
    CENTERED_CCW,
    LEGACY_FORWARD_CCW,
    LocalPlaquetteGeometry,
    build_local_plaquette,
)


CANONICAL_SIGN_CONVENTION = "OMEGA = -WILSON_PHASE / SIGNED_AREA / (2*pi)^2"
LEGACY_GEOMETRY_CANONICAL_SIGN_NOTE = "LEGACY_FORWARD_CCW geometry with canonical sign; historical numerical reproduction is mephc.berry.BerryCurvatureCalculator"

@dataclass(frozen=True)
class CanonicalBerryCurvatureResult:
    k_points: np.ndarray
    values: np.ndarray
    band_index: int | None
    step: float
    convention: str
    geometries: tuple[LocalPlaquetteGeometry, ...]
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "k_points": self.k_points.tolist(),
            "values": self.values.tolist(),
            "band_index": self.band_index,
            "step": self.step,
            "convention": self.convention,
            "geometries": [geometry.to_dict() for geometry in self.geometries],
            "curvature_unit_space": self.provenance.get("curvature_unit_space"),
            "provenance": dict(self.provenance),
        }



@dataclass(frozen=True)
class CanonicalBerryPlaquetteResult:
    values: Any
    geometry: LocalPlaquetteGeometry
    band_index: int | None
    resolution: int
    field_representation: str
    overlap_formulation: str
    qualification: str = "UNQUALIFIED_NUMERICAL_SAMPLE"
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "values": self.values.tolist() if hasattr(self.values, "tolist") else self.values,
            "geometry": self.geometry.to_dict(),
            "band_index": self.band_index,
            "resolution": self.resolution,
            "field_representation": self.field_representation,
            "overlap_formulation": self.overlap_formulation,
                "sign_convention": CANONICAL_SIGN_CONVENTION,
            "qualification": self.qualification,
            "curvature_unit_space": self.provenance.get("curvature_unit_space"),
            "provenance": dict(self.provenance),
        }


class CanonicalBerryCurvatureCalculator(BerryCurvatureCalculator):
    """Berry calculator with centered CCW semantics as the default."""

    def calculate_result(
        self,
        k_point,
        step: float,
        band_index: int | None = None,
        *,
        convention: str = CENTERED_CCW,
        dx=None,
        dy=None,
    ) -> CanonicalBerryPlaquetteResult:
        if band_index is not None and (band_index < 0 or band_index >= self.num_bands):
            raise ValueError(f"band_index must be between 0 and {self.num_bands - 1}")
        dx_value = step if dx is None else dx
        if dy is None:
            dy_value = step if np.isscalar(dx_value) else (0.0, step)
        else:
            dy_value = dy
        geometry = build_local_plaquette(
            k_point, dx_value, dy_value, convention=convention
        )
        fields = []
        for point in geometry.ordered_vertices:
            e_fields, h_fields = self.calculate_fields(point)
            if self.overlap_formulation == "mpb_h":
                fields.append((None, self.normalize_h_fields(h_fields), None))
            else:
                e_fields, h_fields = self.normalize_fields(e_fields, h_fields)
                fields.append((e_fields, h_fields, self.eps.copy()))

        def compute_one_band(index: int) -> tuple[float, float]:
            links = []
            for edge in range(4):
                e1, h1, eps1 = fields[edge]
                e2, h2, _ = fields[(edge + 1) % 4]
                if self.overlap_formulation == "mpb_h":
                    links.append(self._h_link_overlap(h1[index:index + 1], h2[index:index + 1]))
                else:
                    links.append(self.link_overlap(
                        e1[index:index + 1], h1[index:index + 1],
                        e2[index:index + 1], h2[index:index + 1], eps=eps1,
                    ))
            phase = float(np.real(np.asarray(np.angle(np.prod(links))).reshape(-1)[0]))
            return float(-phase / geometry.signed_area / (2.0 * np.pi) ** 2), phase

        indices = range(self.num_bands) if band_index is None else (band_index,)
        computed = [compute_one_band(index) for index in indices]
        if band_index is not None:
            values = computed[0][0]
            phases = computed[0][1]
        else:
            values = tuple(value for value, _ in computed)
            phases = [phase for _, phase in computed]
        provenance = {
            **curvature_unit_provenance(
                unit_space=OMEGA_PHYS_OVER_A2,
                requested_k_space=Q_COORDINATE_SPACE,
                plaquette_vertex_space=Q_COORDINATE_SPACE,
                signed_area_space=Q_COORDINATE_SPACE,
                conversion_applied=True,
                plaquette_convention=geometry.convention,
                orientation=geometry.orientation,
                representation="canonical_berry_plaquette",
                wilson_phase=phases,
            ),
            "requested_k": list(geometry.requested_k),
            "geometric_center": list(geometry.geometric_center),
            "convention": geometry.convention,
            "ordered_vertices": [list(point) for point in geometry.ordered_vertices],
            "dx": list(geometry.dx),
            "dy": list(geometry.dy),
            "signed_area": geometry.signed_area,
            "orientation": geometry.orientation,
            "coordinate_system": "cartesian_reciprocal",
            "resolution": self.resolution,
            "field_representation": "periodic_e_h_bloch_envelope" if self.overlap_formulation == "energy_eh" else "periodic_h_bloch_envelope",
            "overlap_formulation": self.overlap_formulation,
                "sign_convention": CANONICAL_SIGN_CONVENTION,
            "legacy_geometry_only": geometry.convention == LEGACY_FORWARD_CCW,
              "rank": 1,
              "band_index": band_index,
              "wilson_phase": phases,
              "curvature": values,
              "reason_withheld": "numerical sample is not a scientific qualification certificate",
            "status": "UNQUALIFIED_NUMERICAL_SAMPLE",
            "qualification": "UNQUALIFIED_NUMERICAL_SAMPLE",
        }
        return CanonicalBerryPlaquetteResult(
            values=values,
            geometry=geometry,
            band_index=band_index,
            resolution=self.resolution,
            field_representation=provenance["field_representation"],
            overlap_formulation=self.overlap_formulation,
            provenance=provenance,
        )

    def calculate(self, k_point, step: float, band_index: int | None = None, *, convention: str = CENTERED_CCW, dx=None, dy=None):
        return self.calculate_result(k_point, step, band_index, convention=convention, dx=dx, dy=dy).values

    def calculate_legacy_result(self, k_point, step: float, band_index: int | None = None) -> CanonicalBerryPlaquetteResult:
        """Use legacy forward geometry with the canonical -phase/signed-area sign.

        Historical numerical reproduction remains available only through
        mephc.berry.BerryCurvatureCalculator.
        """
        return self.calculate_result(k_point, step, band_index, convention=LEGACY_FORWARD_CCW)

    def calculate_legacy(self, k_point, step: float, band_index: int | None = None):
        return self.calculate_legacy_result(k_point, step, band_index).values

    def calculate_grid(self, k_points: Iterable[Any], step: float, band_index: int | None = None, *, convention: str = CENTERED_CCW, dx=None, dy=None) -> CanonicalBerryCurvatureResult:
        points = np.asarray(list(k_points), dtype=float)
        results = [self.calculate_result(point, step, band_index, convention=convention, dx=dx, dy=dy) for point in points]
        return CanonicalBerryCurvatureResult(
            k_points=points,
            values=np.asarray([result.values for result in results], dtype=float),
            band_index=band_index,
            step=float(step),
            convention=convention,
            geometries=tuple(result.geometry for result in results),
            provenance={
                **curvature_unit_provenance(
                    unit_space=OMEGA_PHYS_OVER_A2,
                    requested_k_space=Q_COORDINATE_SPACE,
                    plaquette_vertex_space=Q_COORDINATE_SPACE,
                    signed_area_space=Q_COORDINATE_SPACE,
                    conversion_applied=True,
                    plaquette_convention=convention,
                    representation="canonical_berry_grid",
                ),
                "coordinate_system": "cartesian_reciprocal",
                "convention": convention,
                "resolution": self.resolution,
                "field_representation": results[0].field_representation if results else None,
                "overlap_formulation": self.overlap_formulation,
                "sign_convention": CANONICAL_SIGN_CONVENTION,
            },
        )


__all__ = [
    "CanonicalBerryCurvatureCalculator",
    "CANONICAL_SIGN_CONVENTION",
    "LEGACY_GEOMETRY_CANONICAL_SIGN_NOTE",
    "CanonicalBerryCurvatureResult",
    "CanonicalBerryPlaquetteResult",
]
