"""Solver-neutral, reference-cell-safe mixed ``q-s`` Berry geometry.

The module consumes already-normalized periodic-H vectors.  It owns neither
geometry construction nor field solving; reference-cell metadata is checked
before any overlap or Wilson transport is evaluated.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import math
from numbers import Real
from typing import Any

import numpy as np

from .eigenspace import EigenSubspace
from .subspace_transport import SubspaceTransportError, SubspaceTransportLink, parallel_transport_link


DEFAULT_TOLERANCE = 1e-10
REPRESENTATION = "mpb_periodic_h_l2_v1"
MU1_NONMAGNETIC = "MU1_NONMAGNETIC"
LAB_CARTESIAN = "LAB_CARTESIAN"


class PhaseSpaceGeometryError(ValueError):
    """Base class for fail-closed phase-space geometry errors."""


class ReferenceCellMismatchError(PhaseSpaceGeometryError):
    pass


class PhaseSpaceIdentityMismatchError(PhaseSpaceGeometryError):
    pass


class DiamondGeometryMismatchError(PhaseSpaceGeometryError):
    pass


class RankMismatchError(PhaseSpaceGeometryError):
    pass


class AmbientDimensionMismatchError(PhaseSpaceGeometryError):
    pass


class SingularTransportError(PhaseSpaceGeometryError):
    pass


class NonfiniteStateError(PhaseSpaceGeometryError):
    pass


class InvalidNormalizationError(PhaseSpaceGeometryError):
    pass


class FixedQDerivativeMismatchError(PhaseSpaceGeometryError):
    pass


def _real(value: Any, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite real scalar")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _positive(value: Any, *, name: str) -> float:
    result = _real(value, name=name)
    if result <= 0.0:
        raise ValueError(f"{name} must be positive")
    return result


def _integer(value: Any, *, name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return int(value)


def _vector(value: Any, *, name: str, size: int | None = None) -> tuple[float, ...]:
    try:
        array = np.asarray(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if array.ndim != 1 or array.dtype.kind not in "iuf" or (size is not None and array.size != size):
        raise ValueError(f"{name} must be a real vector of size {size or 'any'}")
    if not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must be finite")
    return tuple(float(item) for item in array)


def _matrix(value: Any, *, name: str, shape: tuple[int, int] = (2, 2)) -> tuple[tuple[float, ...], ...]:
    try:
        array = np.asarray(value, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if array.shape != shape or not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must be finite with shape {shape}")
    return tuple(tuple(float(item) for item in row) for row in array)


def _tolerance(value: Any, *, name: str = "tolerance") -> float:
    result = _real(value, name=name)
    if result < 0.0:
        raise ValueError(f"{name} must be non-negative")
    return result


def _json_safe(value: Any) -> Any:
    if value is None or type(value) in {bool, str, int}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("metadata contains a non-finite float")
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    raise ValueError("metadata must be JSON-safe")


def _matrix_array(value: tuple[tuple[float, ...], ...]) -> np.ndarray:
    return np.asarray(value, dtype=float)


@dataclass(frozen=True)
class ReferenceCellIdentity:
    """Immutable compatibility identity for the certified reference cell."""

    representation: str = REPRESENTATION
    bloch_phase_excluded: bool = True
    resolution: int = 1
    spatial_shape: tuple[int, int] = (1, 1)
    lattice_size: tuple[float, float] = (1.0, 1.0)
    component_order: str = "supplied final axis order"
    component_basis: str = LAB_CARTESIAN
    mu_contract: str = MU1_NONMAGNETIC
    orientation_sign: int = 1
    fractional_material_indexing_identity: str = "same fractional (ix,iy) material coordinates"
    reference_cell_identity: str = "certified-common-reference-cell"

    def __post_init__(self) -> None:
        if not isinstance(self.representation, str) or not self.representation:
            raise ValueError("representation must be a non-empty string")
        if type(self.bloch_phase_excluded) is not bool:
            raise ValueError("bloch_phase_excluded must be bool")
        object.__setattr__(self, "resolution", _integer(self.resolution, name="resolution", minimum=1))
        shape = tuple(_integer(item, name="spatial_shape", minimum=1) for item in self.spatial_shape)
        if len(shape) != 2:
            raise ValueError("spatial_shape must have two positive dimensions")
        object.__setattr__(self, "spatial_shape", shape)
        lattice = _vector(self.lattice_size, name="lattice_size", size=2)
        if any(item <= 0.0 for item in lattice):
            raise ValueError("lattice_size must be positive")
        object.__setattr__(self, "lattice_size", lattice)
        if not isinstance(self.component_order, str) or not isinstance(self.component_basis, str) or not isinstance(self.mu_contract, str):
            raise ValueError("component and material contracts must be strings")
        if self.orientation_sign not in (-1, 1):
            raise ValueError("orientation_sign must be +1 or -1")
        for name in ("fractional_material_indexing_identity", "reference_cell_identity"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name):
                raise ValueError(f"{name} must be a non-empty string")

    def compatibility_key(self) -> tuple[Any, ...]:
        return (
            self.representation, self.bloch_phase_excluded, self.resolution,
            self.spatial_shape, self.lattice_size, self.component_order,
            self.component_basis, self.mu_contract, self.orientation_sign,
            self.fractional_material_indexing_identity, self.reference_cell_identity,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "representation": self.representation,
            "bloch_phase_excluded": self.bloch_phase_excluded,
            "resolution": self.resolution,
            "spatial_shape": list(self.spatial_shape),
            "lattice_size": list(self.lattice_size),
            "component_order": self.component_order,
            "component_basis": self.component_basis,
            "mu_contract": self.mu_contract,
            "orientation_sign": self.orientation_sign,
            "fractional_material_indexing_identity": self.fractional_material_indexing_identity,
            "reference_cell_identity": self.reference_cell_identity,
        }


@dataclass(frozen=True)
class PhaseSpaceStateIdentity:
    """Identity binding one already-computed state to ``(q,s)``."""

    public_q: tuple[float, float]
    s: float
    derived_kappa: tuple[float, float]
    A_s: tuple[tuple[float, ...], ...]
    F_s: tuple[tuple[float, ...], ...]
    geometry_identity: str
    reference_cell: ReferenceCellIdentity
    solver_configuration_identity: str
    det_f_tolerance: float = 1e-10

    def __post_init__(self) -> None:
        object.__setattr__(self, "public_q", _vector(self.public_q, name="public_q", size=2))
        object.__setattr__(self, "s", _real(self.s, name="s"))
        object.__setattr__(self, "derived_kappa", _vector(self.derived_kappa, name="derived_kappa", size=2))
        object.__setattr__(self, "A_s", _matrix(self.A_s, name="A_s"))
        object.__setattr__(self, "F_s", _matrix(self.F_s, name="F_s"))
        if not isinstance(self.reference_cell, ReferenceCellIdentity):
            raise TypeError("reference_cell must be a ReferenceCellIdentity")
        if not isinstance(self.geometry_identity, str) or not self.geometry_identity:
            raise ValueError("geometry_identity must be a non-empty string")
        if not isinstance(self.solver_configuration_identity, str) or not self.solver_configuration_identity:
            raise ValueError("solver_configuration_identity must be a non-empty string")
        tolerance = _tolerance(self.det_f_tolerance, name="det_f_tolerance")
        object.__setattr__(self, "det_f_tolerance", tolerance)
        determinant = float(np.linalg.det(_matrix_array(self.F_s)))
        if determinant <= 0.0:
            raise PhaseSpaceIdentityMismatchError("det F_s must be positive")

    @property
    def determinant_f(self) -> float:
        return float(np.linalg.det(_matrix_array(self.F_s)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "public_q": list(self.public_q), "s": self.s, "derived_kappa": list(self.derived_kappa),
            "A_s": [list(row) for row in self.A_s], "F_s": [list(row) for row in self.F_s],
            "determinant_f": self.determinant_f, "geometry_identity": self.geometry_identity,
            "reference_cell": self.reference_cell.to_dict(),
            "solver_configuration_identity": self.solver_configuration_identity,
        }


def _checked_vector(value: Any, *, name: str, tolerance: float) -> np.ndarray:
    try:
        array = np.asarray(value, dtype=np.complex128)
    except (TypeError, ValueError) as exc:
        raise NonfiniteStateError(f"{name} is not numeric") from exc
    if array.ndim != 1 or array.size == 0 or not np.all(np.isfinite(array)):
        raise NonfiniteStateError(f"{name} must be a finite non-empty vector")
    norm = float(np.linalg.norm(array))
    if not math.isfinite(norm) or abs(norm - 1.0) > tolerance:
        raise InvalidNormalizationError(f"{name} must already have unit norm")
    result = np.array(array, copy=True)
    result.setflags(write=False)
    return result


@dataclass(frozen=True)
class HState:
    """Immutable wrapper for normalized periodic-H vectors and metadata."""

    identity: PhaseSpaceStateIdentity
    frequencies: tuple[float, ...]
    h_vectors: tuple[np.ndarray, ...]
    band_indices: tuple[int, ...]
    normalization_tolerance: float = DEFAULT_TOLERANCE

    def __post_init__(self) -> None:
        if not isinstance(self.identity, PhaseSpaceStateIdentity):
            raise TypeError("identity must be a PhaseSpaceStateIdentity")
        tolerance = _tolerance(self.normalization_tolerance, name="normalization_tolerance")
        object.__setattr__(self, "normalization_tolerance", tolerance)
        frequencies = tuple(_real(value, name="frequency") for value in self.frequencies)
        vectors = tuple(_checked_vector(value, name="h_vector", tolerance=tolerance) for value in self.h_vectors)
        indices = tuple(_integer(value, name="band_index", minimum=0) for value in self.band_indices)
        if not vectors or len(vectors) != len(frequencies) or len(vectors) != len(indices):
            raise ValueError("frequencies, h_vectors, and band_indices must have equal nonzero length")
        ambient = vectors[0].size
        if any(vector.size != ambient for vector in vectors):
            raise AmbientDimensionMismatchError("all H vectors must have equal ambient dimensions")
        if len(set(indices)) != len(indices):
            raise ValueError("band_indices must be unique")
        object.__setattr__(self, "frequencies", frequencies)
        object.__setattr__(self, "h_vectors", vectors)
        object.__setattr__(self, "band_indices", indices)

    @property
    def rank(self) -> int:
        return len(self.h_vectors)

    @property
    def ambient_dimension(self) -> int:
        return int(self.h_vectors[0].size)

    def vector_for_band(self, band_index: int) -> np.ndarray:
        try:
            return self.h_vectors[self.band_indices.index(_integer(band_index, name="band_index"))]
        except ValueError as exc:
            raise FixedQDerivativeMismatchError(f"band {band_index} is not bound by this H state") from exc

    def frequency_for_band(self, band_index: int) -> float:
        try:
            return self.frequencies[self.band_indices.index(_integer(band_index, name="band_index"))]
        except ValueError as exc:
            raise FixedQDerivativeMismatchError(f"band {band_index} is not bound by this H state") from exc

    def to_dict(self) -> dict[str, Any]:
        return {"identity": self.identity.to_dict(), "rank": self.rank, "ambient_dimension": self.ambient_dimension, "frequencies": list(self.frequencies), "band_indices": list(self.band_indices)}


def h_state_from_normalized_vectors(
    identity: PhaseSpaceStateIdentity,
    h_vectors: Sequence[Any],
    *,
    frequencies: Sequence[Any] | None = None,
    band_indices: Sequence[Any] | None = None,
    normalization_tolerance: float = DEFAULT_TOLERANCE,
) -> HState:
    candidate = np.asarray(h_vectors)
    vectors = (h_vectors,) if candidate.ndim == 1 else tuple(h_vectors)
    if not vectors:
        raise ValueError("h_vectors must not be empty")
    frequencies = tuple(0.0 for _ in vectors) if frequencies is None else tuple(frequencies)
    band_indices = tuple(range(len(vectors))) if band_indices is None else tuple(band_indices)
    return HState(identity, frequencies, vectors, band_indices, normalization_tolerance)


def h_state_from_snapshot(snapshot: Any, identity: PhaseSpaceStateIdentity, *, band_indices: Sequence[Any] | None = None) -> HState:
    """Consume an existing MPB H snapshot without importing or running a solver."""

    provenance = getattr(snapshot, "provenance", None)
    if not isinstance(provenance, Mapping):
        raise ReferenceCellMismatchError("snapshot provenance is required")
    if provenance.get("representation") != REPRESENTATION:
        raise ReferenceCellMismatchError("snapshot representation is not mpb_periodic_h_l2_v1")
    if provenance.get("bloch_phase_excluded") is not True:
        raise ReferenceCellMismatchError("snapshot must exclude Bloch phase")
    if provenance.get("component_count") != 3:
        raise ReferenceCellMismatchError("snapshot must contain three H components")
    if provenance.get("normalization_convention") != "per-band H-space discrete L2 norm":
        raise ReferenceCellMismatchError("snapshot normalization convention mismatch")
    if provenance.get("metric") != "sum(conj(H1) * H2) over x y and vector component":
        raise ReferenceCellMismatchError("snapshot material metric mismatch")
    fields = np.asarray(getattr(snapshot, "h_fields", None))
    if fields.ndim != 4 or fields.shape[3] != 3 or tuple(fields.shape[1:3]) != identity.reference_cell.spatial_shape:
        raise ReferenceCellMismatchError("snapshot spatial shape or component count mismatch")
    vectors = tuple(getattr(snapshot, "normalized_vectors", ()))
    frequencies = tuple(getattr(snapshot, "frequencies", ()))
    indices = tuple(range(len(vectors))) if band_indices is None else tuple(band_indices)
    return h_state_from_normalized_vectors(identity, vectors, frequencies=frequencies, band_indices=indices)


def validate_reference_cell_compatibility(left: HState, right: HState) -> None:
    if left.identity.reference_cell.compatibility_key() != right.identity.reference_cell.compatibility_key():
        raise ReferenceCellMismatchError("reference-cell compatibility identity mismatch")
    if left.identity.reference_cell.mu_contract != MU1_NONMAGNETIC:
        raise ReferenceCellMismatchError("current H-space contract requires MU1_NONMAGNETIC")
    if left.identity.reference_cell.component_basis != LAB_CARTESIAN:
        raise ReferenceCellMismatchError("current H-space contract requires LAB_CARTESIAN components")
    if left.identity.reference_cell.orientation_sign != 1:
        raise ReferenceCellMismatchError("orientation-reversing reference cells are fail-closed")
    if left.ambient_dimension != right.ambient_dimension:
        raise AmbientDimensionMismatchError("H state ambient dimensions differ")
    if left.rank != right.rank:
        raise RankMismatchError("H state ranks differ")


def reference_cell_link(left: HState, right: HState, *, min_singular_value: float = 1e-12, tolerance: float = DEFAULT_TOLERANCE) -> SubspaceTransportLink:
    validate_reference_cell_compatibility(left, right)
    left_subspace = EigenSubspace(left.identity.public_q, np.column_stack(left.h_vectors), left.frequencies, left.band_indices, {"reference_cell": left.identity.reference_cell.to_dict()})
    right_subspace = EigenSubspace(right.identity.public_q, np.column_stack(right.h_vectors), right.frequencies, right.band_indices, {"reference_cell": right.identity.reference_cell.to_dict()})
    try:
        return parallel_transport_link(left_subspace, right_subspace, min_singular_value=min_singular_value, validation_tolerance=tolerance)
    except SubspaceTransportError as exc:
        raise SingularTransportError(str(exc)) from exc


@dataclass(frozen=True)
class MixedDiamond:
    plus_q: HState
    plus_s: HState
    minus_q: HState
    minus_s: HState
    axis: int
    h_q: float
    h_s: float
    q_center: tuple[float, float]
    s_center: float
    tolerance: float = DEFAULT_TOLERANCE

    def __post_init__(self) -> None:
        if not all(isinstance(item, HState) for item in (self.plus_q, self.plus_s, self.minus_q, self.minus_s)):
            raise TypeError("diamond vertices must be HState values")
        if self.axis not in (0, 1):
            raise DiamondGeometryMismatchError("axis must be 0 (qx) or 1 (qy)")
        object.__setattr__(self, "h_q", _positive(self.h_q, name="h_q"))
        object.__setattr__(self, "h_s", _positive(self.h_s, name="h_s"))
        object.__setattr__(self, "q_center", _vector(self.q_center, name="q_center", size=2))
        object.__setattr__(self, "s_center", _real(self.s_center, name="s_center"))
        object.__setattr__(self, "tolerance", _tolerance(self.tolerance))
        vertices = ((self.plus_q, (1.0, 0.0)), (self.plus_s, (0.0, 1.0)), (self.minus_q, (-1.0, 0.0)), (self.minus_s, (0.0, -1.0)))
        for state, (q_sign, s_sign) in vertices:
            expected_q = np.asarray(self.q_center, dtype=float)
            if q_sign:
                expected_q[self.axis] += q_sign * self.h_q
            expected_s = self.s_center + s_sign * self.h_s
            if not np.allclose(state.identity.public_q, expected_q, rtol=0.0, atol=self.tolerance) or not math.isclose(state.identity.s, expected_s, rel_tol=0.0, abs_tol=self.tolerance):
                raise DiamondGeometryMismatchError("diamond vertex is not at its declared centered q-s role")
        validate_reference_cell_compatibility(self.plus_q, self.plus_s)
        validate_reference_cell_compatibility(self.plus_q, self.minus_q)
        validate_reference_cell_compatibility(self.plus_q, self.minus_s)

    @property
    def signed_area_qs(self) -> float:
        return 2.0 * self.h_q * self.h_s


def make_mixed_diamond(*, plus_q: HState, plus_s: HState, minus_q: HState, minus_s: HState, axis: int, h_q: float, h_s: float, q_center: Sequence[float], s_center: float, tolerance: float = DEFAULT_TOLERANCE) -> MixedDiamond:
    return MixedDiamond(plus_q, plus_s, minus_q, minus_s, axis, h_q, h_s, tuple(q_center), s_center, tolerance)


@dataclass(frozen=True)
class MixedCurvatureResult:
    rank: int
    phase: float
    omega_qs: float
    signed_area_qs: float
    minimum_link_singular_value: float
    maximum_link_principal_angle: float
    orientation: str
    interpretation: str

    def to_dict(self) -> dict[str, Any]:
        return {"rank": self.rank, "phase": self.phase, "omega_qs": self.omega_qs, "signed_area_qs": self.signed_area_qs, "minimum_link_singular_value": self.minimum_link_singular_value, "maximum_link_principal_angle": self.maximum_link_principal_angle, "orientation": self.orientation, "interpretation": self.interpretation}


def _coerce_diamond(diamond: MixedDiamond | None, vertices: dict[str, Any]) -> MixedDiamond:
    if diamond is not None:
        if vertices:
            raise TypeError("supply either diamond or explicit vertices, not both")
        return diamond
    required = ("plus_q", "plus_s", "minus_q", "minus_s", "axis", "h_q", "h_s", "q_center", "s_center")
    missing = [name for name in required if name not in vertices]
    if missing:
        raise TypeError("missing diamond arguments: " + ", ".join(missing))
    tolerance = vertices.pop("tolerance", DEFAULT_TOLERANCE)
    return make_mixed_diamond(tolerance=tolerance, **vertices)


def _wilson(diamond: MixedDiamond, *, reverse: bool = False) -> MixedCurvatureResult:
    sequence = ((diamond.plus_q, diamond.plus_s), (diamond.plus_s, diamond.minus_q), (diamond.minus_q, diamond.minus_s), (diamond.minus_s, diamond.plus_q))
    if reverse:
        sequence = tuple((right, left) for left, right in reversed(sequence))
    links = [reference_cell_link(left, right) for left, right in sequence]
    rank = links[0].dimension
    wilson = np.eye(rank, dtype=np.complex128)
    for link in links:
        wilson = wilson @ link.unitary
    phase = float(np.angle(np.linalg.det(wilson)))
    return MixedCurvatureResult(
        rank=rank, phase=phase, omega_qs=float(-phase / diamond.signed_area_qs), signed_area_qs=diamond.signed_area_qs,
        minimum_link_singular_value=min(link.min_singular_value for link in links),
        maximum_link_principal_angle=float(max(math.acos(min(1.0, max(-1.0, link.min_singular_value))) for link in links)),
        orientation="CW_REVERSE" if reverse else "CCW",
        interpretation="TRACE_OR_U1_SUBSPACE_GEOMETRY_ONLY" if rank > 1 else "SCALAR_RANK1_MIXED_CURVATURE",
    )


def rank1_mixed_curvature(diamond: MixedDiamond | None = None, **vertices: Any) -> MixedCurvatureResult:
    value = _coerce_diamond(diamond, vertices)
    if value.plus_q.rank != 1:
        raise RankMismatchError("rank1 mixed curvature requires rank one vertices")
    return _wilson(value)


def rankN_trace_mixed_curvature(diamond: MixedDiamond | None = None, **vertices: Any) -> MixedCurvatureResult:
    value = _coerce_diamond(diamond, vertices)
    if value.plus_q.rank < 1:
        raise RankMismatchError("rankN mixed curvature requires a positive rank")
    result = _wilson(value)
    return MixedCurvatureResult(**{**result.to_dict(), "interpretation": "TRACE_OR_U1_SUBSPACE_GEOMETRY_ONLY"})


def reverse_mixed_curvature(diamond: MixedDiamond) -> MixedCurvatureResult:
    if not isinstance(diamond, MixedDiamond):
        raise TypeError("diamond must be a MixedDiamond")
    return _wilson(diamond, reverse=True)


def fixed_q_frequency_derivative(plus_s: HState, minus_s: HState, *, band_index: int, h_s: float, tolerance: float = DEFAULT_TOLERANCE) -> float:
    if not isinstance(plus_s, HState) or not isinstance(minus_s, HState):
        raise TypeError("plus_s and minus_s must be HState values")
    validate_reference_cell_compatibility(plus_s, minus_s)
    if not np.allclose(plus_s.identity.public_q, minus_s.identity.public_q, rtol=0.0, atol=_tolerance(tolerance)):
        raise FixedQDerivativeMismatchError("fixed-q derivative requires identical public q")
    step = _positive(h_s, name="h_s")
    expected_center = (plus_s.identity.s + minus_s.identity.s) / 2.0
    if not math.isclose(plus_s.identity.s - minus_s.identity.s, 2.0 * step, rel_tol=0.0, abs_tol=_tolerance(tolerance)):
        raise FixedQDerivativeMismatchError("s endpoints do not match the declared centered h_s")
    return float((plus_s.frequency_for_band(band_index) - minus_s.frequency_for_band(band_index)) / (2.0 * step))


__all__ = [
    "DEFAULT_TOLERANCE", "REPRESENTATION", "MU1_NONMAGNETIC", "LAB_CARTESIAN",
    "PhaseSpaceGeometryError", "ReferenceCellMismatchError", "PhaseSpaceIdentityMismatchError",
    "DiamondGeometryMismatchError", "RankMismatchError", "AmbientDimensionMismatchError",
    "SingularTransportError", "NonfiniteStateError", "InvalidNormalizationError",
    "FixedQDerivativeMismatchError", "ReferenceCellIdentity", "PhaseSpaceStateIdentity",
    "HState", "h_state_from_normalized_vectors", "h_state_from_snapshot",
    "validate_reference_cell_compatibility", "reference_cell_link", "MixedDiamond",
    "make_mixed_diamond", "MixedCurvatureResult", "rank1_mixed_curvature",
    "rankN_trace_mixed_curvature", "reverse_mixed_curvature", "fixed_q_frequency_derivative",
]
