# MePhC Affine Architecture R7.2

## Final contract closure: verified sign equivalence and differential-resolution ladder

R7.2 closes the remaining response contract gaps:

- `+A` and `-A` are verified as the same periodic geometry after an explicit
  declared primitive translation and order-invariant polygon matching;
- their Maxwell spectra are checked for equivalence at every resolution before
  the odd/even differential response is accepted;
- the full five-amplitude real-MPB response is generated at resolutions 8, 12,
  and 16, and the differential coefficients are compared across adjacent
  resolutions.

SqrLatt receives a `PASS_REAL_MPB` response only when sign equivalence,
band-local eligibility, and the differential-resolution ladder all pass.
TriLatt raw spectra are retained for audit, but the pre-existing fixed
8/12/16 baseline convergence contract remains authoritative: no TriLatt
response claim is made while that contract is non-converged.
