"""Canonical spatially varying in-plane deformation fields.

R5 deliberately keeps the field model separate from solver physics.  A field
maps reference positions with ``r' = r + u(r)`` and exposes diagnostic
quantities derived from ``F = I + grad(u)``.  Only a constant affine field is
eligible for the legacy primitive-cell workflow; a declared supercell must
pass an explicit periodic-boundary check before reciprocal-space use.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from typing import Callable, Mapping

import numpy as np

from .affine import AffineTransform2D
from .bravais import BravaisLattice2D


class DeformationFieldError(ValueError):
    """Invalid field data or an invalid field capability request."""


class PeriodicityError(DeformationFieldError):
    """A declared periodic field failed its explicit boundary verification."""


class SemanticCapabilityError(RuntimeError):
    """A reciprocal-space operation is not valid for the selected field."""


class DeformationCapability(str, Enum):
    GLOBAL_AFFINE_PERIODIC = "GLOBAL_AFFINE_PERIODIC"
    SUPERCELL_PERIODIC = "SUPERCELL_PERIODIC"
    APERIODIC_LOCAL = "APERIODIC_LOCAL"


def _points(values, *, allow_empty: bool = True) -> np.ndarray:
    array = np.asarray(values, dtype=float)
    if array.shape == (2,):
        array = array.reshape(1, 2)
    if array.ndim != 2 or array.shape[1] != 2 or (not allow_empty and len(array) == 0):
        raise DeformationFieldError("points must have shape (2,) or (N, 2)")
    if not np.all(np.isfinite(array)):
        raise DeformationFieldError("points must contain only finite values")
    return array


def _jsonable(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    return value


def _validate_vector(values, count: int, label: str) -> np.ndarray:
    array = np.asarray(values, dtype=float)
    if array.shape == (2,):
        array = np.broadcast_to(array, (count, 2)).copy()
    if array.shape != (count, 2) or not np.all(np.isfinite(array)):
        raise DeformationFieldError(f"{label} must return finite shape ({count}, 2) values")
    return array


class DeformationField(ABC):
    """Value-semantic displacement-field interface."""

    capability = DeformationCapability.APERIODIC_LOCAL
    stable_identity = True

    @abstractmethod
    def displacement(self, points) -> np.ndarray:
        """Return ``u(r)`` for one or more Cartesian points."""

    def gradient(self, points, *, step: float = 1e-6) -> np.ndarray:
        """Return a deterministic central-difference gradient ``du_i/dr_j``."""
        values = _points(points)
        step = float(step)
        if not np.isfinite(step) or step <= 0:
            raise DeformationFieldError("finite-difference step must be positive and finite")
        result = np.empty((len(values), 2, 2), dtype=float)
        for axis in range(2):
            delta = np.zeros(2, dtype=float)
            delta[axis] = step
            result[:, :, axis] = (
                self.displacement(values + delta) - self.displacement(values - delta)
            ) / (2.0 * step)
        if not np.all(np.isfinite(result)):
            raise DeformationFieldError("gradient contains non-finite values")
        return result

    def deformation_gradient(self, points) -> np.ndarray:
        values = _points(points)
        return np.eye(2, dtype=float)[None, :, :] + self.gradient(values)

    def jacobian(self, points) -> np.ndarray:
        return np.linalg.det(self.deformation_gradient(points))

    def small_strain(self, points) -> np.ndarray:
        grad = self.gradient(points)
        return 0.5 * (grad + np.swapaxes(grad, 1, 2))

    def rotation(self, points) -> np.ndarray:
        grad = self.gradient(points)
        return 0.5 * (grad - np.swapaxes(grad, 1, 2))

    def map_points(self, points) -> np.ndarray:
        values = _points(points)
        return values + self.displacement(values)

    apply = map_points

    def metadata(self) -> dict[str, object]:
        return {
            "schema": "mephc.deformation_field.v1",
            "capability": self.capability.value,
            "stable_identity": bool(self.stable_identity),
        }

    def fingerprint(self) -> str:
        payload = json.dumps(_jsonable(self.metadata()), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def require(self, operation: str, *, allow_supercell: bool = False) -> None:
        allowed = {DeformationCapability.GLOBAL_AFFINE_PERIODIC}
        if allow_supercell:
            allowed.add(DeformationCapability.SUPERCELL_PERIODIC)
        if self.capability not in allowed:
            expected = "global-affine primitive periodicity"
            if allow_supercell:
                expected += " or a verified supercell"
            raise SemanticCapabilityError(
                f"E_R5_PRIMITIVE_SEMANTICS: {operation} requires {expected}; "
                f"field capability is {self.capability.value}."
            )


@dataclass(frozen=True, slots=True)
class ZeroDeformationField(DeformationField):
    """Canonical zero field, equivalent to ``AffineTransform2D.identity()``."""

    capability = DeformationCapability.GLOBAL_AFFINE_PERIODIC
    stable_identity = True

    def displacement(self, points) -> np.ndarray:
        return np.zeros_like(_points(points))

    def gradient(self, points, *, step: float = 1e-6) -> np.ndarray:
        return np.zeros((len(_points(points)), 2, 2), dtype=float)

    def metadata(self) -> dict[str, object]:
        return {
            "schema": "mephc.deformation_field.v1",
            "kind": "zero",
            "capability": self.capability.value,
            "stable_identity": True,
            "canonical_affine": AffineTransform2D.identity().metadata(),
        }


@dataclass(frozen=True, slots=True)
class ConstantAffineField(DeformationField):
    """Displacement field induced by one existing global affine transform."""

    transform: AffineTransform2D

    capability = DeformationCapability.GLOBAL_AFFINE_PERIODIC
    stable_identity = True

    def __post_init__(self):
        if not isinstance(self.transform, AffineTransform2D):
            raise TypeError("transform must be an AffineTransform2D")

    def displacement(self, points) -> np.ndarray:
        values = _points(points)
        return values @ (self.transform.matrix - np.eye(2)).T

    def gradient(self, points, *, step: float = 1e-6) -> np.ndarray:
        count = len(_points(points))
        return np.broadcast_to(self.transform.matrix - np.eye(2), (count, 2, 2)).copy()

    def metadata(self) -> dict[str, object]:
        return {
            "schema": "mephc.deformation_field.v1",
            "kind": "constant_affine",
            "capability": self.capability.value,
            "stable_identity": True,
            "affine": self.transform.metadata(),
        }

    @property
    def affine_transform(self) -> AffineTransform2D:
        return self.transform


class AnalyticDeformationField(DeformationField):
    """Callable local field with optional analytic gradient and stable metadata."""

    capability = DeformationCapability.APERIODIC_LOCAL

    def __init__(self, value, *, gradient: Callable | None = None, domain=None,
                 stable_id: str | None = None, parameters: Mapping | None = None,
                 finite_difference_step: float = 1e-6):
        if not callable(value):
            raise TypeError("value must be callable")
        if gradient is not None and not callable(gradient):
            raise TypeError("gradient must be callable when supplied")
        if stable_id is not None and (not isinstance(stable_id, str) or not stable_id.strip()):
            raise DeformationFieldError("stable_id must be a non-empty string")
        if not np.isfinite(finite_difference_step) or finite_difference_step <= 0:
            raise DeformationFieldError("finite_difference_step must be positive and finite")
        self._value = value
        self._gradient = gradient
        self.domain = None if domain is None else tuple(float(v) for v in domain)
        if self.domain is not None and len(self.domain) != 4:
            raise DeformationFieldError("domain must be (xmin, xmax, ymin, ymax)")
        self.stable_id = stable_id
        self.parameters = dict(parameters or {})
        self.finite_difference_step = float(finite_difference_step)
        self.stable_identity = stable_id is not None

    def _check_domain(self, values):
        if self.domain is None:
            return
        xmin, xmax, ymin, ymax = self.domain
        if np.any(values[:, 0] < xmin) or np.any(values[:, 0] > xmax) or np.any(values[:, 1] < ymin) or np.any(values[:, 1] > ymax):
            raise DeformationFieldError("point lies outside the analytic field domain")

    def displacement(self, points) -> np.ndarray:
        values = _points(points)
        self._check_domain(values)
        return _validate_vector(self._value(values), len(values), "analytic field value")

    def gradient(self, points, *, step: float | None = None) -> np.ndarray:
        values = _points(points)
        self._check_domain(values)
        if self._gradient is None:
            return super().gradient(values, step=step or self.finite_difference_step)
        result = np.asarray(self._gradient(values), dtype=float)
        if result.shape == (2, 2):
            result = np.broadcast_to(result, (len(values), 2, 2)).copy()
        if result.shape != (len(values), 2, 2) or not np.all(np.isfinite(result)):
            raise DeformationFieldError(f"analytic gradient must return finite shape ({len(values)}, 2, 2) values")
        return result

    def metadata(self) -> dict[str, object]:
        return {
            "schema": "mephc.deformation_field.v1",
            "kind": "analytic",
            "capability": self.capability.value,
            "stable_identity": bool(self.stable_identity),
            "stable_id": self.stable_id,
            "parameters": _jsonable(self.parameters),
            "domain": self.domain,
            "gradient_policy": "analytic_callable" if self._gradient is not None else "central_difference",
            "finite_difference_step": self.finite_difference_step,
        }


class SampledDeformationField(DeformationField):
    """Deterministic bilinear interpolation on a rectangular sampled grid."""

    capability = DeformationCapability.APERIODIC_LOCAL

    def __init__(self, origin, spacing, displacements, *, stable_id: str | None = None,
                 interpolation: str = "bilinear"):
        self.origin = np.asarray(origin, dtype=float)
        self.spacing = np.asarray(spacing, dtype=float)
        self.samples = np.asarray(displacements, dtype=float)
        if self.origin.shape != (2,) or self.spacing.shape != (2,) or np.any(self.spacing <= 0) or not np.all(np.isfinite(self.spacing)):
            raise DeformationFieldError("origin must be 2D and spacing must be positive finite 2D")
        if self.samples.ndim != 3 or self.samples.shape[2] != 2 or min(self.samples.shape[:2]) < 2 or not np.all(np.isfinite(self.samples)):
            raise DeformationFieldError("displacements must have finite shape (ny, nx, 2), with nx and ny >= 2")
        if interpolation != "bilinear":
            raise DeformationFieldError("only deterministic 'bilinear' interpolation is supported")
        self.stable_id = stable_id
        self.stable_identity = True

    @property
    def extent(self) -> np.ndarray:
        return self.origin + self.spacing * np.array([self.samples.shape[1] - 1, self.samples.shape[0] - 1], dtype=float)

    def displacement(self, points) -> np.ndarray:
        values = _points(points)
        coordinate = (values - self.origin) / self.spacing
        if np.any(coordinate < 0) or np.any(coordinate[:, 0] > self.samples.shape[1] - 1) or np.any(coordinate[:, 1] > self.samples.shape[0] - 1):
            raise DeformationFieldError("point lies outside the sampled field domain")
        x = coordinate[:, 0]
        y = coordinate[:, 1]
        x0 = np.floor(x).astype(int).clip(0, self.samples.shape[1] - 2)
        y0 = np.floor(y).astype(int).clip(0, self.samples.shape[0] - 2)
        tx = (x - x0)[:, None]
        ty = (y - y0)[:, None]
        q00 = self.samples[y0, x0]
        q10 = self.samples[y0, x0 + 1]
        q01 = self.samples[y0 + 1, x0]
        q11 = self.samples[y0 + 1, x0 + 1]
        return (1 - ty) * ((1 - tx) * q00 + tx * q10) + ty * ((1 - tx) * q01 + tx * q11)

    def metadata(self) -> dict[str, object]:
        digest = hashlib.sha256(np.ascontiguousarray(self.samples).tobytes()).hexdigest()
        return {
            "schema": "mephc.deformation_field.v1",
            "kind": "sampled",
            "capability": self.capability.value,
            "stable_identity": True,
            "stable_id": self.stable_id,
            "origin": self.origin.tolist(),
            "spacing": self.spacing.tolist(),
            "shape": list(self.samples.shape),
            "sample_digest": digest,
            "interpolation": "bilinear",
        }


@dataclass(frozen=True, slots=True)
class SupercellLattice:
    """Direct/reciprocal basis for a declared integer supercell."""

    reference_lattice: BravaisLattice2D
    replication_matrix: tuple[tuple[int, int], tuple[int, int]]

    def __post_init__(self):
        if not isinstance(self.reference_lattice, BravaisLattice2D):
            raise TypeError("reference_lattice must be a BravaisLattice2D")
        matrix = np.asarray(self.replication_matrix, dtype=int)
        if matrix.shape != (2, 2) or not np.array_equal(matrix, np.asarray(self.replication_matrix, dtype=float)):
            raise DeformationFieldError("replication_matrix must be a 2 x 2 integer matrix")
        if abs(int(round(np.linalg.det(matrix)))) < 1:
            raise DeformationFieldError("replication_matrix must be nonsingular")
        if np.any(np.abs(matrix) > 10_000):
            raise DeformationFieldError("replication_matrix exceeds the safe R5 size limit")

    @property
    def matrix(self) -> np.ndarray:
        return np.asarray(self.replication_matrix, dtype=int)

    @property
    def direct_basis(self) -> np.ndarray:
        return self.reference_lattice.direct_basis @ self.matrix

    @property
    def reciprocal_basis(self) -> np.ndarray:
        return np.linalg.inv(self.direct_basis).T

    @property
    def multiplicity(self) -> int:
        return abs(int(round(np.linalg.det(self.matrix))))

    def metadata(self) -> dict[str, object]:
        return {
            "schema": "mephc.supercell_lattice.v1",
            "reference_lattice": self.reference_lattice.metadata(),
            "replication_matrix": self.matrix.tolist(),
            "multiplicity": self.multiplicity,
            "direct_basis": self.direct_basis.tolist(),
            "reciprocal_basis_no_2pi": self.reciprocal_basis.tolist(),
            "basis_convention": "columns_are_vectors",
            "semantic_label": "supercell",
        }


class PeriodicSupercellField(DeformationField):
    """A locally varying field admitted to reciprocal space only after proof."""

    capability = DeformationCapability.SUPERCELL_PERIODIC

    def __init__(self, field: DeformationField, reference_lattice: BravaisLattice2D,
                 replication_matrix=(1, 1), *, tolerance: float = 1e-9,
                 boundary_samples: int = 9, verify: bool = True):
        self.field = canonicalize_field(field)
        if isinstance(replication_matrix, (tuple, list)) and len(replication_matrix) == 2 and all(np.isscalar(v) for v in replication_matrix):
            replication_matrix = ((int(replication_matrix[0]), 0), (0, int(replication_matrix[1])))
        self.supercell = SupercellLattice(reference_lattice, tuple(tuple(int(v) for v in row) for row in replication_matrix))
        self.tolerance = float(tolerance)
        self.boundary_samples = int(boundary_samples)
        if not np.isfinite(self.tolerance) or self.tolerance <= 0 or self.boundary_samples < 2:
            raise DeformationFieldError("invalid supercell tolerance or boundary sample count")
        self._verified = False
        self._verification = None
        if verify:
            self.verify_periodicity()

    @property
    def verified(self) -> bool:
        return bool(self._verified)

    @property
    def direct_basis(self) -> np.ndarray:
        return self.supercell.direct_basis

    @property
    def reciprocal_basis(self) -> np.ndarray:
        return self.supercell.reciprocal_basis

    def displacement(self, points) -> np.ndarray:
        return self.field.displacement(points)

    def gradient(self, points, *, step: float = 1e-6) -> np.ndarray:
        return self.field.gradient(points, step=step)

    def verify_periodicity(self) -> dict[str, object]:
        # Use the complete perimeter of a deterministic fractional grid.  The
        # test is intentionally independent of the field's declared metadata.
        samples = np.linspace(0.0, 1.0, self.boundary_samples)
        basis = self.direct_basis
        probes = []
        for t in samples:
            probes.extend((t * basis[:, 0], t * basis[:, 1]))
        probes = np.asarray(probes, dtype=float)
        values = self.field.displacement(probes)
        residuals = []
        for shift in basis.T:
            residuals.append(np.max(np.linalg.norm(self.field.displacement(probes + shift) - values, axis=1)))
        max_residual = float(max(residuals))
        self._verification = {
            "verified": max_residual <= self.tolerance,
            "tolerance": self.tolerance,
            "boundary_samples": self.boundary_samples,
            "max_displacement_residual": max_residual,
            "translations": basis.T.tolist(),
        }
        self._verified = bool(self._verification["verified"])
        if not self._verified:
            raise PeriodicityError(
                "E_R5_SUPERCELL_BOUNDARY: declared supercell field is not continuous "
                f"on equivalent boundaries (max residual {max_residual:.3e} > {self.tolerance:.3e})"
            )
        return dict(self._verification)

    def require_verified(self) -> None:
        if not self.verified:
            raise PeriodicityError("E_R5_SUPERCELL_UNVERIFIED: supercell periodicity must pass verification before solver use")

    def metadata(self) -> dict[str, object]:
        return {
            "schema": "mephc.deformation_field.v1",
            "kind": "periodic_supercell",
            "capability": self.capability.value,
            "stable_identity": bool(self.field.stable_identity),
            "base_field": self.field.metadata(),
            "base_field_fingerprint": self.field.fingerprint(),
            "supercell": self.supercell.metadata(),
            "boundary_policy": {
                "tolerance": self.tolerance,
                "samples": self.boundary_samples,
                "verified": self.verified,
                "verification": self._verification,
            },
        }

    def require(self, operation: str, *, allow_supercell: bool = False) -> None:
        if not allow_supercell:
            super().require(operation, allow_supercell=False)
        self.require_verified()


def canonicalize_field(field=None) -> DeformationField:
    """Return the one canonical field authority for all downstream projects."""
    if field is None:
        return ZeroDeformationField()
    if isinstance(field, DeformationField):
        return field
    if isinstance(field, AffineTransform2D):
        if field.is_identity:
            return ZeroDeformationField()
        return ConstantAffineField(field)
    raise TypeError("field must be a DeformationField, AffineTransform2D, or None")


def affine_field(transform: AffineTransform2D | None = None) -> DeformationField:
    return canonicalize_field(transform or AffineTransform2D.identity())


def analytic_field(value, **kwargs) -> AnalyticDeformationField:
    return AnalyticDeformationField(value, **kwargs)


def sampled_field(origin, spacing, displacements, **kwargs) -> SampledDeformationField:
    return SampledDeformationField(origin, spacing, displacements, **kwargs)


def periodic_supercell_field(field, reference_lattice, replication_matrix=(1, 1), **kwargs) -> PeriodicSupercellField:
    return PeriodicSupercellField(field, reference_lattice, replication_matrix, **kwargs)


def validate_jacobian(field, points, *, min_determinant: float = 1e-8, max_condition: float = 1e8) -> dict[str, object]:
    """Validate local invertibility without turning small strain into physics."""
    field = canonicalize_field(field)
    probes = _points(points, allow_empty=False)
    values = field.deformation_gradient(probes)
    determinants = np.linalg.det(values)
    condition = np.asarray([np.linalg.cond(matrix) for matrix in values], dtype=float)
    if not np.all(np.isfinite(determinants)) or not np.all(np.isfinite(condition)):
        raise DeformationFieldError("E_R5_JACOBIAN_FINITE: deformation gradient is non-finite")
    if np.any(determinants <= float(min_determinant)):
        raise DeformationFieldError("E_R5_JACOBIAN_SINGULAR: local deformation gradient is singular or orientation reversing")
    if np.any(condition > float(max_condition)):
        raise DeformationFieldError("E_R5_JACOBIAN_CONDITION: local deformation gradient exceeds conditioning limit")
    return {
        "min_determinant": float(np.min(determinants)),
        "max_determinant": float(np.max(determinants)),
        "max_condition": float(np.max(condition)),
        "samples": int(len(probes)),
    }


# Friendly aliases used by downstream projects and external validation code.
ZeroField = ZeroDeformationField
ConstantAffineDeformationField = ConstantAffineField
AnalyticField = AnalyticDeformationField
SampledField = SampledDeformationField
SupercellField = PeriodicSupercellField


__all__ = [
    "AnalyticDeformationField", "AnalyticField", "ConstantAffineField",
    "ConstantAffineDeformationField", "DeformationCapability", "DeformationField",
    "DeformationFieldError", "PeriodicSupercellField", "PeriodicityError",
    "SampledDeformationField", "SampledField", "SemanticCapabilityError",
    "SupercellField", "SupercellLattice", "ZeroDeformationField", "ZeroField",
    "affine_field", "analytic_field", "canonicalize_field", "periodic_supercell_field",
    "sampled_field", "validate_jacobian",
]
