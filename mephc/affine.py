"""Small, deterministic two-dimensional affine-transform primitives.

The public API uses column-vector mathematics internally.  ``apply`` accepts
points as ``(2,)`` or ``(N, 2)`` arrays and returns the same shape; no silent
transpose is performed.  ``compose`` follows the usual function order:
``left.compose(right)`` represents ``left @ right`` and therefore applies
``right`` first, then ``left``.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np


@dataclass(frozen=True, slots=True, init=False)
class AffineTransform2D:
    """An immutable finite, nonsingular 2 x 2 affine linear transform.

    Parameters
    ----------
    matrix:
        A finite ``(2, 2)`` floating matrix.  Singular and near-singular
        matrices are rejected when ``abs(det) <= tolerance * scale**2``.
    tolerance:
        Numerical singularity threshold.  It is stored in metadata so a
        transform can be reproduced without relying on platform repr text.
    """

    _matrix: tuple[tuple[float, float], tuple[float, float]]
    tolerance: float

    def __init__(self, matrix, tolerance: float = 1e-12):
        array = np.asarray(matrix, dtype=float)
        if array.shape != (2, 2):
            raise ValueError("matrix must have shape (2, 2)")
        if not np.all(np.isfinite(array)):
            raise ValueError("matrix must contain only finite values")
        if not np.isfinite(tolerance) or tolerance <= 0:
            raise ValueError("tolerance must be a positive finite number")
        determinant = float(np.linalg.det(array))
        scale = max(1.0, float(np.linalg.norm(array, ord=2)))
        if abs(determinant) <= float(tolerance) * scale * scale:
            raise ValueError("matrix is singular or numerically near-singular")
        object.__setattr__(self, "_matrix", tuple(tuple(float(v) for v in row) for row in array))
        object.__setattr__(self, "tolerance", float(tolerance))

    @classmethod
    def identity(cls) -> "AffineTransform2D":
        """Return the identity transform."""

        return cls(np.eye(2))

    @classmethod
    def uniaxial(cls, factor: float, angle_degrees: float = 0.0) -> "AffineTransform2D":
        """Return uniaxial stretch ``I + (factor-1) n n^T``.

        ``n`` is the unit vector at ``angle_degrees`` measured counter-
        clockwise from +x.  ``factor`` must be finite and strictly positive.
        """

        if not np.isfinite(factor) or factor <= 0:
            raise ValueError("factor must be a positive finite number")
        if not np.isfinite(angle_degrees):
            raise ValueError("angle_degrees must be finite")
        if float(factor) == 1.0:
            # Identity has no directional parameter; keep its serialized form
            # independent of the angle supplied by a caller.
            return cls.identity()
        if max(float(factor), 1.0 / float(factor)) > 1e8:
            raise ValueError("factor produces a transform beyond the conditioning limit 1e8")
        angle = math.radians(float(angle_degrees))
        direction = np.array([math.cos(angle), math.sin(angle)], dtype=float)
        matrix = np.eye(2) + (float(factor) - 1.0) * np.outer(direction, direction)
        return cls(matrix)

    @property
    def is_identity(self) -> bool:
        """Whether this transform is exactly the canonical identity matrix."""

        return self._matrix == ((1.0, 0.0), (0.0, 1.0))

    @property
    def matrix(self) -> np.ndarray:
        """Return a read-only defensive copy of the transform matrix."""

        result = np.array(self._matrix, dtype=float)
        result.setflags(write=False)
        return result

    @property
    def determinant(self) -> float:
        """Return the determinant of the transform."""

        return float(np.linalg.det(self.matrix))

    def apply(self, points) -> np.ndarray:
        """Apply the transform to one point or an ``(N, 2)`` point array."""

        values = np.asarray(points, dtype=float)
        if values.shape not in {(2,), (0, 2)} and not (values.ndim == 2 and values.shape[1] == 2):
            raise ValueError("points must have shape (2,) or (N, 2)")
        if not np.all(np.isfinite(values)):
            raise ValueError("points must contain only finite values")
        return values @ self.matrix.T

    def compose(self, right: "AffineTransform2D") -> "AffineTransform2D":
        """Return ``self @ right``; ``right`` is applied first."""

        if not isinstance(right, AffineTransform2D):
            raise TypeError("right must be an AffineTransform2D")
        return AffineTransform2D(self.matrix @ right.matrix, tolerance=max(self.tolerance, right.tolerance))

    def inverse(self) -> "AffineTransform2D":
        """Return the inverse transform."""

        return AffineTransform2D(np.linalg.inv(self.matrix), tolerance=self.tolerance)

    def almost_equal(self, other: "AffineTransform2D", atol: float = 1e-12, rtol: float = 1e-12) -> bool:
        """Compare matrices with explicit NumPy tolerances."""

        return isinstance(other, AffineTransform2D) and np.allclose(self.matrix, other.matrix, atol=atol, rtol=rtol)

    def metadata(self) -> dict[str, object]:
        """Return deterministic JSON-safe transform metadata."""

        return {
            "type": "AffineTransform2D",
            "matrix": [[float(v) for v in row] for row in self._matrix],
            "tolerance": float(self.tolerance),
            "determinant": self.determinant,
        }
