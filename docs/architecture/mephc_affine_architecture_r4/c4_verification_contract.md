# C4 Verification Contract

The verifier is candidate-based. It checks only the requested proper 90-degree
rotation and does not search for arbitrary point groups.

Inputs:
1. current direct Bravais basis A, stored as columns;
2. every normalized motif vertex;
3. motif material identity;
4. absolute tolerance 1e-9.

Basis condition:
R90 A = A U for an integer 2 by 2 matrix U within tolerance. This is tested
from U = solve(A, R90 A), not from reference_family or a token.

Motif condition:
For every rotated vertex p, a motif vertex q must satisfy solve(A, p-q)
being an integer vector within tolerance. This is periodic equivalence in the
current direct lattice. All motif entries are checked.

Identity square-hole result:
verified PASS, C4q eligible.

Non-identity uniaxial result:
verified FAIL because unequal principal stretches do not preserve C4. auto
therefore resolves to raw_bz and explicit c4/c4q raises a ValueError.

Negative fixtures:
- rectangular current basis: rejected;
- deliberately triangular/non-C4 motif: rejected;
- reference family or polygon side count: never consulted;
- explicit c4/c4q token alone: never authoritative.

The verifier returns basis_ok, motif_ok, area_ok, material_ok, integer action,
tolerance, and stable reasons. The default production tolerance is 1e-9
absolute with zero relative tolerance.
