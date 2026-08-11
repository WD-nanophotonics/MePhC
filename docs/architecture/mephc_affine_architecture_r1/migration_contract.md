# R1.1 Migration Contract

This is a plan artifact only. It does not implement R2 or affine behavior.

## Ordered seams

| Step | Existing seam | Responsibility behind the seam | Compatibility callers/tests |
|---|---|---|---|
| 1 | `mephc.band.Band._make_geometry_lattice`; `mephc.lattice.maketriangularlattice`; `mephc.lattice.makesquarelattice` | One explicit direct-basis and normalized-geometry context | `test_lock_01_real_space_and_solver_basis_parity`; existing `Band` constructors |
| 2 | `mephc.geometry.to_meep_geometry`; `Band.create_unitcell` | Convert a context-owned motif to Meep geometry without changing polygon order | geometry conversion examples and existing case smoke tests |
| 3 | `mephc.kspace.HighSymmetryPath`; `TriangularKSpace`; `SquareKSpace` | Derive reciprocal coordinates, BZ domains, and path conventions from the context | LOCK-02 through LOCK-06 and downstream path tests |
| 4 | `mephc.band._run_cartesian_k_frequencies`; `mephc.berry.BerryCurvatureCalculator` | Consume one shared reciprocal coordinate object and preserve Cartesian public inputs | Berry/band low-resolution tests and record metadata checks |
| 5 | `mephc.records.make_geometry_id`; `make_task_key`; `find_matching_record` | Make result-affecting identity explicit while excluding plot parameters | LOCK-09 and case auto/plot-only tests |
| 6 | `mephc.workflows.resolve_record`; TriLatt/SqrLatt local `_resolve_existing_record` | Move reusable record resolution behind one facade | both case workflow suites before caller switch |

## Legacy facade policy

Current `Band`, k-space functions, and record helpers remain public facades while
the context is introduced. Existing callers in `MePhC/examples`, TriLatt, and
SqrLatt must continue to run. No removal is permitted in R2; deprecation may be
announced only after compatibility tests pass in both consumers.

## Migration order and hold point

1. Land and validate the coordinate/context seam in MePhC.
2. Migrate TriLatt first, preserving its C3 declaration and records.
3. Run the full TriLatt suite and cross-repository import checks.
4. Hold SqrLatt until a full-structure C4 decision is characterized; its current
   `symmetry = "c4q"` is explicit and must not be silently converted to auto.
5. Migrate SqrLatt only after the hold-point review accepts the C4 policy.

Each step stops and rolls back the caller switch if basis parity, path values,
record identity, or solver smoke changes unexpectedly. Rollback means leaving
the new facade unused while retaining the compatibility layer; it does not
rewrite records or use reset/clean operations.

## Explicit exclusions

- local motif deformation;
- global affine or Bravais-frame deformation;
- supercells;
- nonperiodic structures;
- non-Abelian Berry implementation;
- unrelated solver redesign;
- automatic C4 inference before full-structure verification.
