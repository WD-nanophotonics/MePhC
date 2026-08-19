"""Solver-neutral subspace overlap and one-link polar transport.

The overlap convention is ``M_LR = Q_L.conj().T @ Q_R``.  Singular values
and principal angles are gauge invariant.  E2 ends at one directed link
between two subspaces; it does not implement branch tracking, Wilson loops,
Berry quantities, symmetry labels, or solver-specific metrics.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from numbers import Real
from typing import Any

import numpy as np

from .eigenspace import EigenSubspace


DEFAULT_VALIDATION_TOLERANCE = 1e-10


class SubspaceTransportError(ValueError):
    """Raised when a unique qualified polar transport link cannot be formed."""


def _finite_real(value: Any, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite real scalar")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _tolerance(value: Any, *, name: str, positive: bool = False) -> float:
    result = _finite_real(value, name=name)
    if result < 0.0 or (positive and result == 0.0):
        qualifier = "positive" if positive else "non-negative"
        raise ValueError(f"{name} must be {qualifier}")
    return result


def _complex_array(value: Any, *, name: str, ndim: int) -> np.ndarray:
    try:
        array = np.asarray(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a numeric array") from exc
    if array.ndim != ndim or array.dtype.kind not in "iufc":
        raise ValueError(f"{name} must be a numeric array with {ndim} dimensions")
    result = np.asarray(array, dtype=np.complex128).copy()
    if not np.all(np.isfinite(result)):
        raise ValueError(f"{name} must contain only finite values")
    return result


def _read_only(array: Any, *, name: str, shape: tuple[int, ...] | None = None) -> np.ndarray:
    result = _complex_array(array, name=name, ndim=len(np.shape(array)))
    if shape is not None and result.shape != shape:
        raise ValueError(f"{name} has shape {result.shape}; expected {shape}")
    result.setflags(write=False)
    return result


def _pairs(matrix: np.ndarray) -> list[list[list[float]]]:
    return [
        [[float(value.real), float(value.imag)] for value in row]
        for row in matrix
    ]


def _vector_pairs(vector: np.ndarray) -> list[list[float]]:
    return [[float(value.real), float(value.imag)] for value in vector]


def _validate_subspaces(left: EigenSubspace, right: EigenSubspace) -> None:
    if not isinstance(left, EigenSubspace) or not isinstance(right, EigenSubspace):
        raise TypeError("left and right must be EigenSubspace values")
    if left.ambient_dimension != right.ambient_dimension:
        raise ValueError("subspaces must have equal ambient dimensions")


@dataclass(frozen=True)
class SubspaceOverlap:
    """Overlap data for ``M_LR = Q_L^dagger Q_R``.

    SVD singular values are stored in descending order; principal angles are
    therefore in ascending order.  Unequal subspace dimensions are valid for
    plain overlap and do not imply an invertible transport map.
    """

    left_k_point: tuple[float, ...]
    right_k_point: tuple[float, ...]
    left_dimension: int
    right_dimension: int
    ambient_dimension: int
    matrix: np.ndarray
    singular_values: np.ndarray
    principal_angles: np.ndarray

    def __post_init__(self) -> None:
        for name, value in (("left_dimension", self.left_dimension), ("right_dimension", self.right_dimension), ("ambient_dimension", self.ambient_dimension)):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if self.left_dimension > self.ambient_dimension or self.right_dimension > self.ambient_dimension:
            raise ValueError("subspace dimensions cannot exceed ambient dimension")
        matrix = _read_only(
            self.matrix,
            name="matrix",
            shape=(self.left_dimension, self.right_dimension),
        )
        singular_values = np.asarray(self.singular_values, dtype=float).copy()
        principal_angles = np.asarray(self.principal_angles, dtype=float).copy()
        expected = min(self.left_dimension, self.right_dimension)
        if singular_values.ndim != 1 or singular_values.size != expected:
            raise ValueError("singular_values must have min(N_L, N_R) entries")
        if principal_angles.ndim != 1 or principal_angles.size != expected:
            raise ValueError("principal_angles must have min(N_L, N_R) entries")
        if not np.all(np.isfinite(singular_values)) or not np.all(np.isfinite(principal_angles)):
            raise ValueError("singular_values and principal_angles must be finite")
        if np.any(singular_values < 0.0) or np.any(singular_values > 1.0 + DEFAULT_VALIDATION_TOLERANCE):
            raise SubspaceTransportError("singular values violate orthonormal-frame bounds")
        singular_values.setflags(write=False)
        principal_angles.setflags(write=False)
        object.__setattr__(self, "matrix", matrix)
        object.__setattr__(self, "singular_values", singular_values)
        object.__setattr__(self, "principal_angles", principal_angles)

    @property
    def min_singular_value(self) -> float:
        return float(np.min(self.singular_values))

    @property
    def max_principal_angle(self) -> float:
        return float(np.max(self.principal_angles))

    @property
    def is_equal_dimension(self) -> bool:
        return self.left_dimension == self.right_dimension

    def to_dict(self, *, include_matrix: bool = False) -> dict[str, Any]:
        result = {
            "left_k_point": list(self.left_k_point),
            "right_k_point": list(self.right_k_point),
            "left_dimension": self.left_dimension,
            "right_dimension": self.right_dimension,
            "ambient_dimension": self.ambient_dimension,
            "singular_values": [float(value) for value in self.singular_values],
            "principal_angles": [float(value) for value in self.principal_angles],
        }
        if include_matrix:
            result["matrix"] = _pairs(self.matrix)
        return result


def subspace_overlap(
    left: EigenSubspace,
    right: EigenSubspace,
    *,
    validation_tolerance: float = DEFAULT_VALIDATION_TOLERANCE,
) -> SubspaceOverlap:
    """Compute ``M_LR = Q_L^dagger Q_R`` without using solver metadata."""
    tolerance = _tolerance(validation_tolerance, name="validation_tolerance")
    _validate_subspaces(left, right)
    matrix = np.asarray(left.frame.conj().T @ right.frame, dtype=np.complex128)
    if not np.all(np.isfinite(matrix)):
        raise SubspaceTransportError("overlap matrix is not finite")
    singular_values = np.linalg.svd(matrix, compute_uv=False)
    if np.any(singular_values > 1.0 + tolerance):
        raise SubspaceTransportError("overlap singular value exceeds orthonormal-frame bound")
    principal_angles = np.arccos(np.clip(singular_values, 0.0, 1.0))
    return SubspaceOverlap(
        left_k_point=left.k_point,
        right_k_point=right.k_point,
        left_dimension=left.dimension,
        right_dimension=right.dimension,
        ambient_dimension=left.ambient_dimension,
        matrix=matrix,
        singular_values=singular_values,
        principal_angles=principal_angles,
    )


@dataclass(frozen=True)
class SubspaceTransportLink:
    """One directed SVD-polar unitary link between equal-dimensional subspaces."""

    left_k_point: tuple[float, ...]
    right_k_point: tuple[float, ...]
    dimension: int
    overlap: np.ndarray
    unitary: np.ndarray
    min_singular_value: float
    condition_number: float
    unitarity_residual: float

    def __post_init__(self) -> None:
        if isinstance(self.dimension, bool) or not isinstance(self.dimension, int) or self.dimension < 1:
            raise ValueError("dimension must be a positive integer")
        shape = (self.dimension, self.dimension)
        object.__setattr__(self, "overlap", _read_only(self.overlap, name="overlap", shape=shape))
        object.__setattr__(self, "unitary", _read_only(self.unitary, name="unitary", shape=shape))
        minimum = _finite_real(self.min_singular_value, name="min_singular_value")
        condition = _finite_real(self.condition_number, name="condition_number")
        residual = _finite_real(self.unitarity_residual, name="unitarity_residual")
        if minimum <= 0.0 or condition < 1.0 or residual < 0.0:
            raise ValueError("transport diagnostics have invalid values")
        object.__setattr__(self, "min_singular_value", minimum)
        object.__setattr__(self, "condition_number", condition)
        object.__setattr__(self, "unitarity_residual", residual)

    def aligned_right_frame(self, right: EigenSubspace) -> np.ndarray:
        """Return ``Q_R @ unitary^dagger``; this is not branch assignment."""
        if not isinstance(right, EigenSubspace):
            raise TypeError("right must be EigenSubspace")
        if right.k_point != self.right_k_point:
            raise ValueError("right k_point does not match this transport link")
        if right.dimension != self.dimension:
            raise ValueError("right subspace dimensions do not match this transport link")
        aligned = np.asarray(right.frame @ self.unitary.conj().T, dtype=np.complex128)
        aligned.setflags(write=False)
        return aligned

    def to_dict(self, *, include_matrices: bool = False) -> dict[str, Any]:
        result = {
            "left_k_point": list(self.left_k_point),
            "right_k_point": list(self.right_k_point),
            "dimension": self.dimension,
            "min_singular_value": self.min_singular_value,
            "condition_number": self.condition_number,
            "unitarity_residual": self.unitarity_residual,
        }
        if include_matrices:
            result["overlap"] = _pairs(self.overlap)
            result["unitary"] = _pairs(self.unitary)
        return result


def parallel_transport_link(
    left: EigenSubspace,
    right: EigenSubspace,
    *,
    min_singular_value: float = 1e-12,
    validation_tolerance: float = DEFAULT_VALIDATION_TOLERANCE,
) -> SubspaceTransportLink:
    """Return the SVD-polar link ``U @ Vh`` for ``M=U Sigma Vh``.

    The link is defined only for equal-dimensional, nonsingular overlaps.
    """
    threshold = _tolerance(min_singular_value, name="min_singular_value", positive=True)
    tolerance = _tolerance(validation_tolerance, name="validation_tolerance")
    _validate_subspaces(left, right)
    if left.dimension != right.dimension:
        raise SubspaceTransportError("parallel transport requires equal subspace dimensions")
    overlap = subspace_overlap(left, right, validation_tolerance=tolerance)
    matrix = overlap.matrix
    u, singular_values, vh = np.linalg.svd(matrix, full_matrices=False)
    smallest = float(singular_values[-1])
    if smallest < threshold:
        raise SubspaceTransportError(
            f"overlap is singular below the minimum singular-value threshold: {smallest} < {threshold}"
        )
    unitary = np.asarray(u @ vh, dtype=np.complex128)
    residual = float(np.linalg.norm(unitary.conj().T @ unitary - np.eye(left.dimension), ord="fro"))
    if not math.isfinite(residual) or residual > tolerance:
        raise SubspaceTransportError("SVD-polar factor failed the configured unitarity tolerance")
    condition = float(singular_values[0] / smallest)
    return SubspaceTransportLink(
        left_k_point=left.k_point,
        right_k_point=right.k_point,
        dimension=left.dimension,
        overlap=matrix,
        unitary=unitary,
        min_singular_value=smallest,
        condition_number=condition,
        unitarity_residual=residual,
    )


__all__ = [
    "DEFAULT_VALIDATION_TOLERANCE",
    "SubspaceTransportError",
    "SubspaceOverlap",
    "subspace_overlap",
    "SubspaceTransportLink",
    "parallel_transport_link",
]
