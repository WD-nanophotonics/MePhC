# R1 Migration Contract

## Hard invariants

1. No affine deformation is implemented in R1.
2. No production/runtime source file is changed in any of the three repos.
3. Existing data, image, diagnostic, cache, and archive evidence remains byte
   identical.
4. Existing public behavior remains available; R1 only adds characterization
   tests and audit artifacts to `MePhC`.
5. Plot parameters do not define simulation record identity. Result-affecting
   task and compute parameters do.
6. Reciprocal coordinates must retain explicit unit and `2*pi` semantics in
   any future shared context; no silent convention change is allowed.
7. Symmetry reduction may only be applied after checking the full structure,
   not the lattice in isolation.
8. Records are never implicitly rewritten when a plot is requested.
9. TriLatt is the first migration consumer; SqrLatt follows after the shared
   context is characterized.

## R2 proposed boundary

The proposed dependency target is:

```text
math/coordinates -> lattice/structure -> reciprocal/symmetry
    -> solver adapters -> observables/workflows
```

R2 should introduce an explicit immutable geometry/coordinate context holding
the direct basis, normalization, reciprocal basis, lattice type, motif, and
units. Solver adapters should consume that context instead of reconstructing
parallel basis and coordinate assumptions. Observable and record layers should
receive the same context and task identity.

## R2 exclusions until resolved

- no automatic affine deformation model;
- no non-Abelian Berry implementation without a degeneracy characterization;
- no assumption that a polygon-side count proves full-structure symmetry;
- no deletion of compatibility wrappers until downstream imports are audited;
- no migration of binary records into the package repository.

## Evidence policy

Consumer repositories own `.pkl`, images, MPB caches, and diagnostic outputs.
Only small manifests and reproducible metadata belong in Git. The MePhC R1
artifact manifest contains hashes for the audit artifacts, not user data.
