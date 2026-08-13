# R7.2 response contract

## Sign equivalence

For each downstream, the realized `+A` geometry is translated by one of the
declared primitive lattice vectors and wrapped into the 2x2 supercell. The
translated polygon set must match `-A` under polygon-set equivalence. The
matching records the translation and assignment; direct absolute equality is
not substituted for periodic equivalence.

At each resolution, the `+A` and `-A` `RawSpectrum` for each q point must be
equivalent after band assignment within the declared spectral tolerance. A
failed sign check blocks the downstream response claim.

## Differential-resolution ladder

Fresh `meep.mpb.ModeSolver` spectra are generated for every amplitude and each
resolution in `{8,12,16}`. For each point/band record, R7 differential odd/even
coefficients are compared between 8→12 and 12→16. A comparison passes when
each coefficient difference is below
`max(absolute_tolerance, relative_tolerance*|high_resolution_value|)`.

The first high resolution with a passing adjacent comparison is the accepted
resolution. A downstream is not closure-qualified if no comparison passes,
even if one isolated resolution produces an apparently large response.
