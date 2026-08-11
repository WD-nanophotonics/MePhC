# API Decisions

## AffineTransform2D

`AffineTransform2D` accepts a finite nonsingular `(2, 2)` matrix, uses column
vector mathematics, and applies to `(2,)` or `(N, 2)` points.  `compose` is
matrix composition (`left.compose(right)` applies `right` first).  The matrix
property is a read-only defensive copy.  `uniaxial` is a mathematical
constructor only; no user-facing deformation workflow is exposed.

## BravaisLattice2D

Direct basis vectors are columns.  The reciprocal basis is `A^{-T}` without a
`2*pi` factor, so `A.T @ B == I`.  `to_meep_lattice` is the only solver-facing
adapter.  Named triangular and square factories preserve the existing MPB
bases; custom bases support affine and oblique mathematics.

## BrillouinZone2D

`first_brillouin_zone` computes an origin-centered Euclidean Wigner-Seitz cell
by clipping half-planes generated from reciprocal-lattice neighbors.  It does
not transform a legacy polygon and does not add named K/M semantics.

## Compatibility

Existing positional and keyword call shapes remain valid.  Optional
`lattice_model` arguments let migrated callers provide the canonical model;
omitting them selects the historical named lattice.  Existing k-space
wrappers and path classes remain available.
