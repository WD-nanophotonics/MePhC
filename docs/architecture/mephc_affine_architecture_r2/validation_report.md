# Validation Report

## Baselines

- MePhC baseline contains `ba1ea29ae86e6fb72f96a3a6099b5e2127e02407`.
- MePhC and TriLatt were clean before implementation; SqrLatt was clean and
  read-only.
- Existing MePhC tests: 18 passed before R2 edits.
- Existing TriLatt tests: 22 passed before R2 edits.
- R1.1 artifact validator passed during preflight.

## R2 focused coverage

- Affine validation/application/composition/inverse/metadata.
- Reciprocal duality, coordinate round trips, named triangular/square parity.
- Generic BZ construction for identity, anisotropic, rotated, sheared, and
  ill-conditioned valid bases.
- Meep adapter and legacy real-space point-order parity.
- TriLatt canonical model consumed by Band, pattern, and k-space workflow.

## Final acceptance boundary

The final completion record contains exact commands, exit codes, durations,
and evidence paths.  The historical R1.1 validator remains unchanged and its
pre-R2 pass is recorded.  Its whole-runtime-tree equality assertion is not a
post-R2 acceptance condition because the R2 scope explicitly adds runtime
production modules.  R1/R1.1 artifacts, scientific records, and SqrLatt are
checked by independent byte digests.
