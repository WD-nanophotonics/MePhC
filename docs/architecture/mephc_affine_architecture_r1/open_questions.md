# Open Questions

## Question ID: OQ-01

- Decision required: Choose one authoritative owner for direct basis and motif geometry.
- Evidence: `mephc.band.Band._make_geometry_lattice` owns MPB basis; `mephc.lattice.maketriangularlattice` and case configs also define physical placement conventions.
- Option A: Introduce an immutable geometry context consumed by both paths.
- Option B: Keep Band as owner and expose a tested adapter for real-space lattices.
- Impact on R2: Determines the first migration seam and prevents parallel basis definitions.
- Recommended default: Option A, with compatibility facades.
- Resolution owner/trigger: R2 math/coordinates design review before changing callers.

## Question ID: OQ-02

- Decision required: Represent real-space normalization and reciprocal `2*pi` units explicitly.
- Evidence: Current code passes dimensionless Cartesian reciprocal coordinates and invokes `mp.cartesian_to_reciprocal` at solver boundaries.
- Option A: Add typed coordinate/context objects with explicit units and scale.
- Option B: Keep tuples/arrays and enforce conventions through validators and documentation.
- Impact on R2: Controls whether affine work can avoid silent unit mismatches.
- Recommended default: Option A at internal seams, tuple compatibility at public facades.
- Resolution owner/trigger: R2 coordinates implementation and compatibility test review.

## Question ID: OQ-03

- Decision required: Define whether symmetry belongs to the Bravais lattice, motif, or full dielectric structure.
- Evidence: TriLatt C3 selection checks active polygon side counts; SqrLatt currently selects `c4q` explicitly; neither verifies the full structure.
- Option A: Verify symmetry on the complete normalized dielectric geometry before reduction.
- Option B: Keep case-provided symmetry declarations and treat them as user assertions.
- Impact on R2: Determines whether reduced sampling is automatic or declarative.
- Recommended default: Option A for auto mode, Option B retained as an explicit override.
- Resolution owner/trigger: R2 reciprocal/symmetry design after a full-structure verifier exists.

## Question ID: OQ-04

- Decision required: Define band identity across crossings for Berry curvature.
- Evidence: `mephc.berry.BerryCurvatureCalculator` is Abelian and band-index based; R1.1 does not characterize degeneracies.
- Option A: Add non-Abelian subspace links for degenerate bands.
- Option B: Require isolated-band validation and report warnings near crossings.
- Impact on R2: Affects observable correctness and symmetry expansion eligibility.
- Recommended default: Option B first, then Option A where needed.
- Resolution owner/trigger: R2 observables review with a targeted degeneracy study.

## Question ID: OQ-05

- Decision required: Select package coupling policy for TriLatt and SqrLatt.
- Evidence: Both consumers import MePhC through local development paths and duplicate some workflow resolution.
- Option A: Pin released MePhC versions with an editable-development override.
- Option B: Use a coordinated monorepo/submodule arrangement.
- Impact on R2: Controls audit reproducibility and cross-repository migration order.
- Recommended default: Option A with explicit compatibility tests.
- Resolution owner/trigger: Repository maintainers before the first downstream migration.
