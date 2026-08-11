"""Canonical two-dimensional Bravais-lattice model and solver adapter."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .affine import AffineTransform2D


@dataclass(frozen=True, slots=True, init=False)
class BravaisLattice2D:
    """A 2-D direct basis stored as columns.

    If ``A = direct_basis``, column ``j`` is direct lattice vector ``a_j``.
    The reciprocal basis ``B`` is stored with the same convention and is
    defined without a ``2*pi`` factor, so ``A.T @ B == I``.  MPB receives the
    direct columns through :meth:`to_meep_lattice`.
    """

    _direct_basis: tuple[tuple[float, float], tuple[float, float]]
    kind: str
    tolerance: float
    reference_family: str
    current_symmetry: str
    _deformation_matrix: tuple[tuple[float, float], tuple[float, float]]

    def __init__(self, direct_basis, kind: str = "custom", tolerance: float = 1e-12,
                 reference_family: str | None = None, deformation_matrix=None):
        array = np.asarray(direct_basis, dtype=float)
        if array.shape != (2, 2):
            raise ValueError("direct_basis must have shape (2, 2), with vectors in columns")
        if not np.all(np.isfinite(array)):
            raise ValueError("direct_basis must contain only finite values")
        if not np.isfinite(tolerance) or tolerance <= 0:
            raise ValueError("tolerance must be a positive finite number")
        determinant = float(np.linalg.det(array))
        scale = max(1.0, float(np.linalg.norm(array, ord=2)))
        if abs(determinant) <= tolerance * scale * scale:
            raise ValueError("direct_basis vectors must be independent")
        normalized_kind = str(kind).lower()
        if normalized_kind not in {"custom", "triangular", "square"}:
            raise ValueError("kind must be 'custom', 'triangular', or 'square'")
        family = str(reference_family or normalized_kind).lower()
        if family not in {"custom", "triangular", "square"}:
            raise ValueError("reference_family must be 'custom', 'triangular', or 'square'")
        deformation = np.eye(2) if deformation_matrix is None else np.asarray(deformation_matrix, dtype=float)
        if deformation.shape != (2, 2) or not np.all(np.isfinite(deformation)):
            raise ValueError("deformation_matrix must be a finite (2, 2) matrix")
        object.__setattr__(self, "_direct_basis", tuple(tuple(float(v) for v in row) for row in array))
        object.__setattr__(self, "kind", normalized_kind)
        object.__setattr__(self, "tolerance", float(tolerance))
        object.__setattr__(self, "reference_family", family)
        identity = np.allclose(deformation, np.eye(2), atol=0.0, rtol=0.0)
        symmetry = {
            "triangular": "triangular_c3" if identity else "generic_affine",
            "square": "square_c4" if identity else "generic_affine",
            "custom": "custom" if identity else "generic_affine",
        }[family]
        object.__setattr__(self, "current_symmetry", symmetry)
        object.__setattr__(self, "_deformation_matrix", tuple(tuple(float(v) for v in row) for row in deformation))

    @classmethod
    def triangular(cls) -> "BravaisLattice2D":
        """Return the existing MPB triangular basis and orientation."""

        return cls(
            np.array([[0.5, 0.5], [np.sqrt(3.0) / 2.0, -np.sqrt(3.0) / 2.0]]),
            kind="triangular",
        )

    @classmethod
    def square(cls) -> "BravaisLattice2D":
        """Return the existing unit square MPB basis."""

        return cls(np.eye(2), kind="square")

    @classmethod
    def named(cls, lattice_type: str) -> "BravaisLattice2D":
        """Construct the canonical basis for a triangular or square alias."""

        key = str(lattice_type).lower()
        if key in {"triangular", "tri", "t", "honeycomb", "hon", "hc", "h"}:
            return cls.triangular()
        if key in {"square", "sqr", "s"}:
            return cls.square()
        raise ValueError("lattice_type must be 'triangular' or 'square'")

    @property
    def direct_basis(self) -> np.ndarray:
        """Return a read-only defensive copy of the direct basis."""

        result = np.array(self._direct_basis, dtype=float)
        result.setflags(write=False)
        return result

    @property
    def reciprocal_basis(self) -> np.ndarray:
        """Return the no-2pi reciprocal basis ``B = A^{-T}``."""

        result = np.linalg.inv(self.direct_basis).T
        result.setflags(write=False)
        return result

    @property
    def cell_area(self) -> float:
        """Return the positive direct primitive-cell area."""

        return abs(float(np.linalg.det(self.direct_basis)))

    @property
    def orientation(self) -> int:
        """Return +1 for CCW and -1 for CW direct basis orientation."""

        return 1 if np.linalg.det(self.direct_basis) > 0 else -1

    @property
    def condition_number(self) -> float:
        """Return the 2-norm condition number of the direct basis."""

        return float(np.linalg.cond(self.direct_basis))

    @property
    def is_identity(self) -> bool:
        """Whether this model is the undeformed reference lattice."""

        return np.allclose(self.deformation_matrix, np.eye(2), atol=0.0, rtol=0.0)

    @property
    def deformation_matrix(self) -> np.ndarray:
        """Return the direct-space affine matrix from the reference basis."""

        result = np.asarray(self._deformation_matrix, dtype=float)
        result.setflags(write=False)
        return result

    def supports_legacy(self, capability: str) -> bool:
        """Return whether an identity-only named-lattice capability is valid."""

        if not self.is_identity:
            return False
        if self.reference_family == "triangular":
            return capability in {"c3", "hbz", "gkm", "mini_space"}
        if self.reference_family == "square":
            return capability in {"gxm", "c4"}
        return False

    @property
    def real_space_grid_basis(self) -> np.ndarray:
        """Return the legacy site-grid basis as an explicit canonical adapter.

        The triangular generator historically enumerates rows translated by
        ``(1, 0)`` and ``(1/2, sqrt(3)/2)``.  Those vectors equal ``A @ U``
        for the fixed integer matrix ``U=[[1,1],[1,0]]``.  Keeping this
        adapter explicit preserves the old point ordering without introducing
        a second lattice truth source.
        """

        if self.kind == "triangular":
            result = self.direct_basis @ np.array([[1.0, 1.0], [1.0, 0.0]])
        else:
            result = self.direct_basis.copy()
        result.setflags(write=False)
        return result

    def transformed(self, transform: AffineTransform2D) -> "BravaisLattice2D":
        """Apply a direct-space affine transform to both direct vectors."""

        if not isinstance(transform, AffineTransform2D):
            raise TypeError("transform must be an AffineTransform2D")
        deformation = transform.matrix @ self.deformation_matrix
        if transform.is_identity:
            return self
        return BravaisLattice2D(
            transform.matrix @ self.direct_basis,
            kind=self.kind,
            tolerance=self.tolerance,
            reference_family=self.reference_family,
            deformation_matrix=deformation,
        )

    def fractional_to_cartesian(self, coordinates) -> np.ndarray:
        """Map direct fractional coordinates to Cartesian coordinates."""

        values = _coordinates(coordinates)
        return values @ self.direct_basis.T

    def cartesian_to_fractional(self, coordinates) -> np.ndarray:
        """Map Cartesian coordinates to direct fractional coordinates."""

        values = _coordinates(coordinates)
        return values @ np.linalg.inv(self.direct_basis).T

    def reciprocal_to_cartesian(self, coordinates) -> np.ndarray:
        """Map reciprocal fractional coordinates to Cartesian k coordinates."""

        values = _coordinates(coordinates)
        return values @ self.reciprocal_basis.T

    def cartesian_to_reciprocal(self, coordinates) -> np.ndarray:
        """Map Cartesian k coordinates to reciprocal fractional coordinates."""

        values = _coordinates(coordinates)
        return values @ np.linalg.inv(self.reciprocal_basis).T

    def to_meep_lattice(self, *, size=(1.0, 1.0), z_size: float = 0.0):
        """Create an MPB/Meep ``mp.Lattice`` from this canonical basis."""

        import meep as mp

        a1, a2 = self.direct_basis.T
        return mp.Lattice(
            size=mp.Vector3(float(size[0]), float(size[1]), float(z_size)),
            basis1=mp.Vector3(float(a1[0]), float(a1[1])),
            basis2=mp.Vector3(float(a2[0]), float(a2[1])),
        )

    def metadata(self) -> dict[str, object]:
        """Return deterministic JSON-safe lattice metadata."""

        return {
            "type": "BravaisLattice2D",
            "kind": self.kind,
            "reference_family": self.reference_family,
            "current_symmetry": self.current_symmetry,
            "legacy_eligibility": {
                "c3": self.supports_legacy("c3"),
                "hbz": self.supports_legacy("hbz"),
                "gkm": self.supports_legacy("gkm"),
                "gxm": self.supports_legacy("gxm"),
            },
            "deformation_matrix": self.deformation_matrix.tolist(),
            "basis_convention": "columns_are_vectors",
            "direct_basis": self.direct_basis.tolist(),
            "reciprocal_basis_no_2pi": self.reciprocal_basis.tolist(),
            "cell_area": self.cell_area,
            "orientation": self.orientation,
            "condition_number": self.condition_number,
            "tolerance": self.tolerance,
        }


def _coordinates(coordinates) -> np.ndarray:
    values = np.asarray(coordinates, dtype=float)
    if values.shape == (2,):
        return values
    if values.ndim == 2 and values.shape[1] == 2:
        return values
    raise ValueError("coordinates must have shape (2,) or (N, 2)")
