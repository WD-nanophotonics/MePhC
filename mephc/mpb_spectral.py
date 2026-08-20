"""MPB periodic H-envelope representation adapter.

This module accepts explicit periodic H-envelope arrays only. It does not
import or run MPB and does not authorize Berry, Wilson, Chern, observable,
backend, or production calculations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Mapping, Sequence
import math
from types import MappingProxyType
from typing import Any, Iterator

import numpy as np

from .eigenspace import RawEigenstate


MPB_H_ENVELOPE_REPRESENTATION = "mpb_periodic_h_l2_v1"
MPB_H_ENVELOPE_QUALIFIED = "MPB_H_ENVELOPE_QUALIFIED"
MPB_H_ENVELOPE_UNQUALIFIED = "MPB_H_ENVELOPE_UNQUALIFIED"
MPB_H_ORTHOGONAL_QUALIFIED = MPB_H_ENVELOPE_QUALIFIED
MPB_H_ORTHOGONAL_UNQUALIFIED = MPB_H_ENVELOPE_UNQUALIFIED
_LIVE_PROVENANCE_TOKEN = object()


def _finite(value: Any, *, name: str, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, np.integer, np.floating)):
        raise ValueError(f"{name} must be a finite real scalar")
    result = float(value)
    if not math.isfinite(result) or (positive and result <= 0.0) or (not positive and result < 0.0):
        qualifier = "positive" if positive else "non-negative"
        raise ValueError(f"{name} must be {qualifier} and finite")
    return result


def _json_freeze(value: Any, *, path: str = "provenance") -> Any:
    if value is None or type(value) in {bool, str, int}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError(f"{path} contains a non-finite float")
        return value
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _json_freeze(item, path=f"{path}.{key}") for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_json_freeze(item, path=f"{path}[]") for item in value)
    raise ValueError(f"{path} must contain JSON-safe values")


def _json_thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_json_thaw(item) for item in value]
    return value


def _numeric(value: Any, *, name: str, ndim: int) -> np.ndarray:
    try:
        array = np.asarray(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if array.ndim != ndim or array.dtype.kind not in "iufc":
        raise ValueError(f"{name} must be a numeric array with {ndim} dimensions")
    if not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must contain only finite values")
    return array


def _real_vector(value: Any, *, name: str) -> np.ndarray:
    array = _numeric(value, name=name, ndim=1)
    if array.dtype.kind == "c":
        raise ValueError(f"{name} must contain real values")
    if array.size == 0:
        raise ValueError(f"{name} must not be empty")
    return np.asarray(array, dtype=float)


def _k_point(value: Any, *, name: str) -> tuple[float, ...]:
    array = _real_vector(value, name=name)
    return tuple(float(item) for item in array)


def _readonly(value: Any, *, dtype: Any, name: str, ndim: int | None = None) -> np.ndarray:
    array = np.asarray(value, dtype=dtype)
    if ndim is not None and array.ndim != ndim:
        raise ValueError(f"{name} has invalid dimensionality")
    if not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must contain only finite values")
    result = np.array(array, copy=True)
    result.setflags(write=False)
    return result


def _complex_pairs(array: np.ndarray) -> list[Any]:
    if array.ndim == 1:
        return [[float(item.real), float(item.imag)] for item in array]
    return [_complex_pairs(row) for row in array]


def _real_matrix(array: np.ndarray) -> list[list[float]]:
    return [[float(item) for item in row] for row in array]


def _base_provenance(
    *,
    spatial_shape: tuple[int, int],
    mpb_k_point: tuple[float, ...] | None,
    provenance: Mapping[str, Any] | None,
    live_mpb_extraction_validated: bool = False,
) -> Mapping[str, Any]:
    if provenance is not None and not isinstance(provenance, Mapping):
        raise TypeError("provenance must be a mapping or None")
    data = {
        "representation": MPB_H_ENVELOPE_REPRESENTATION,
        "spatial_shape": list(spatial_shape),
        "component_count": 3,
        "flattening_order": "C",
        "component_order": "supplied final axis order",
        "normalization_convention": "per-band H-space discrete L2 norm",
        "metric": "sum(conj(H1) * H2) over x y and vector component",
        "periodic_h_envelope": True,
        "bloch_phase_excluded": True,
        "solver_index_semantics": "ordering metadata only",
        "live_mpb_extraction_validated": bool(live_mpb_extraction_validated),
        "mpb_k_point": None if mpb_k_point is None else list(mpb_k_point),
        "caller_provenance": {} if provenance is None else dict(provenance),
    }
    return _json_freeze(data)


@dataclass(frozen=True)
class MPBHEnvelopeSnapshot:
    """Immutable evidence and RawEigenstate view for one explicit H batch."""

    k_point: tuple[float, ...]
    frequencies: np.ndarray
    h_fields: np.ndarray
    raw_norms: np.ndarray
    normalized_vectors: tuple[np.ndarray, ...]
    gram_matrix: np.ndarray
    max_normalization_error: float
    max_off_diagonal_gram: float
    orthogonality_status: str
    normalization_tolerance: float
    orthogonality_tolerance: float
    raw_eigenstates: tuple[RawEigenstate, ...]
    provenance: Mapping[str, Any] = field(default_factory=dict)
    e_fields: np.ndarray | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "k_point", _k_point(self.k_point, name="k_point"))
        fields = _readonly(self.h_fields, dtype=np.complex128, name="h_fields", ndim=4)
        electric = None if self.e_fields is None else _readonly(self.e_fields, dtype=np.complex128, name="e_fields", ndim=4)
        if electric is not None and electric.shape != fields.shape:
            raise ValueError("e_fields must have the same shape as h_fields")
        if fields.shape[0] < 1 or fields.shape[1] < 1 or fields.shape[2] < 1 or fields.shape[3] != 3:
            raise ValueError("h_fields must have shape (bands, nx, ny, 3) with positive dimensions")
        frequencies = _readonly(self.frequencies, dtype=float, name="frequencies", ndim=1)
        if frequencies.size != fields.shape[0]:
            raise ValueError("frequencies length must match h_fields band count")
        raw_norms = _readonly(self.raw_norms, dtype=float, name="raw_norms", ndim=1)
        if raw_norms.size != fields.shape[0] or np.any(raw_norms <= 0.0):
            raise ValueError("raw_norms must contain one positive norm per band")
        vectors = tuple(_readonly(vector, dtype=np.complex128, name="normalized_vector", ndim=1) for vector in self.normalized_vectors)
        if len(vectors) != fields.shape[0]:
            raise ValueError("normalized_vectors length must match h_fields band count")
        flat_size = int(np.prod(fields.shape[1:])) * (2 if electric is not None else 1)
        if any(vector.size != flat_size for vector in vectors):
            raise ValueError("normalized_vectors have inconsistent flattened size")
        gram = _readonly(self.gram_matrix, dtype=np.complex128, name="gram_matrix", ndim=2)
        if gram.shape != (fields.shape[0], fields.shape[0]):
            raise ValueError("gram_matrix must be square with one row per band")
        if self.orthogonality_status not in {MPB_H_ENVELOPE_QUALIFIED, MPB_H_ENVELOPE_UNQUALIFIED}:
            raise ValueError("invalid orthogonality status")
        norm_tolerance = _finite(self.normalization_tolerance, name="normalization_tolerance", positive=True)
        orthogonality_tolerance = _finite(self.orthogonality_tolerance, name="orthogonality_tolerance")
        norm_error = _finite(self.max_normalization_error, name="max_normalization_error")
        off_diagonal = _finite(self.max_off_diagonal_gram, name="max_off_diagonal_gram")
        if norm_error < 0.0 or off_diagonal < 0.0:
            raise ValueError("diagnostic magnitudes must be non-negative")
        states = tuple(self.raw_eigenstates)
        if len(states) != fields.shape[0] or any(not isinstance(state, RawEigenstate) for state in states):
            raise ValueError("raw_eigenstates must contain one RawEigenstate per band")
        if any(state.k_point != self.k_point for state in states):
            raise ValueError("raw_eigenstates must preserve k_point")
        if any(state.vector.size != flat_size for state in states):
            raise ValueError("raw_eigenstates have inconsistent vector size")
        object.__setattr__(self, "frequencies", frequencies)
        object.__setattr__(self, "h_fields", fields)
        object.__setattr__(self, "e_fields", electric)
        object.__setattr__(self, "raw_norms", raw_norms)
        object.__setattr__(self, "normalized_vectors", vectors)
        object.__setattr__(self, "gram_matrix", gram)
        object.__setattr__(self, "max_normalization_error", norm_error)
        object.__setattr__(self, "max_off_diagonal_gram", off_diagonal)
        object.__setattr__(self, "normalization_tolerance", norm_tolerance)
        object.__setattr__(self, "orthogonality_tolerance", orthogonality_tolerance)
        object.__setattr__(self, "raw_eigenstates", states)
        object.__setattr__(self, "provenance", _json_freeze(dict(self.provenance)))

    @property
    def bands(self) -> int:
        return int(self.h_fields.shape[0])

    @property
    def spatial_shape(self) -> tuple[int, int]:
        return (int(self.h_fields.shape[1]), int(self.h_fields.shape[2]))

    @property
    def component_count(self) -> int:
        return 3

    @property
    def status(self) -> str:
        return self.orthogonality_status

    @property
    def is_orthogonality_qualified(self) -> bool:
        return self.orthogonality_status == MPB_H_ENVELOPE_QUALIFIED

    @property
    def is_qualified(self) -> bool:
        return self.is_orthogonality_qualified

    @property
    def states(self) -> tuple[RawEigenstate, ...]:
        return self.raw_eigenstates

    @property
    def raw_states(self) -> tuple[RawEigenstate, ...]:
        return self.raw_eigenstates

    def __iter__(self) -> Iterator[RawEigenstate]:
        return iter(self.raw_eigenstates)

    def __len__(self) -> int:
        return len(self.raw_eigenstates)

    def __getitem__(self, index: int) -> RawEigenstate:
        return self.raw_eigenstates[index]

    def to_raw_eigenstates(self) -> tuple[RawEigenstate, ...]:
        return self.raw_eigenstates

    def to_dict(self, *, include_h_fields: bool = False, include_vectors: bool = False) -> dict[str, Any]:
        result = {
            "k_point": list(self.k_point),
            "frequencies": [float(value) for value in self.frequencies],
            "spatial_shape": list(self.spatial_shape),
            "component_count": self.component_count,
            "raw_norms": [float(value) for value in self.raw_norms],
            "gram_matrix": _complex_pairs(self.gram_matrix),
            "max_normalization_error": self.max_normalization_error,
            "max_off_diagonal_gram": self.max_off_diagonal_gram,
            "orthogonality_status": self.orthogonality_status,
            "is_orthogonality_qualified": self.is_orthogonality_qualified,
            "normalization_tolerance": self.normalization_tolerance,
            "orthogonality_tolerance": self.orthogonality_tolerance,
            "raw_eigenstates": [state.to_dict(include_vector=include_vectors) for state in self.raw_eigenstates],
            "provenance": _json_thaw(self.provenance),
        }
        if include_h_fields:
            result["h_fields"] = _complex_pairs(self.h_fields)
            if self.e_fields is not None:
                result["e_fields"] = _complex_pairs(self.e_fields)
        return result


def adapt_mpb_h_envelopes(
    k_point: Sequence[float],
    frequencies: Sequence[float],
    h_fields: Any,
    *,
    mpb_k_point: Sequence[float] | None = None,
    norm_tolerance: float = 1e-14,
    orthogonality_tolerance: float = 1e-10,
    provenance: Mapping[str, Any] | None = None,
    _trusted_live_provenance: Any = None,
) -> MPBHEnvelopeSnapshot:
    """Convert explicit periodic H envelopes into ordered RawEigenstate values.

    The input shape is exactly (bands, nx, ny, 3). Each band is flattened in
    C order and normalized independently using the discrete H-space L2 metric.
    No cross-band orthogonalization, phase fixing, reordering, or mixing occurs.
    """
    normalized_k_point = _k_point(k_point, name="k_point")
    normalized_mpb_k_point = None if mpb_k_point is None else _k_point(mpb_k_point, name="mpb_k_point")
    norm_tolerance = _finite(norm_tolerance, name="norm_tolerance", positive=True)
    orthogonality_tolerance = _finite(orthogonality_tolerance, name="orthogonality_tolerance")
    if _trusted_live_provenance is not None and _trusted_live_provenance is not _LIVE_PROVENANCE_TOKEN:
        raise ValueError("trusted live provenance is reserved for the live provider")
    trusted_live_provenance = _trusted_live_provenance is _LIVE_PROVENANCE_TOKEN
    fields_input = _numeric(h_fields, name="h_fields", ndim=4)
    if fields_input.shape[0] < 1 or fields_input.shape[1] < 1 or fields_input.shape[2] < 1 or fields_input.shape[3] != 3:
        raise ValueError("h_fields must have shape (bands, nx, ny, 3) with positive dimensions")
    fields = np.asarray(fields_input, dtype=np.complex128)
    frequency_array = _real_vector(frequencies, name="frequencies")
    if frequency_array.size != fields.shape[0]:
        raise ValueError("frequencies length must match h_fields band count")

    vectors = []
    norms = []
    for index in range(fields.shape[0]):
        vector = np.array(fields[index].reshape(-1, order="C"), dtype=np.complex128, copy=True)
        norm = float(np.sqrt(np.vdot(vector, vector).real))
        if not math.isfinite(norm) or norm <= norm_tolerance:
            raise ValueError(f"h_fields band {index} has a norm at or below norm_tolerance")
        vector /= norm
        vector.setflags(write=False)
        vectors.append(vector)
        norms.append(norm)
    normalized_vectors = tuple(vectors)
    matrix = np.column_stack(normalized_vectors)
    gram = np.asarray(matrix.conj().T @ matrix, dtype=np.complex128)
    gram.setflags(write=False)
    normalization_errors = [abs(float(np.vdot(vector, vector).real) - 1.0) for vector in normalized_vectors]
    max_normalization_error = float(max(normalization_errors))
    off_diagonal = np.array(gram, copy=True)
    np.fill_diagonal(off_diagonal, 0.0)
    max_off_diagonal_gram = float(np.max(np.abs(off_diagonal)))
    status = (
        MPB_H_ENVELOPE_QUALIFIED
        if max_normalization_error <= orthogonality_tolerance and max_off_diagonal_gram <= orthogonality_tolerance
        else MPB_H_ENVELOPE_UNQUALIFIED
    )
    frozen_provenance = _base_provenance(
        spatial_shape=(fields.shape[1], fields.shape[2]),
        mpb_k_point=normalized_mpb_k_point,
        provenance=provenance,
        live_mpb_extraction_validated=trusted_live_provenance,
    )
    state_metadata = {
        "representation": MPB_H_ENVELOPE_REPRESENTATION,
        "spatial_shape": [int(fields.shape[1]), int(fields.shape[2])],
        "component_count": 3,
        "flattening_order": "C",
        "component_order": "supplied final axis order",
        "normalization_convention": "per-band H-space discrete L2 norm",
        "metric": "sum(conj(H1) * H2) over x y and vector component",
        "periodic_h_envelope": True,
        "bloch_phase_excluded": True,
        "live_mpb_extraction_validated": False,
        "solver_index_semantics": "ordering metadata only",
        "batch_orthogonality_status": status,
        "batch_max_off_diagonal_gram": max_off_diagonal_gram,
        "batch_max_normalization_error": max_normalization_error,
        "representation_provenance": _json_thaw(frozen_provenance),
    }
    states = tuple(
        RawEigenstate(
            k_point=normalized_k_point,
            solver_index=index,
            eigenvalue=float(frequency_array[index]),
            vector=vector,
            metadata=state_metadata,
        )
        for index, vector in enumerate(normalized_vectors)
    )
    return MPBHEnvelopeSnapshot(
        k_point=normalized_k_point,
        frequencies=frequency_array,
        h_fields=fields,
        raw_norms=np.asarray(norms, dtype=float),
        normalized_vectors=normalized_vectors,
        gram_matrix=gram,
        max_normalization_error=max_normalization_error,
        max_off_diagonal_gram=max_off_diagonal_gram,
        orthogonality_status=status,
        normalization_tolerance=norm_tolerance,
        orthogonality_tolerance=orthogonality_tolerance,
        raw_eigenstates=states,
        provenance=frozen_provenance,
    )


adapt_mpb_h_envelopes_to_raw_eigenstates = adapt_mpb_h_envelopes

__all__ = [
    "MPB_H_ENVELOPE_REPRESENTATION",
    "MPB_H_ENVELOPE_QUALIFIED",
    "MPB_H_ENVELOPE_UNQUALIFIED",
    "MPB_H_ORTHOGONAL_QUALIFIED",
    "MPB_H_ORTHOGONAL_UNQUALIFIED",
    "MPBHEnvelopeSnapshot",
    "adapt_mpb_h_envelopes",
    "adapt_mpb_h_envelopes_to_raw_eigenstates",
]
