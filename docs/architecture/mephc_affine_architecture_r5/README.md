# MePhC Affine Architecture R5

R5 introduces one shared spatial deformation-field value model. It maps
reference positions as `r' = r + u(r)` and exposes `F = I + grad(u)` plus
diagnostic small strain and rotation tensors. These diagnostics are not
physical strain or curved-space models.

The capability boundary is explicit:

- `GLOBAL_AFFINE_PERIODIC` is the R2–R4 primitive-cell path.
- `SUPERCELL_PERIODIC` is admitted to reciprocal-space code only after the
  declared integer supercell boundary check passes; objects are labeled
  `supercell` and primitive labels/reductions are disabled.
- `APERIODIC_LOCAL` is preview/real-space only. Primitive BZ, Band, Berry,
  EFS, high-symmetry and C3/C4 calls fail with an actionable typed error.

TriLatt and SqrLatt import `mephc.deformation` and `mephc.r5`; neither owns a
second deformation kernel. Motif geometry stays rigid and only motif centers
move.

The R4.1 bundle is validated before R5 writes and is referenced read-only.
Band unfolding, local Berry observables, strain/material coupling, elastic
relaxation, automatic symmetry discovery and R6 remain deferred.
