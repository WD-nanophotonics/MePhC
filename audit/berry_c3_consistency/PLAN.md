# MePhC Berry C3 internal-consistency qualification

Goal ID: `MEPHC-BERRY-C3-CONSISTENCY-V1`

## Scientific question

Determine why the existing triangular-lattice Berry-curvature map is not
internally C3-consistent.  The work must distinguish physical geometry
asymmetry from MPB initialization noise, plane-wave resolution, finite-stencil
orientation and size, band association near degeneracy, Wilson-loop branch
effects, and field-representation/normalization effects.  A smoother or more
symmetric-looking plot is not scientific acceptance.

The frozen observation is the existing TriLatt record
`/home/icy/TriLatt/data/_tmp/bc_latest.pkl`, SHA-256
`d602a094e662103274fd53502bcdb5da41518ac53e61a2518b6962cdc97ca88d`,
size 16627 bytes.  It uses `r1=80`, `r2=75`, `n1=n2=16`, orientations
0 and 60 degrees, resolution 128, step 0.001, grid N 36, target band 2,
and raw K-centred HBZ sampling.  Its strongest C3-related orbit contains
values approximately -257.5, +194.0, and +46.9.  The record is evidence only
and must never be rewritten.

## Controls and sampling

Use two geometries.  `G16` is the frozen screenshot geometry.  `G15` replaces
each 16-sided polygon with a 15-sided polygon while preserving each polygon's
area independently:

```text
r15 = r16 * sqrt(16*sin(2*pi/16) / (15*sin(2*pi/15)))
factor = 1.0017919605440295
r1 = 80.14335684352235
r2 = 75.13439704080221
```

All other material, placement, lattice, polarization, and thickness settings
remain fixed.  G15 is the nearby exact-C3 control; G16 is not to be relabelled
as exact C3 merely because its visual outline is close.

Use K=(2/3,0).  K is spectral-only until rank-1 isolation is qualified.  Pilot
orbits are generated independently from `K-(m/36,0)` for m=1,4,7,10 and their
120/240-degree rotations about K.  The m=7 orbit is first because it contains
the largest observed discrepancy.  Each rotated point is solved independently:
no sector copying, symmetry expansion, value averaging, spike removal, or
scientific interpolation is permitted.

## Milestone 1: solver-free baseline and harness

This milestone has zero Native/provider/solver budget.

1. Verify and snapshot the frozen record and all relevant existing records by
   path, SHA, size, geometry, solver controls, and sampling coordinates.
2. Produce C3-orbit residuals, significant-sign tests, and common-k identity
   checks without altering the records.
3. Implement an audit-only diagnostic entrypoint and fake-provider tests.  For
   every requested solve it must retain only bounded scalars/small matrices:
   exact k, geometry digest, resolution, step, tolerance, mesh size,
   deterministic flag, the first four frequencies, adjacent gaps, iteration
   evidence, link magnitudes/phases, Wilson phase, branch margin, rank-1 band-2
   and composite [1,2]/[2,3] projector observables, and energy-EH/H-only
   reductions.
4. Support both the current lab-fixed square stencil and a C3-covariant rotated
   stencil.  Do not change the production Berry calculator in this milestone.
5. Generate a content-addressed request graph and its exact provider/solver
   demand.  No live acquisition may begin until a successor machine contract
   explicitly authorizes those exact counts.

## Milestone 2: bounded Native pilot

Begin with the m=7 orbit only, using at least four computed bands, tolerance
1e-7, and mesh size 3.  Compare deterministic false and true with three
independent repeats, G16 and G15, and lab-fixed versus covariant stencils.  K
receives frequencies/gaps/projector diagnostics but no assumed rank-1 value.

If deterministic-true repetition remains unresolved, test tolerance 1e-9 and
mesh size 1 versus 3 on the m=7 orbit only.  Analyze this dataset solver-free
inside the same milestone.  Do not request an extended acquisition unless the
predeclared causal decision table remains genuinely ambiguous.

## Milestone 3: conditional extension and qualification

At most one extended acquisition is permitted.  It may cover both geometries
and all four orbits at deterministic true, resolutions 64/128, and steps
1/144, 1/288, and 0.001.  Resolution 32/96 or steps 1/576 and 0.0005 may be
added only by a request graph created before dispatch and only when the first
grid has no identifiable plateau.

Only after the pilot qualifies a method may a full G15 raw-HBZ grid-N-36 map
be acquired.  It must consist of independent points and be accompanied by C3
residual and uncertainty maps.  A G16 map is secondary explanatory evidence.

## Qualification rules

* Repeat uncertainty is a robust three-repeat dispersion; resolution/step
  uncertainty conservatively includes adjacent-setting differences.
* An exact-C3 orbit passes only if every pairwise difference lies within the
  combined uncertainty.  A sign difference is significant only when both
  intervals exclude zero.  All rank-1-eligible pilot orbits must pass; no
  averaging may turn a failure into a pass.
* Common exact k points must agree when geometry and all solver/stencil settings
  agree, regardless of grid N.  Otherwise report hidden state or an
  implementation defect.
* Rank 1 is reportable only when adjacent-gap signal-to-uncertainty is at least
  10, association/projector evidence is stable, link magnitudes exceed the
  repeat noise floor by at least 10, and branch margin exceeds phase uncertainty
  by at least 5.  Otherwise emit `RANK1_WITHHELD` and report any composite
  observable under its own name.
* Do not require mechanically monotone convergence.  Identify a supported
  plateau or state that no qualified plateau was found.

The terminal causal classification is selected from: physical approximate-C3
geometry, random initialization, stencil orientation, plane-wave/geometry
resolution, band association/near-degeneracy, branch/plaquette scale,
field representation/normalization, multiple identified causes, or unresolved
under the bounded experiment.

## Production and workflow boundaries

Production code may change only after one cause is supported, and only by the
smallest corresponding change: deterministic provenance, a qualified stencil,
recommended resolution/step, or rank-1 refusal/quality masks.  Never
symmetrize the scientific data.  COMSOL comparison begins only after internal
qualification.

Use the existing Luna task and four-command Thin Flow.  Request substantial
`challenge + manual_book + milestone` work orders: harness/baseline, pilot plus
analysis, and conditional extension plus synthesis.  Keep local repair and
tests within the same work order.  Every Native acquisition requires an exact
budget and durable run ID; uncertain runs are reconciled rather than repeated.
Push only `origin/sandbox`; never move `origin/main`.

