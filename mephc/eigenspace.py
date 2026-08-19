"""Solver-neutral raw eigenstates and finite-dimensional eigenspaces.

The raw solver index stored by :class:`RawEigenstate` is ordering metadata
only; it is not a physical identity.  :class:`EigenSubspace` is the
basis-independent candidate object for an eigenspace.  E1 deliberately does
not define branch tracking, physical state labels, transport, or Berry APIs.

This module has no Meep or MPB dependency so a future solver adapter can
populate the same objects without changing their semantics.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from collections.abc import Mapping
import math
from numbers import Real
from typing import Any, Iterable

import numpy as np


def _finite_real(value: Any, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite real scalar")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _numeric_array(value: Any, *, name: str, ndim: int) -> np.ndarray:
    try:
        array = np.asarray(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a numeric array") from exc
    if array.ndim != ndim:
        raise ValueError(f"{name} must have exactly {ndim} dimensions")
    if array.dtype.kind not in "iufc":
        raise ValueError(f"{name} must contain numeric values without coercion")
    if not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must contain only finite values")
    return array


def _normalize_k_point(value: Any) -> tuple[float, ...]:
    array = _numeric_array(value, name="k_point", ndim=1)
    if array.dtype.kind == "c":
        raise ValueError("k_point must contain real coordinates")
    if array.size < 1:
        raise ValueError("k_point must have at least one coordinate")
    return tuple(float(component) for component in array)


def _normalize_vector(value: Any, *, name: str = "vector") -> np.ndarray:
    array = _numeric_array(value, name=name, ndim=1)
    if array.size < 1:
        raise ValueError(f"{name} must not be empty")
    normalized = np.asarray(array, dtype=np.complex128).copy()
    norm = float(np.linalg.norm(normalized))
    if not math.isfinite(norm) or norm == 0.0:
        raise ValueError(f"{name} must have a finite nonzero norm")
    normalized /= norm
    normalized.setflags(write=False)
    return normalized


def _freeze_json(value: Any, *, path: str = "metadata") -> Any:
    if value is None or type(value) is bool or type(value) is str:
        return value
    if type(value) is int:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError(f"{path} contains a non-finite float")
        return value
    if isinstance(value, Mapping):
        frozen = {}
        for key, item in value.items():
            if type(key) is not str:
                raise ValueError(f"{path} mapping keys must be strings")
            frozen[key] = _freeze_json(item, path=f"{path}.{key}")
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item, path=f"{path}[]") for item in value)
    raise ValueError(f"{path} must contain only JSON-safe values")


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_json(value[key]) for key in sorted(value)}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _complex_pairs(vector: np.ndarray) -> list[list[float]]:
    return [[float(value.real), float(value.imag)] for value in vector]


@dataclass(frozen=True)
class RawEigenstate:
    """One normalized raw solver state.

    ``solver_index`` records raw solver ordering metadata only.  It is not a
    physical band identity, branch identity, or state label.
    """

    k_point: tuple[float, ...]
    solver_index: int
    eigenvalue: float
    vector: np.ndarray
    metadata: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "k_point", _normalize_k_point(self.k_point))
        if isinstance(self.solver_index, bool) or not isinstance(self.solver_index, int) or self.solver_index < 0:
            raise ValueError("solver_index must be a non-negative integer")
        object.__setattr__(self, "eigenvalue", _finite_real(self.eigenvalue, name="eigenvalue"))
        object.__setattr__(self, "vector", _normalize_vector(self.vector))
        frozen_metadata = _freeze_json(self.metadata)
        if not isinstance(frozen_metadata, Mapping):
            raise ValueError("metadata must be a JSON-safe mapping")
        object.__setattr__(self, "metadata", frozen_metadata)

    @property
    def dimension(self) -> int:
        return int(self.vector.size)

    def to_dict(self, *, include_vector: bool = False) -> dict[str, Any]:
        result = {
            "k_point": list(self.k_point),
            "solver_index": self.solver_index,
            "eigenvalue": self.eigenvalue,
            "metadata": _thaw_json(self.metadata),
        }
        if include_vector:
            result["vector"] = _complex_pairs(self.vector)
        return result


def _canonical_frame(value: Any) -> np.ndarray:
    array = _numeric_array(value, name="frame", ndim=2)
    ambient, dimension = array.shape
    if ambient < 1 or dimension < 1:
        raise ValueError("frame must have positive ambient and subspace dimensions")
    if dimension > ambient:
        raise ValueError("subspace dimension cannot exceed ambient dimension")
    matrix = np.asarray(array, dtype=np.complex128)
    if np.linalg.matrix_rank(matrix) != dimension:
        raise ValueError("frame columns are rank deficient")
    q, _ = np.linalg.qr(matrix, mode="reduced")
    q = np.asarray(q, dtype=np.complex128)
    for column in range(dimension):
        magnitudes = np.abs(q[:, column])
        pivot = int(np.argmax(magnitudes))
        pivot_value = q[pivot, column]
        if abs(pivot_value) > 0.0:
            q[:, column] *= np.conj(pivot_value) / abs(pivot_value)
    q.setflags(write=False)
    return q


@dataclass(frozen=True)
class EigenSubspace:
    """A canonical orthonormal frame and its basis-independent projector."""

    k_point: tuple[float, ...]
    frame: np.ndarray
    eigenvalues: tuple[float, ...]
    solver_indices: tuple[int, ...]
    metadata: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "k_point", _normalize_k_point(self.k_point))
        canonical = _canonical_frame(self.frame)
        object.__setattr__(self, "frame", canonical)
        dimension = canonical.shape[1]
        try:
            eigenvalues = tuple(self.eigenvalues)
            solver_indices = tuple(self.solver_indices)
        except TypeError as exc:
            raise ValueError("eigenvalues and solver_indices must be iterable") from exc
        if len(eigenvalues) != dimension:
            raise ValueError("eigenvalues length must equal subspace dimension")
        if len(solver_indices) != dimension:
            raise ValueError("solver_indices length must equal subspace dimension")
        object.__setattr__(self, "eigenvalues", tuple(
            _finite_real(value, name="eigenvalue") for value in eigenvalues
        ))
        for value in solver_indices:
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError("solver_indices must contain non-negative integers")
        object.__setattr__(self, "solver_indices", solver_indices)
        frozen_metadata = _freeze_json(self.metadata)
        if not isinstance(frozen_metadata, Mapping):
            raise ValueError("metadata must be a JSON-safe mapping")
        object.__setattr__(self, "metadata", frozen_metadata)

    @property
    def ambient_dimension(self) -> int:
        return int(self.frame.shape[0])

    @property
    def dimension(self) -> int:
        return int(self.frame.shape[1])

    @classmethod
    def from_states(cls, states: Iterable[RawEigenstate]) -> "EigenSubspace":
        states = tuple(states)
        if not states:
            raise ValueError("at least one RawEigenstate is required")
        if any(not isinstance(state, RawEigenstate) for state in states):
            raise TypeError("states must contain RawEigenstate values")
        k_point = states[0].k_point
        if any(state.k_point != k_point for state in states[1:]):
            raise ValueError("all states must have exactly equal k_point values")
        ambient = states[0].dimension
        if any(state.dimension != ambient for state in states[1:]):
            raise ValueError("all states must have equal vector dimensions")
        metadata = {
            "source": "RawEigenstate.from_states",
            "state_metadata": [_thaw_json(state.metadata) for state in states],
        }
        return cls(
            k_point=k_point,
            frame=np.column_stack([state.vector for state in states]),
            eigenvalues=tuple(state.eigenvalue for state in states),
            solver_indices=tuple(state.solver_index for state in states),
            metadata=metadata,
        )

    def project(self, vector: Any) -> np.ndarray:
        candidate = _numeric_array(vector, name="vector", ndim=1)
        if candidate.size != self.ambient_dimension:
            raise ValueError("vector dimension must equal ambient dimension")
        candidate = np.asarray(candidate, dtype=np.complex128)
        return self.frame @ (self.frame.conj().T @ candidate)

    def projector_matrix(self) -> np.ndarray:
        """Materialize the dense projector for toy and validation dimensions."""
        return self.frame @ self.frame.conj().T

    def contains(self, vector: Any, *, atol: float = 1e-10) -> bool:
        tolerance = _finite_real(atol, name="atol")
        if tolerance < 0.0:
            raise ValueError("atol must be non-negative")
        candidate = _numeric_array(vector, name="vector", ndim=1)
        if candidate.size != self.ambient_dimension:
            raise ValueError("vector dimension must equal ambient dimension")
        candidate = np.asarray(candidate, dtype=np.complex128)
        return bool(np.linalg.norm(candidate - self.project(candidate)) <= tolerance)

    def projector_distance(self, other: "EigenSubspace") -> float:
        if not isinstance(other, EigenSubspace):
            raise TypeError("other must be EigenSubspace")
        if self.ambient_dimension != other.ambient_dimension:
            raise ValueError("projector distance requires equal ambient dimensions")
        if self.k_point != other.k_point:
            raise ValueError("projector distance requires exactly compatible k_point values")
        return float(np.linalg.norm(self.projector_matrix() - other.projector_matrix(), ord="fro"))

    def to_dict(self, *, include_frame: bool = False) -> dict[str, Any]:
        result = {
            "k_point": list(self.k_point),
            "ambient_dimension": self.ambient_dimension,
            "dimension": self.dimension,
            "eigenvalues": list(self.eigenvalues),
            "solver_indices": list(self.solver_indices),
            "metadata": _thaw_json(self.metadata),
        }
        if include_frame:
            result["frame"] = [_complex_pairs(row) for row in self.frame]
        return result


__all__ = ["RawEigenstate", "EigenSubspace"]
