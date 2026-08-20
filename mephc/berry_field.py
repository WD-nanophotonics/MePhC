"""Internal fail-closed sampled Berry-field data and measure semantics.

This module is intentionally solver-neutral.  It stores qualified sampled
values and their evidence; it does not run a solver or make a topological
claim.  Integration is a generic rectangular field integral with explicit
coordinate-measure and mask-policy contracts.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import math
from types import MappingProxyType
from typing import Any

import numpy as np

from .berry_units import OMEGA_PHYS_OVER_A2, OMEGA_Q, Q_COORDINATE_SPACE


FIELD_SCHEMA = "mephc-qualified-berry-field/v1"
FIELD_PROVENANCE_VERSION = "e7i1c-field-provenance/v1"
QUALIFIED_VALUE = "QUALIFIED_VALUE"
MASKED = "MASKED"
MASK_REASONS = frozenset({
    "UNQUALIFIED_BAND_IDENTITY",
    "UNQUALIFIED_EXTERNAL_ISOLATION",
    "UNQUALIFIED_TRANSPORT",
    "RANK_ENLARGEMENT_REQUIRED",
    "NUMERICALLY_INCOMPLETE",
    "RUNTIME_FAILED",
})
STRICT_FAIL_CLOSED = "STRICT_FAIL_CLOSED"
EXPLICIT_SUBDOMAIN = "EXPLICIT_SUBDOMAIN"
UNSAFE = "UNSAFE"
D2Q = "D2Q"
D2K_PHYSICAL = "D2K_PHYSICAL"


class BerryFieldModelError(ValueError):
    """Raised when field data violates a semantic invariant."""


class MaskedFieldError(BerryFieldModelError):
    """Raised when a requested strict integral contains a masked point."""


def _safe(value: Any, path: str = "value") -> Any:
    if value is None or type(value) in {bool, str, int}:
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise BerryFieldModelError(f"{path} contains a non-finite float")
        return float(value)
    if isinstance(value, np.floating):
        return _safe(float(value), path)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, Mapping):
        return {str(key): _safe(item, f"{path}.{key}") for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(item, f"{path}[]") for item in value]
    raise BerryFieldModelError(f"{path} must be JSON-safe")


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _coordinate(value: Sequence[float], name: str) -> tuple[float, float]:
    if isinstance(value, (str, bytes)) or len(value) != 2:
        raise BerryFieldModelError(f"{name} must be a two-dimensional coordinate")
    result = tuple(float(item) for item in value)
    if not all(math.isfinite(item) for item in result):
        raise BerryFieldModelError(f"{name} must be finite")
    return result


def _axis(value: Sequence[float], name: str) -> tuple[float, ...]:
    if isinstance(value, (str, bytes)):
        raise BerryFieldModelError(f"{name} must be a coordinate axis")
    result = tuple(float(item) for item in value)
    if len(result) < 2 or not all(math.isfinite(item) for item in result):
        raise BerryFieldModelError(f"{name} must contain at least two finite coordinates")
    delta = np.diff(np.asarray(result, dtype=float))
    if not (np.all(delta > 0.0) or np.all(delta < 0.0)):
        raise BerryFieldModelError(f"{name} must be strictly monotonic")
    if len(set(result)) != len(result):
        raise BerryFieldModelError(f"{name} must not contain duplicate coordinates")
    return result


@dataclass(frozen=True)
class BerryFieldEvidenceAxes:
    spectral_isolation: Mapping[str, Any] = field(default_factory=dict)
    solver_repeatability: Mapping[str, Any] = field(default_factory=dict)
    transport_quality: Mapping[str, Any] = field(default_factory=dict)
    band_identity: Mapping[str, Any] = field(default_factory=dict)
    production_authority: str = "CURRENT_LOCAL_AUTHORITY"

    def __post_init__(self) -> None:
        for name in ("spectral_isolation", "solver_repeatability", "transport_quality", "band_identity"):
            value = getattr(self, name)
            if not isinstance(value, Mapping):
                raise BerryFieldModelError(f"{name} evidence must be a mapping")
            object.__setattr__(self, name, _freeze(_safe(dict(value), name)))
        if not isinstance(self.production_authority, str) or not self.production_authority:
            raise BerryFieldModelError("production_authority must be non-empty")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "BerryFieldEvidenceAxes":
        value = {} if value is None else value
        return cls(
            spectral_isolation=(value.get("spectral_isolation", {}) if isinstance(value.get("spectral_isolation", {}), Mapping) else {"status": value.get("spectral_isolation")}),
            solver_repeatability=(value.get("solver_repeatability", {}) if isinstance(value.get("solver_repeatability", {}), Mapping) else {"status": value.get("solver_repeatability")}),
            transport_quality=(value.get("transport_quality", {}) if isinstance(value.get("transport_quality", {}), Mapping) else {"status": value.get("transport_quality")}),
            band_identity=(value.get("band_identity", {}) if isinstance(value.get("band_identity", {}), Mapping) else {"status": value.get("band_identity")}),
            production_authority=str(value.get("production_authority", "CURRENT_LOCAL_AUTHORITY")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "spectral_isolation": _thaw(self.spectral_isolation),
            "solver_repeatability": _thaw(self.solver_repeatability),
            "transport_quality": _thaw(self.transport_quality),
            "band_identity": _thaw(self.band_identity),
            "production_authority": self.production_authority,
        }


@dataclass(frozen=True)
class CoordinateMeasureContract:
    """The q/k Jacobian and dual curvature-unit contract."""

    lattice_scale_a: float = 1.0
    coordinate_space: str = Q_COORDINATE_SPACE
    q_curvature_unit: str = OMEGA_Q
    physical_normalized_curvature_unit: str = OMEGA_PHYS_OVER_A2
    q_to_k_jacobian: float = field(init=False)
    k_to_q_jacobian: float = field(init=False)
    curvature_conversion_factor: float = field(init=False)

    def __post_init__(self) -> None:
        a = float(self.lattice_scale_a)
        if not math.isfinite(a) or a <= 0.0:
            raise BerryFieldModelError("lattice_scale_a must be positive and finite")
        if self.coordinate_space != Q_COORDINATE_SPACE:
            raise BerryFieldModelError("unsupported coordinate space")
        if self.q_curvature_unit != OMEGA_Q or self.physical_normalized_curvature_unit != OMEGA_PHYS_OVER_A2:
            raise BerryFieldModelError("unsupported Berry curvature unit contract")
        object.__setattr__(self, "lattice_scale_a", a)
        object.__setattr__(self, "q_to_k_jacobian", (2.0 * math.pi / a) ** 2)
        object.__setattr__(self, "k_to_q_jacobian", (a / (2.0 * math.pi)) ** 2)
        object.__setattr__(self, "curvature_conversion_factor", 1.0 / (2.0 * math.pi) ** 2)

    def omega_q_to_phys_over_a2(self, omega_q: float) -> float:
        return float(omega_q) * self.curvature_conversion_factor

    def omega_phys_over_a2_to_q(self, omega_phys_over_a2: float) -> float:
        return float(omega_phys_over_a2) / self.curvature_conversion_factor

    def flux_element_from_q(self, omega_q: float, dq_area: float) -> float:
        return float(omega_q) * float(dq_area)

    def flux_element_from_physical_k(self, omega_phys_over_a2: float, dk_area: float) -> float:
        # Omega_phys_over_a2 is normalized by a^2, so restore a^2 before
        # multiplying by physical-k area.  This equals Omega_q d^2q.
        return float(omega_phys_over_a2) * float(dk_area) * self.lattice_scale_a**2

    def to_dict(self) -> dict[str, Any]:
        return {
            "coordinate_space": self.coordinate_space,
            "q_curvature_unit": self.q_curvature_unit,
            "physical_normalized_curvature_unit": self.physical_normalized_curvature_unit,
            "lattice_scale_a": self.lattice_scale_a,
            "q_to_k_jacobian": self.q_to_k_jacobian,
            "k_to_q_jacobian": self.k_to_q_jacobian,
            "curvature_conversion_factor": self.curvature_conversion_factor,
            "identity": "Omega_phys_over_a2=Omega_q/(2*pi)^2; d2k=(2*pi/a)^2*d2q",
        }


@dataclass(frozen=True)
class QualifiedBerryFieldPoint:
    q_coordinate: tuple[float, float]
    omega_q: float | None
    omega_phys_over_a2: float | None
    selected_bands_one_based: tuple[int, ...]
    rank: int
    production_decision: str
    mask_reason: str | None
    evidence_axes: BerryFieldEvidenceAxes
    resolution: int
    plaquette_h: float
    representation: str
    geometry_identity: str
    provenance: Mapping[str, Any] = field(default_factory=dict)
    physical_k_coordinate: tuple[float, float] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "q_coordinate", _coordinate(self.q_coordinate, "q_coordinate"))
        if not isinstance(self.evidence_axes, BerryFieldEvidenceAxes):
            object.__setattr__(self, "evidence_axes", BerryFieldEvidenceAxes.from_mapping(self.evidence_axes))
        if self.physical_k_coordinate is not None:
            object.__setattr__(self, "physical_k_coordinate", _coordinate(self.physical_k_coordinate, "physical_k_coordinate"))
        bands = tuple(int(item) for item in self.selected_bands_one_based)
        if not bands or any(item < 1 for item in bands) or len(set(bands)) != len(bands):
            raise BerryFieldModelError("selected bands must be distinct positive one-based indices")
        if isinstance(self.rank, bool) or int(self.rank) < 1:
            raise BerryFieldModelError("rank must be positive")
        if self.production_decision == QUALIFIED_VALUE:
            if self.mask_reason is not None:
                raise BerryFieldModelError("qualified points cannot carry a mask reason")
            if self.omega_q is None or self.omega_phys_over_a2 is None:
                raise BerryFieldModelError("qualified points require both curvature units")
            expected = float(self.omega_q) / (2.0 * math.pi) ** 2
            if not math.isclose(float(self.omega_phys_over_a2), expected, rel_tol=1e-12, abs_tol=1e-14):
                raise BerryFieldModelError("dual curvature units are inconsistent")
        else:
            if self.mask_reason not in MASK_REASONS:
                raise BerryFieldModelError("unqualified points require an explicit mask reason")
            if self.omega_q is not None or self.omega_phys_over_a2 is not None:
                raise BerryFieldModelError("masked points must not carry fake curvature values")
        for name, value in (("resolution", self.resolution), ("plaquette_h", self.plaquette_h),
                            ("representation", self.representation), ("geometry_identity", self.geometry_identity)):
            if name == "resolution" and (isinstance(value, bool) or int(value) < 1):
                raise BerryFieldModelError("resolution must be positive")
            if name == "plaquette_h" and (not math.isfinite(float(value)) or float(value) <= 0.0):
                raise BerryFieldModelError("plaquette_h must be positive")
            if name in {"representation", "geometry_identity"} and (not isinstance(value, str) or not value):
                raise BerryFieldModelError(f"{name} must be non-empty")
        object.__setattr__(self, "selected_bands_one_based", bands)
        object.__setattr__(self, "rank", int(self.rank))
        object.__setattr__(self, "resolution", int(self.resolution))
        object.__setattr__(self, "plaquette_h", float(self.plaquette_h))
        object.__setattr__(self, "provenance", _freeze(_safe(dict(self.provenance), "provenance")))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "QualifiedBerryFieldPoint":
        provenance = dict(value.get("provenance", {}))
        axes = value.get("qualification_axes", value.get("evidence_axes", {}))
        return cls(
            q_coordinate=value.get("q_coordinate", value.get("target_q")),
            omega_q=value.get("omega_q", value.get("omega_anti_q")),
            omega_phys_over_a2=value.get("omega_phys_over_a2", value.get("omega_anti_phys_over_a2")),
            selected_bands_one_based=tuple(value.get("selected_bands_one_based", (1,))),
            rank=value.get("rank", 1),
            production_decision=value.get("production_decision", MASKED),
            mask_reason=value.get("mask_reason"),
            evidence_axes=BerryFieldEvidenceAxes.from_mapping(axes),
            resolution=value.get("resolution"),
            plaquette_h=value.get("plaquette_h", value.get("h")),
            representation=value.get("representation", provenance.get("representation", "unknown")),
            geometry_identity=value.get("geometry_identity", provenance.get("geometry", "unknown")),
            provenance=provenance,
            physical_k_coordinate=value.get("physical_k_coordinate"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "q_coordinate": list(self.q_coordinate),
            "physical_k_coordinate": None if self.physical_k_coordinate is None else list(self.physical_k_coordinate),
            "omega_q": self.omega_q,
            "omega_phys_over_a2": self.omega_phys_over_a2,
            "selected_bands_one_based": list(self.selected_bands_one_based),
            "rank": self.rank,
            "production_decision": self.production_decision,
            "mask_reason": self.mask_reason,
            "qualification_axes": self.evidence_axes.to_dict(),
            "resolution": self.resolution,
            "plaquette_h": self.plaquette_h,
            "representation": self.representation,
            "geometry_identity": self.geometry_identity,
            "provenance": _thaw(self.provenance),
        }


@dataclass(frozen=True)
class QualifiedBerryField:
    q_x: tuple[float, ...]
    q_y: tuple[float, ...]
    points: tuple[QualifiedBerryFieldPoint, ...]
    measure_contract: CoordinateMeasureContract = field(default_factory=CoordinateMeasureContract)
    geometry_identity: str = ""
    representation: str = ""
    plaquette_semantics: str = "CENTERED_CCW"
    field_provenance_version: str = FIELD_PROVENANCE_VERSION
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        q_x, q_y = _axis(self.q_x, "q_x"), _axis(self.q_y, "q_y")
        points = tuple(self.points)
        if not points or any(not isinstance(point, QualifiedBerryFieldPoint) for point in points):
            raise BerryFieldModelError("points must contain QualifiedBerryFieldPoint values")
        expected = {(x, y) for x in q_x for y in q_y}
        actual = [point.q_coordinate for point in points]
        if len(set(actual)) != len(actual):
            raise BerryFieldModelError("field contains duplicate coordinates")
        if set(actual) != expected:
            raise BerryFieldModelError("field has missing or unexpected grid coordinates")
        geometry = self.geometry_identity or points[0].geometry_identity
        representation = self.representation or points[0].representation
        if any(point.geometry_identity != geometry or point.representation != representation for point in points):
            raise BerryFieldModelError("incompatible geometry or representation was combined")
        resolution = points[0].resolution
        h = points[0].plaquette_h
        if any(point.resolution != resolution or point.plaquette_h != h for point in points):
            raise BerryFieldModelError("incompatible resolution or plaquette semantics was combined")
        if self.plaquette_semantics != "CENTERED_CCW":
            raise BerryFieldModelError("unsupported plaquette semantics")
        if not isinstance(self.measure_contract, CoordinateMeasureContract):
            raise BerryFieldModelError("measure_contract is invalid")
        object.__setattr__(self, "q_x", q_x)
        object.__setattr__(self, "q_y", q_y)
        object.__setattr__(self, "points", points)
        object.__setattr__(self, "geometry_identity", geometry)
        object.__setattr__(self, "representation", representation)
        object.__setattr__(self, "provenance", _freeze(_safe(dict(self.provenance), "provenance")))

    @classmethod
    def from_rows(cls, rows: Sequence[Mapping[str, Any]], *, measure_contract: CoordinateMeasureContract | None = None, provenance: Mapping[str, Any] | None = None) -> "QualifiedBerryField":
        points = tuple(QualifiedBerryFieldPoint.from_mapping(row) for row in rows)
        if not points:
            raise BerryFieldModelError("cannot build an empty field")
        q_x = tuple(sorted({point.q_coordinate[0] for point in points}))
        q_y = tuple(sorted({point.q_coordinate[1] for point in points}))
        return cls(q_x, q_y, points, measure_contract or CoordinateMeasureContract(), provenance=provenance or {})

    @property
    def shape(self) -> tuple[int, int]:
        return len(self.q_x), len(self.q_y)

    @property
    def requested_point_count(self) -> int:
        return len(self.points)

    @property
    def qualified_point_count(self) -> int:
        return sum(point.production_decision == QUALIFIED_VALUE for point in self.points)

    @property
    def qualification_fraction(self) -> float:
        return self.qualified_point_count / self.requested_point_count

    @property
    def mask_counts(self) -> dict[str, int]:
        counts = {reason: 0 for reason in sorted(MASK_REASONS)}
        for point in self.points:
            if point.mask_reason is not None:
                counts[point.mask_reason] += 1
        return counts

    @property
    def q_domain(self) -> tuple[float, float, float, float]:
        return self.q_x[0], self.q_x[-1], self.q_y[0], self.q_y[-1]

    def point_at(self, q_coordinate: Sequence[float]) -> QualifiedBerryFieldPoint:
        q = _coordinate(q_coordinate, "q_coordinate")
        for point in self.points:
            if point.q_coordinate == q:
                return point
        raise BerryFieldModelError("requested coordinate is not present")

    def values(self, unit_space: str, q_x: tuple[float, ...] | None = None, q_y: tuple[float, ...] | None = None) -> np.ndarray:
        if unit_space not in {OMEGA_Q, OMEGA_PHYS_OVER_A2}:
            raise BerryFieldModelError("unsupported integration curvature unit")
        xs, ys = q_x or self.q_x, q_y or self.q_y
        grid = []
        for x in xs:
            row = []
            for y in ys:
                point = self.point_at((x, y))
                value = point.omega_q if unit_space == OMEGA_Q else point.omega_phys_over_a2
                if value is None:
                    raise MaskedFieldError(f"masked point at {(x, y)}")
                row.append(float(value))
            grid.append(row)
        return np.asarray(grid, dtype=float)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": FIELD_SCHEMA,
            "field_provenance_version": self.field_provenance_version,
            "coordinate_space": Q_COORDINATE_SPACE,
            "curvature_units": [OMEGA_Q, OMEGA_PHYS_OVER_A2],
            "q_x": list(self.q_x),
            "q_y": list(self.q_y),
            "shape": list(self.shape),
            "grid_topology": "RECTANGULAR_REGULAR",
            "geometry_identity": self.geometry_identity,
            "representation": self.representation,
            "resolution": self.points[0].resolution,
            "plaquette_h": self.points[0].plaquette_h,
            "plaquette_semantics": self.plaquette_semantics,
            "qualification_fraction": self.qualification_fraction,
            "mask_counts": self.mask_counts,
            "measure_contract": self.measure_contract.to_dict(),
            "points": [point.to_dict() for point in self.points],
            "provenance": _thaw(self.provenance),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "QualifiedBerryField":
        if value.get("schema") != FIELD_SCHEMA:
            raise BerryFieldModelError("unsupported field schema")
        contract_data = value.get("measure_contract", {})
        contract = CoordinateMeasureContract(lattice_scale_a=contract_data.get("lattice_scale_a", 1.0))
        return cls(
            tuple(value["q_x"]), tuple(value["q_y"]),
            tuple(QualifiedBerryFieldPoint.from_mapping(point) for point in value["points"]),
            contract,
            geometry_identity=value.get("geometry_identity", ""),
            representation=value.get("representation", ""),
            plaquette_semantics=value.get("plaquette_semantics", "CENTERED_CCW"),
            field_provenance_version=value.get("field_provenance_version", FIELD_PROVENANCE_VERSION),
            provenance=value.get("provenance", {}),
        )


@dataclass(frozen=True)
class FieldIntegralResult:
    value: float
    curvature_unit: str
    measure: str
    mask_policy: str
    q_domain: tuple[float, float, float, float]
    sample_count: int
    signed_measure: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "curvature_unit": self.curvature_unit,
            "measure": self.measure,
            "mask_policy": self.mask_policy,
            "q_domain": list(self.q_domain),
            "sample_count": self.sample_count,
            "signed_measure": self.signed_measure,
        }


def _selected_axis(axis: tuple[float, ...], bounds: tuple[float, float] | None, name: str) -> tuple[float, ...]:
    if bounds is None:
        return axis
    low, high = map(float, bounds)
    if low > high or not math.isfinite(low) or not math.isfinite(high):
        raise BerryFieldModelError(f"{name} bounds must be finite and ordered")
    selected = tuple(value for value in axis if low <= value <= high)
    if len(selected) < 2:
        raise BerryFieldModelError(f"{name} must select an explicit stored subdomain")
    increasing = selected[0] < selected[-1]
    endpoints_ok = (selected[0] == low and selected[-1] == high) if increasing else (selected[0] == high and selected[-1] == low)
    if not endpoints_ok:
        raise BerryFieldModelError(f"{name} must select an explicit stored subdomain")
    return selected


def integrate_qualified_field(
    field: QualifiedBerryField,
    *,
    curvature_unit: str = OMEGA_Q,
    measure: str = D2Q,
    mask_policy: str = STRICT_FAIL_CLOSED,
    subdomain: tuple[float, float, float, float] | None = None,
) -> FieldIntegralResult:
    """Integrate a rectangular qualified scalar field with signed trapezoids."""
    if not isinstance(field, QualifiedBerryField):
        raise TypeError("field must be QualifiedBerryField")
    if curvature_unit not in {OMEGA_Q, OMEGA_PHYS_OVER_A2}:
        raise BerryFieldModelError("unsupported curvature unit")
    if measure not in {D2Q, D2K_PHYSICAL}:
        raise BerryFieldModelError("unsupported coordinate measure")
    if mask_policy not in {STRICT_FAIL_CLOSED, EXPLICIT_SUBDOMAIN}:
        raise BerryFieldModelError("unsafe or unknown mask policy")
    if mask_policy == EXPLICIT_SUBDOMAIN and subdomain is None:
        raise BerryFieldModelError("EXPLICIT_SUBDOMAIN requires explicit bounds")
    if curvature_unit == OMEGA_Q and measure != D2Q:
        raise BerryFieldModelError("OMEGA_Q requires d2q measure")
    if curvature_unit == OMEGA_PHYS_OVER_A2 and measure != D2K_PHYSICAL:
        raise BerryFieldModelError("OMEGA_PHYS_OVER_A2 requires physical-k measure")
    if subdomain is None:
        x_bounds = y_bounds = None
    else:
        if len(subdomain) != 4:
            raise BerryFieldModelError("subdomain must be (qx_min,qx_max,qy_min,qy_max)")
        x_bounds, y_bounds = (subdomain[0], subdomain[1]), (subdomain[2], subdomain[3])
    xs = _selected_axis(field.q_x, x_bounds, "qx")
    ys = _selected_axis(field.q_y, y_bounds, "qy")
    selected_points = [field.point_at((x, y)) for x in xs for y in ys]
    masked = [point for point in selected_points if point.production_decision != QUALIFIED_VALUE]
    if masked:
        reasons = sorted({point.mask_reason for point in masked})
        raise MaskedFieldError(f"masked points prevent integration: {reasons}")
    values = field.values(curvature_unit, xs, ys)
    trapezoid = np.trapezoid if hasattr(np, "trapezoid") else np.trapz
    integrate_y = trapezoid(values, np.asarray(ys), axis=1)
    value = float(trapezoid(integrate_y, np.asarray(xs), axis=0))
    if measure == D2K_PHYSICAL:
        value *= (2.0 * math.pi) ** 2
    return FieldIntegralResult(value, curvature_unit, measure, mask_policy, (xs[0], xs[-1], ys[0], ys[-1]), len(selected_points))


__all__ = [
    "D2K_PHYSICAL", "D2Q", "EXPLICIT_SUBDOMAIN", "FIELD_PROVENANCE_VERSION",
    "FIELD_SCHEMA", "FieldIntegralResult", "BerryFieldEvidenceAxes",
    "BerryFieldModelError", "CoordinateMeasureContract", "MASKED",
    "MASK_REASONS", "MaskedFieldError", "QUALIFIED_VALUE",
    "QualifiedBerryField", "QualifiedBerryFieldPoint", "STRICT_FAIL_CLOSED",
    "UNSAFE", "integrate_qualified_field",
]
