# R5 validation report

The R4.1 bundle-only validator passed before writes. The new MePhC kernel
tests ran 5/5, TriLatt R5 tests ran 2/2, and SqrLatt R5 tests ran 2/2 using
the bundled NumPy runtime. Compile checks passed for all new Python modules.

The real MPB supercell smoke is explicitly blocked because the available
runtime has no `meep`/`mpb`; the implementation does not mislabel an
aperiodic field to obtain a green solver result. Existing R4/R4.1 artifacts
and scientific data were not regenerated or modified.
