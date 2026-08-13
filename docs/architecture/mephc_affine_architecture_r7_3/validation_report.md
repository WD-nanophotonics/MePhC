# R7.3 validation report

The bundle was executed from the byte-for-byte Gmail machine contract. Its SHA-256 is `c2f9d2c8f1b0742cb032abf8b9bd94172ba49d8bcf1a814342b0b181d684a37a`.

Geometry Workstream A enumerated 16 candidates: the four verified identity-square proper operations from the R4/R4.1 complete-structure policy crossed with the four primitive translations modulo the 2x2 supercell. The result is `EQUIVALENT_BY_VERIFIED_OPERATION`, with identity plus translation `(1,0)` and maximum typed-polygon coordinate residual `2.220446049250313e-16`.

SqrLatt Workstreams B-D used real `meep.mpb.ModeSolver` only at resolutions 12, 16, and 20, then ran 24 exactly once because at least one locked target failed 16→20. Each used resolution has the five contracted amplitudes plus two exact +A replays. No resolution 8 was run. TriLatt fresh solver calls are exactly zero.

The final comparison is 20→24. Three of the five locked targets are differential-converged, but only one is resolved under the contract's signal-to-error and absolute-shift gates. The q0 replay floor also detects a q0 +A/-A spectral mismatch under the exact replay tolerance, so the authoritative scientific terminal state is `BLOCKED_EQUIVALENCE_SPECTRAL_MISMATCH`. No response pass is claimed and no threshold was widened.

The R6/R6.1/R7/R7.1/R7.2 evidence trees are protected historical inputs. No completion Gmail was sent and R8 was not performed.
