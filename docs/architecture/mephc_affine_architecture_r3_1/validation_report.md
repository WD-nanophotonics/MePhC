# R3.1 Validation Report

Generated: `2026-08-12T05:02:16.262592+00:00`

## Decision

R3.1 corrective validation is **PASS**. All required production, geometry,
landmark, smoke, compatibility, and integrity gates pass. R4 is not authorized.

## Corrective gates

- Motif placement: all identity and nonidentity cases satisfy `center = F @ reference_center`; local polygon offsets remain rigid.
- Reciprocal landmark: identity preserves legacy `(2/3, 0)`; nonidentity selects deterministic current-BZ `tracked_K1` from the `F^-T` predictor.
- Entrypoints: real low-resolution band, Berry, EFS, and frequency-at-landmark MPB calls pass without record writes.
- Documentation: TriLatt describes deformation semantics and current-BZ landmark behavior.

## Test evidence

- MePhC: 33 tests passed.
- TriLatt: 28 tests passed.
- Compileall, R2 validator, R3 validator, and MPB smoke: exit code 0.
- Geometry cases: `4` passed.
- Landmark cases: `4` passed.
- MPB smoke entries: `4` passed.

## Scope and integrity

The change allowlists pass. Protected R1/R2/R3 evidence, scientific data/images,
and the SqrLatt tree are unchanged according to `integrity_digests.json`.

## Review state

`independent_review_required = true`; no R4 work was started or authorized.
