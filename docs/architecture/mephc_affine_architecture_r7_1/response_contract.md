# R7.1 closure contract

## Geometry

`match_geometry(reference, candidate)` solves a one-to-one polygon assignment
after canonicalizing each polygon under cyclic and reversal vertex ordering.
Default mode requires both centered shape and centroid position equality.
`shape_only=True` ignores each polygon's centroid, which is the invariant
needed to prove that a local displacement moved rigid motifs without changing
their shape.

## Real MPB response

For every downstream and every amplitude in
`{0,+0.005,-0.005,+0.0025,-0.0025}`, the closure driver invokes the real
`meep.mpb.ModeSolver`, records raw frequencies and `RawSpectrum` provenance,
and calls `qualify_differential_maxwell_response`. No response is calculated
from an archived response JSON.

The qualification is valid only after semantic identity matching, band
assignment, the R6.1 local gap/delta guard, and the downstream convergence
bound. A non-converged downstream may have raw MPB data but cannot receive a
`PASS_DIFFERENTIAL` claim.
