# MePhC Affine Architecture R7.1

## Contract recovery: geometry equivalence and real differential MPB closure

R7.1 closes two gaps left by R7:

1. realized polygon geometries are compared as sets, independent of polygon
   order and cyclic/reversed vertex order; absolute equivalence and centered
   shape equivalence are reported separately;
2. the differential response is generated from fresh `meep.mpb.ModeSolver`
   runs at every fixed ladder amplitude, then converted to `RawSpectrum` and
   passed through R7 equivalence-aware matching.

The zero-amplitude geometry must be absolutely equivalent to the legacy
geometry. Every ladder geometry must remain shape-equivalent while nonzero
amplitudes must have distinct absolute geometry. A pure band permutation is
removed before calculating odd/even differences.

SqrLatt is the closure-eligible downstream when its fixed resolution-12
convergence gate passes. TriLatt real spectra are recorded for audit, but its
response remains non-qualified when the protected fixed 8/12/16 convergence
contract is blocked. This does not reinterpret primitive bands or add
topological/Berry/transport claims.
