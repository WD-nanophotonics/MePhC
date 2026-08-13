# R7.1 validation report

The R7.1 driver executed fresh `meep.mpb.ModeSolver` runs at resolution 12 for
all five amplitudes and all three generic supercell q points for SqrLatt and
TriLatt. Each record contains `RawSpectrum` provenance before qualification.

- SqrLatt geometry: PASS; real differential closure: PASS_REAL_MPB; 5 of 18
  point/band records passed the R7.1 differential gate.
- TriLatt geometry: PASS; 15 raw records and 18 qualification records were
  generated for audit, but the response claim remains false because the
  protected fixed 8/12/16 convergence contract is non-converged.
- zero geometry is absolutely equivalent to the legacy geometry for both
  downstreams;
- every ladder geometry is centered-shape equivalent while nonzero geometries
  are pairwise absolutely distinct;
- protected R6/R6.1 inputs were read only and not overwritten.
