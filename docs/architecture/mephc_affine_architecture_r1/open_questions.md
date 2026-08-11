# Open Questions

1. Which object is the authoritative physical geometry: `Band` construction,
   case `config.py`, or a future immutable geometry context?
2. Should `a`, normalized coordinates, and reciprocal coordinates be modeled
   as explicit units instead of documented conventions?
3. Does `Band.K` for the triangular solver represent the same physical point
   as the public Cartesian `triangular_gkm_path` K point? The current code has
   both `(1/3, 1/3)` and `(2/3, 0)` conventions in different boundaries and
   needs an explicit reciprocal-coordinate decision.
4. Is C3/C4 symmetry a property of the Bravais lattice, the motif, or the full
   dielectric structure for each case? Current case logic mostly checks motif
   polygon side counts.
5. How should band identity be tracked through crossings or near degeneracies?
   The current Berry workflow is Abelian and band-index based.
6. Should the solver adapter own `mp.cartesian_to_reciprocal`, or should a
   shared reciprocal context expose both coordinate forms?
7. Which record fields are required for exact reproducibility across Meep/MPB
   versions, and which are diagnostic-only?
8. Should TriLatt and SqrLatt depend on a released MePhC version, editable path,
   or a monorepo/submodule arrangement for audit workflows?
9. What is the intended affine model: a global Bravais deformation, a local
   motif deformation, or both with separate identities?
10. Should existing local record lookup wrappers be removed after a shared
    workflow API is proven against both consumers?
