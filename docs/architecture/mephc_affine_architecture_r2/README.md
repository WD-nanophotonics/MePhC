# MePhC Affine Architecture R2

R2 introduces one canonical two-dimensional lattice kernel for MePhC and the
undeformed production path in MePhC-TriLatt.  The scope is deliberately
limited to identity and mathematical affine transforms.  User-facing stretch
parameters, local deformation, and affine Berry/EFS claims are outside R2.

## Scope

- `mephc.affine.AffineTransform2D` is the immutable 2 x 2 linear-transform
  primitive.
- `mephc.bravais.BravaisLattice2D` owns direct and no-`2*pi` reciprocal basis
  conventions and the MPB/Meep lattice adapter.
- `mephc.bz.first_brillouin_zone` reconstructs the reciprocal Wigner-Seitz
  cell from half-planes for any valid 2-D Bravais basis.
- Legacy `Band`, `Lattice`, and k-space classes use explicit compatibility
  adapters and preserve their public call shapes.
- TriLatt's `canonical_lattice()` is the identity geometry truth source used
  by its Band, real-space pattern, and k-space workflows.

## Explicit boundaries

R2 does not add `stretch_factor`, `stretch_angle`, local deformation, or
deformed Berry/EFS workflows.  SqrLatt is read-only in this delivery.  The
existing R1 and R1.1 artifact directories are preserved byte-for-byte.

## Validation

The R2 completion record names implementation and closure commits, records
the Python/Meep environment, and includes test and digest evidence.  The
historical R1.1 runtime-tree validator is retained unchanged; its post-R2
runtime assertion is intentionally not used as an R2 validator because R2
must add production modules.  R1/R1.1 artifacts and scientific records are
validated separately by byte digest.
