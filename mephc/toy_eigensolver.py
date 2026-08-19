"""Minimal solver-neutral NumPy Hermitian toy backend for E1."""

from __future__ import annotations

from typing import Any

import numpy as np

from .eigenspace import RawEigenstate


HERMITIAN_ATOL = 1e-12


def solve_hermitian(
    matrix: Any,
    *,
    k_point: Any = (0.0,),
    solver_order: str = "ascending",
) -> tuple[RawEigenstate, ...]:
    """Solve a finite Hermitian matrix and return raw ordering metadata.

    ``solver_order='permuted'`` swaps the first two raw states and exists only
    to test that solver ordering is not physical eigenspace identity.
    ``'descending'``/``'reverse'`` provide a deterministic reverse ordering.
    """
    try:
        array = np.asarray(matrix)
    except (TypeError, ValueError) as exc:
        raise ValueError("matrix must be a numeric square matrix") from exc
    if array.ndim != 2 or array.shape[0] != array.shape[1] or array.shape[0] < 1:
        raise ValueError("matrix must be a non-empty square matrix")
    if array.dtype.kind not in "iufc":
        raise ValueError("matrix must contain numeric values without coercion")
    if not np.all(np.isfinite(array)):
        raise ValueError("matrix must contain only finite values")
    matrix_complex = np.asarray(array, dtype=np.complex128)
    if not np.allclose(matrix_complex, matrix_complex.conj().T, rtol=0.0, atol=HERMITIAN_ATOL):
        raise ValueError(f"matrix must be Hermitian within atol={HERMITIAN_ATOL}")
    eigenvalues, eigenvectors = np.linalg.eigh(matrix_complex)
    count = matrix_complex.shape[0]
    if solver_order == "ascending":
        order = list(range(count))
    elif solver_order in {"descending", "reverse"}:
        order = list(reversed(range(count)))
    elif solver_order in {"permuted", "swap_first_two"}:
        if count < 2:
            raise ValueError("permuted solver order requires at least two states")
        order = [1, 0, *range(2, count)]
    else:
        raise ValueError("solver_order must be 'ascending', 'descending', or 'permuted'")
    return tuple(
        RawEigenstate(
            k_point=k_point,
            solver_index=index,
            eigenvalue=float(eigenvalues[index]),
            vector=eigenvectors[:, index],
            metadata={"backend": "numpy-hermitian-toy", "raw_order": solver_order},
        )
        for index in order
    )


__all__ = ["HERMITIAN_ATOL", "solve_hermitian"]
