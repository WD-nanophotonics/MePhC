# R3 Activation Plan

R3 may be opened only after independent review of the R2 completion record.

1. Decide whether user-facing affine geometry parameters are required.
2. Define the physical meaning of transforming direct geometry, reciprocal
   coordinates, and material/period metadata together.
3. Add explicit deformed-geometry records and cache identity rules.
4. Design Berry/EFS behavior for non-identity lattices, including degeneracy
   and symmetry boundaries; do not infer it from R2 geometry math.
5. Add cross-repository fixtures and acceptance tests before exposing any
   stretch controls.

R3 must not silently change identity geometry IDs, record keys, or the R2
compatibility facades.
