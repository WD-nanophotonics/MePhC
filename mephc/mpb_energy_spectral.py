"""Explicit periodic Maxwell E+H envelope representation for MPB states.

This additive adapter is deliberately distinct from the existing H-only
representation.  For nondispersive mu=1 media its state vector is
``(sqrt(epsilon) * E, H)`` with the uniform discrete cell quadrature, so its
ordinary vector inner product is the electromagnetic energy inner product.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
import math
from typing import Any

import numpy as np

from .eigenspace import RawEigenstate
from .mpb_spectral import (
    MPB_H_ENVELOPE_QUALIFIED,
    MPB_H_ENVELOPE_UNQUALIFIED,
    MPBHEnvelopeSnapshot,
    _LIVE_PROVENANCE_TOKEN,
)

MPB_ENERGY_EH_REPRESENTATION = "mpb_energy_eh_v1"


def _numeric_fields(value: Any, *, name: str) -> np.ndarray:
    array = np.asarray(value)
    if array.ndim != 4 or array.shape[0] < 1 or array.shape[1] < 1 or array.shape[2] < 1 or array.shape[3] != 3:
        raise ValueError(f"{name} must have shape (bands, nx, ny, 3)")
    if array.dtype.kind not in "iufc" or not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must be finite numeric data")
    return np.asarray(array, dtype=np.complex128)


def _epsilon(value: Any, *, shape: tuple[int, int]) -> np.ndarray:
    array = np.asarray(value)
    if array.shape == shape + (1,):
        array = array[:, :, 0]
    if array.shape != shape or array.dtype.kind not in "iuf" or not np.all(np.isfinite(array)):
        raise ValueError("epsilon must be finite real data with shape (nx, ny)")
    array = np.asarray(array, dtype=float)
    if np.any(array <= 0.0):
        raise ValueError("epsilon must be strictly positive")
    return array


def _k_point(value: Any) -> tuple[float, ...]:
    array = np.asarray(value)
    if array.ndim != 1 or array.size < 1 or array.dtype.kind not in "iuf" or not np.all(np.isfinite(array)):
        raise ValueError("k_point must be a finite real vector")
    return tuple(float(item) for item in array)


def _frequencies(value: Any, bands: int) -> np.ndarray:
    array = np.asarray(value)
    if array.ndim != 1 or array.size != bands or array.dtype.kind not in "iuf" or not np.all(np.isfinite(array)):
        raise ValueError("frequencies must match the number of bands")
    return np.asarray(array, dtype=float)


def adapt_mpb_energy_eh_envelopes(
    k_point: Sequence[float],
    frequencies: Sequence[float],
    e_fields: Any,
    h_fields: Any,
    epsilon: Any,
    *,
    mpb_k_point: Sequence[float] | None = None,
    norm_tolerance: float = 1e-14,
    orthogonality_tolerance: float = 1e-10,
    provenance: Mapping[str, Any] | None = None,
    _trusted_live_provenance: Any = None,
) -> MPBHEnvelopeSnapshot:
    """Adapt explicit periodic E/H envelopes using the full energy metric.

    The discrete norm is ``sum(epsilon*|E|^2 + |H|^2)`` over grid cells and
    vector components.  The common cell-volume factor is omitted because it
    cancels in normalized overlaps.
    """
    e = _numeric_fields(e_fields, name="e_fields")
    h = _numeric_fields(h_fields, name="h_fields")
    if e.shape != h.shape:
        raise ValueError("e_fields and h_fields must have identical shapes")
    eps = _epsilon(epsilon, shape=(e.shape[1], e.shape[2]))
    k = _k_point(k_point)
    mpb_k = None if mpb_k_point is None else _k_point(mpb_k_point)
    freq = _frequencies(frequencies, e.shape[0])
    if not isinstance(norm_tolerance, (int, float)) or not math.isfinite(float(norm_tolerance)) or float(norm_tolerance) <= 0.0:
        raise ValueError("norm_tolerance must be positive and finite")
    if not isinstance(orthogonality_tolerance, (int, float)) or not math.isfinite(float(orthogonality_tolerance)) or float(orthogonality_tolerance) < 0.0:
        raise ValueError("orthogonality_tolerance must be non-negative and finite")
    if _trusted_live_provenance is not None and _trusted_live_provenance is not _LIVE_PROVENANCE_TOKEN:
        raise ValueError("trusted live provenance is reserved for the live provider")
    weighted_e = np.sqrt(eps)[None, :, :, None] * e
    vectors, norms = [], []
    for index in range(e.shape[0]):
        vector = np.concatenate((weighted_e[index].reshape(-1), h[index].reshape(-1)))
        norm = float(np.sqrt(np.vdot(vector, vector).real))
        if not math.isfinite(norm) or norm <= float(norm_tolerance):
            raise ValueError(f"energy state {index} has a norm at or below norm_tolerance")
        vector = np.asarray(vector / norm, dtype=np.complex128)
        vector.setflags(write=False)
        vectors.append(vector)
        norms.append(norm)
    matrix = np.column_stack(vectors)
    gram = np.asarray(matrix.conj().T @ matrix, dtype=np.complex128)
    gram.setflags(write=False)
    off = np.array(gram, copy=True)
    np.fill_diagonal(off, 0.0)
    max_off = float(np.max(np.abs(off)))
    max_norm_error = float(max(abs(float(np.vdot(v, v).real) - 1.0) for v in vectors))
    status = MPB_H_ENVELOPE_QUALIFIED if max_norm_error <= float(orthogonality_tolerance) and max_off <= float(orthogonality_tolerance) else MPB_H_ENVELOPE_UNQUALIFIED
    caller = {} if provenance is None else dict(provenance)
    caller.update({"representation": MPB_ENERGY_EH_REPRESENTATION, "energy_metric": "sum(epsilon*conj(E1)*E2 + conj(H1)*H2)", "quadrature": "uniform discrete cell quadrature; common cell volume cancels", "epsilon_weighting": "electric contribution weighted exactly once by epsilon", "periodic_e_and_h_envelopes": True, "bloch_phase_excluded": True})
    frozen = {
        "representation": MPB_ENERGY_EH_REPRESENTATION,
        "spatial_shape": [int(e.shape[1]), int(e.shape[2])],
        "component_count": 3,
        "flattening_order": "C",
        "component_order": "supplied final axis order; vector=(sqrt(epsilon)E,H)",
        "normalization_convention": "full Maxwell discrete energy norm",
        "metric": "sum(epsilon*conj(E1)*E2 + conj(H1)*H2)",
        "quadrature": "uniform cell quadrature with common cell volume omitted",
        "periodic_e_and_h_envelopes": True,
        "bloch_phase_excluded": True,
        "live_mpb_extraction_validated": _trusted_live_provenance is _LIVE_PROVENANCE_TOKEN,
        "mpb_k_point": None if mpb_k is None else list(mpb_k),
        "solver_index_semantics": "ordering metadata only",
        "batch_orthogonality_status": status,
        "batch_max_off_diagonal_gram": max_off,
        "batch_max_normalization_error": max_norm_error,
        "caller_provenance": caller,
    }
    states = tuple(RawEigenstate(k_point=k, solver_index=index, eigenvalue=float(freq[index]), vector=vector, metadata=frozen) for index, vector in enumerate(vectors))
    return MPBHEnvelopeSnapshot(
        k_point=k,
        frequencies=freq,
        h_fields=h,
        e_fields=e,
        raw_norms=np.asarray(norms, dtype=float),
        normalized_vectors=tuple(vectors),
        gram_matrix=gram,
        max_normalization_error=max_norm_error,
        max_off_diagonal_gram=max_off,
        orthogonality_status=status,
        normalization_tolerance=float(norm_tolerance),
        orthogonality_tolerance=float(orthogonality_tolerance),
        raw_eigenstates=states,
        provenance=frozen,
    )


__all__ = ["MPB_ENERGY_EH_REPRESENTATION", "adapt_mpb_energy_eh_envelopes"]
