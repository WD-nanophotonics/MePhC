# Canonical Structure Contract

SqrLatt/square_hole/canonical.py is the case authority. It consumes the
accepted MePhC AffineTransform2D, BravaisLattice2D, first_brillouin_zone,
SquareKSpace, and geometry conversion APIs.

One SquareHoleStructure provides:
- reference square direct basis;
- uniaxial F = I + (s - 1) n n^T;
- current direct and reciprocal bases;
- validated current Wigner-Seitz BZ;
- rigid centered square-hole vertices;
- transformed primitive-cell outline;
- verified C4 capability;
- identity/non-identity geometry ID and path policy;
- the exact pattern used by NumPy preview, MPB geometry, Band, Berry, EFS,
  metadata, and records.

At factor == 1, angle canonicalizes out and the legacy geometry ID remains
SQR_LATT_SQR_HOLE_A400_D200_NEFF2p7. At factor != 1, the geometry ID includes
factor and angle. The square-hole side, orientation, material, and local
Cartesian vertices do not deform.

Legacy config facades remain available: make_band, build_pattern, band_path,
square_grid, c4_quadrant, unit_cell_outline, preview_pattern_data.
