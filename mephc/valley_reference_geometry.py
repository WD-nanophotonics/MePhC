"""Solver-neutral geometry contract for the triangular reference family.

This module describes a deterministic one-hole triangular reference cell.  It
does not construct Meep/MPB objects and deliberately labels the intermediate
rounded-triangle family as a close analogue rather than claiming exact paper
geometry.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any

import numpy as np


TRIANGULAR_CELL_AREA = math.sqrt(3.0) / 2.0
REFERENCE_AIR_FILL_FRACTION = 0.107
REFERENCE_MATERIAL_VALUE = 2.65
REFERENCE_EFFECTIVE_PERMITTIVITY = REFERENCE_MATERIAL_VALUE
REFERENCE_MATERIAL_SOURCE_ROLE = "Dai II.1 Structural model effective-permittivity statement"


def _signed_area(vertices: np.ndarray) -> float:
    return 0.5 * float(np.sum(vertices[:, 0] * np.roll(vertices[:, 1], -1) - vertices[:, 1] * np.roll(vertices[:, 0], -1)))


def _positive_area(vertices: np.ndarray) -> float:
    return abs(_signed_area(vertices))


def _canonical_vertices(vertices: np.ndarray) -> tuple[tuple[float, float], ...]:
    values = np.asarray(vertices, dtype=float)
    if values.ndim != 2 or values.shape[1] != 2 or len(values) < 3:
        raise ValueError("vertices must have shape (N, 2), N >= 3")
    if not np.all(np.isfinite(values)) or _signed_area(values) <= 0.0:
        raise ValueError("vertices must be finite and counter-clockwise")
    return tuple(tuple(float(value) for value in point) for point in values)


def _triangle_radius_for_area(area: float) -> float:
    return math.sqrt(area / (3.0 * math.sqrt(3.0) / 4.0))


def _circle_radius_for_area(area: float) -> float:
    return math.sqrt(area / math.pi)


def _triangle_radial(theta: np.ndarray) -> np.ndarray:
    """Radial function of a unit-circumradius equilateral triangle."""
    apothem = 0.5
    normal0 = math.pi / 2.0 + math.pi / 3.0
    nearest = normal0 + (np.round((theta - normal0) / (2.0 * math.pi / 3.0)) * (2.0 * math.pi / 3.0))
    return apothem / np.cos(theta - nearest)


def _make_boundary(fr: float, target_area: float) -> np.ndarray:
    if fr == 0.0:
        radius = _triangle_radius_for_area(target_area)
        angles = math.pi / 2.0 + np.arange(3, dtype=float) * (2.0 * math.pi / 3.0)
        raw = radius * np.column_stack((np.cos(angles), np.sin(angles)))
        return raw * math.sqrt(target_area / _positive_area(raw))
    if fr == 0.5:
        radius = _circle_radius_for_area(target_area)
        angles = np.linspace(0.0, 2.0 * math.pi, 96, endpoint=False)
        raw = radius * np.column_stack((np.cos(angles), np.sin(angles)))
        return raw

    # The interpolation is an internal, deterministic close analogue.  It
    # preserves the endpoint shapes and is rescaled to the reference fill.
    count = 96
    angles = np.linspace(0.0, 2.0 * math.pi, count, endpoint=False)
    t = fr / 0.5
    radial = (1.0 - t) * _triangle_radial(angles) + t * _circle_radius_for_area(target_area)
    raw = np.column_stack((radial * np.cos(angles), radial * np.sin(angles)))
    return raw * math.sqrt(target_area / _positive_area(raw))


@dataclass(frozen=True, slots=True)
class TriangularReferenceGeometry:
    """Canonical normalized triangular reference-cell description."""

    fr: float
    vertices: tuple[tuple[float, float], ...]
    air_fill_fraction: float = REFERENCE_AIR_FILL_FRACTION
    lattice_constant: float = 1.0
    polarization: str = "TE"
    effective_permittivity: float = REFERENCE_EFFECTIVE_PERMITTIVITY
    reference_material_semantics: str = "RELATIVE_PERMITTIVITY"
    primitive_kind: str = "rounded_triangle_close_analogue"
    analytic_radius: float | None = None
    geometry_equivalence: str = "CLOSE_ANALOGUE"
    paper_parameter_equivalence: str = "UNRESOLVED"
    polygonization_version: str = "INTERNAL_CLOSE_ANALOGUE_RADIAL_MORPH_V1"
    boundary_construction_version: str = "INTERNAL_CLOSE_ANALOGUE_RADIAL_MORPH_V1"
    triangle_orientation_degrees: float = 90.0
    orientation_convention: str = "PUBLIC_CARTESIAN_QX_QY_CCW"
    orientation_source_status: str = "CONVENTION_MAPPED"
    reference_material_source_role: str = REFERENCE_MATERIAL_SOURCE_ROLE
    construction_status: str = "EXACT_INTERNAL_REFERENCE_CONTRACT"

    @property
    def cell_area(self) -> float:
        return TRIANGULAR_CELL_AREA * self.lattice_constant**2

    @property
    def polygonization_area(self) -> float:
        return _positive_area(np.asarray(self.vertices, dtype=float))

    @property
    def analytic_area(self) -> float | None:
        if self.primitive_kind == "circle" and self.analytic_radius is not None:
            return math.pi * self.analytic_radius ** 2
        if self.primitive_kind == "triangle" and self.analytic_radius is not None:
            return 3.0 * math.sqrt(3.0) * self.analytic_radius ** 2 / 4.0
        return None

    @property
    def air_area(self) -> float:
        return self.analytic_area if self.analytic_area is not None else self.polygonization_area

    @property
    def polygonization_area_error(self) -> float:
        return self.polygonization_area - self.air_area

    @property
    def fill_fraction_error(self) -> float:
        return self.air_area / self.cell_area - self.air_fill_fraction

    @property
    def shape_kind(self) -> str:
        if self.fr == 0.0:
            return "triangle"
        if self.fr == 0.5:
            return "circle"
        return "rounded_triangle"

    @property
    def mpb_epsilon_value(self) -> float | None:
        if self.reference_material_semantics == "REFRACTIVE_INDEX":
            return self.effective_permittivity ** 2
        if self.reference_material_semantics == "RELATIVE_PERMITTIVITY":
            return self.effective_permittivity
        return None

    @property
    def boundary_digest(self) -> str:
        payload = {
            "construction_version": self.boundary_construction_version,
            "vertices_float64": [list(point) for point in self.vertices],
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()

    @property
    def material_contract_status(self) -> str:
        return "REFERENCE_BOUND" if self.reference_material_semantics == "RELATIVE_PERMITTIVITY" and self.reference_material_source_role == REFERENCE_MATERIAL_SOURCE_ROLE else "NON_REFERENCE_ANALOGUE" if self.reference_material_semantics in {"REFRACTIVE_INDEX", "RELATIVE_PERMITTIVITY"} else "UNRESOLVED"

    @property
    def material_contract_digest(self) -> str:
        payload = {
            "value": self.effective_permittivity,
            "semantics": self.reference_material_semantics,
            "source_role": self.reference_material_source_role,
            "epsilon": self.mpb_epsilon_value,
            "status": self.material_contract_status,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()

    @property
    def live_reference_solve_ready(self) -> bool:
        return self.mpb_epsilon_value is not None and self.material_contract_status == "REFERENCE_BOUND" and self.paper_parameter_equivalence in {"BOUND", "PAPER_PARAMETER_BOUND"}

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "triangular_reference_geometry_v2",
            "fr": self.fr,
            "shape_kind": self.shape_kind,
            "vertices": [list(point) for point in self.vertices],
            "air_fill_fraction": self.air_fill_fraction,
            "cell_area": self.cell_area,
            "air_area": self.air_area,
            "polygonization_area": self.polygonization_area,
            "polygonization_area_error": self.polygonization_area_error,
            "analytic_area": self.analytic_area,
            "lattice_constant": self.lattice_constant,
            "polarization": self.polarization,
            "effective_permittivity": self.effective_permittivity,
            "reference_material_semantics": self.reference_material_semantics,
            "mpb_epsilon_value": self.mpb_epsilon_value,
            "material_contract_status": self.material_contract_status,
            "material_contract_digest": self.material_contract_digest,
            "reference_material_source_role": self.reference_material_source_role,
            "primitive_kind": self.primitive_kind,
            "analytic_radius": self.analytic_radius,
            "geometry_equivalence": self.geometry_equivalence,
            "paper_parameter_equivalence": self.paper_parameter_equivalence,
            "polygonization_version": self.polygonization_version,
            "boundary_construction_version": self.boundary_construction_version,
            "boundary_digest": self.boundary_digest,
            "triangle_orientation_degrees": self.triangle_orientation_degrees,
            "orientation_convention": self.orientation_convention,
            "orientation_source_status": self.orientation_source_status,
            "construction_status": self.construction_status,
        }

    @property
    def geometry_digest(self) -> str:
        identity = {
            "schema": "triangular_reference_geometry_identity_v3",
            "fr": self.fr,
            "primitive_kind": self.primitive_kind,
            "analytic_radius": self.analytic_radius,
            "analytic_area": self.analytic_area,
            "air_fill_fraction": self.air_fill_fraction,
            "lattice_constant": self.lattice_constant,
            "polarization": self.polarization,
            "geometry_equivalence": self.geometry_equivalence,
            "paper_parameter_equivalence": self.paper_parameter_equivalence,
            "material_contract_digest": self.material_contract_digest,
            "orientation": {
                "degrees": self.triangle_orientation_degrees,
                "convention": self.orientation_convention,
                "source_status": self.orientation_source_status,
            },
        }
        if self.primitive_kind == "rounded_triangle_close_analogue":
            identity["boundary_construction_version"] = self.boundary_construction_version
            identity["boundary_digest"] = self.boundary_digest
        payload = json.dumps(identity, sort_keys=True, separators=(",", ":"), allow_nan=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_triangular_reference_geometry(
    fr: float,
    *,
    air_fill_fraction: float = REFERENCE_AIR_FILL_FRACTION,
    effective_permittivity: float = REFERENCE_EFFECTIVE_PERMITTIVITY,
    material_semantics: str = "RELATIVE_PERMITTIVITY",
) -> TriangularReferenceGeometry:
    """Build the internal triangular reference contract without MPB."""
    if isinstance(fr, bool) or not math.isfinite(float(fr)) or not 0.0 <= float(fr) <= 0.5:
        raise ValueError("fr must lie in [0, 0.5]")
    if not math.isfinite(float(air_fill_fraction)) or not 0.0 < float(air_fill_fraction) < 1.0:
        raise ValueError("air_fill_fraction must lie in (0, 1)")
    if not math.isfinite(float(effective_permittivity)) or float(effective_permittivity) <= 0.0:
        raise ValueError("effective_permittivity must be positive")
    if material_semantics not in {"REFRACTIVE_INDEX", "RELATIVE_PERMITTIVITY", "UNRESOLVED"}:
        raise ValueError("material_semantics is invalid")
    fr = float(fr)
    target_area = float(air_fill_fraction) * TRIANGULAR_CELL_AREA
    vertices = _canonical_vertices(_make_boundary(fr, target_area))
    result = TriangularReferenceGeometry(
        fr=fr,
        vertices=vertices,
        air_fill_fraction=float(air_fill_fraction),
        effective_permittivity=float(effective_permittivity),
        reference_material_semantics=material_semantics,
        reference_material_source_role=REFERENCE_MATERIAL_SOURCE_ROLE,
        primitive_kind="triangle" if fr == 0.0 else "circle" if fr == 0.5 else "rounded_triangle_close_analogue",
        analytic_radius=_triangle_radius_for_area(target_area) if fr == 0.0 else _circle_radius_for_area(target_area) if fr == 0.5 else None,
        geometry_equivalence="PAPER_PARAMETER_BOUND" if fr in {0.0, 0.5} else "CLOSE_ANALOGUE",
        paper_parameter_equivalence="PAPER_PARAMETER_BOUND" if fr in {0.0, 0.5} else "UNRESOLVED",
        polygonization_version="ANALYTIC_TRIANGLE_V1" if fr == 0.0 else "ANALYTIC_CIRCLE_WITH_DISPLAY_POLYGON_V1" if fr == 0.5 else "INTERNAL_CLOSE_ANALOGUE_RADIAL_MORPH_V1",
        boundary_construction_version="ANALYTIC_TRIANGLE_V1" if fr == 0.0 else "ANALYTIC_CIRCLE_WITH_DISPLAY_POLYGON_V1" if fr == 0.5 else "INTERNAL_CLOSE_ANALOGUE_RADIAL_MORPH_V1",
        triangle_orientation_degrees=90.0,
        orientation_convention="PUBLIC_CARTESIAN_QX_QY_CCW",
        orientation_source_status="CONVENTION_MAPPED",
    )
    if abs(result.fill_fraction_error) > 5e-13:
        raise RuntimeError("reference geometry failed its fixed-fill construction")
    return result


__all__ = [
    "REFERENCE_AIR_FILL_FRACTION",
    "REFERENCE_EFFECTIVE_PERMITTIVITY", "REFERENCE_MATERIAL_VALUE", "REFERENCE_MATERIAL_SOURCE_ROLE",
    "TRIANGULAR_CELL_AREA",
    "TriangularReferenceGeometry",
    "build_triangular_reference_geometry",
]
