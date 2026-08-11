# MePhC Affine Architecture R3

R3 activates one global, periodic 2-D affine deformation for MePhC-TriLatt.
The supported model is `A' = F A`, with local polygon shape and material
unchanged. The R2 baselines are MePhC `690a543e33967fc449fd7d3b28d9c30a07b1a848`
and TriLatt `5d84f992310fbe0141df811704a9ffb3811807cb`.

Implementation refs: MePhC `bbb27e5`; MePhC-TriLatt `df2cdf4`.
Environment: `/home/icy/miniconda3/envs/mp/bin/python`, Python 3.13.13,
NumPy 2.4.6, Meep/MPB available. Identity behavior remains on the legacy
path; nonidentity triangular data uses the current reciprocal basis and a
reconstructed Wigner-Seitz BZ. C3/HBZ/GKM are guarded identity capabilities.

Validation commands and results are recorded in `validation_report.md` and
`test_coverage_matrix.csv`. R3 does not modify SqrLatt, scientific records,
or R1/R2 artifacts. This delivery stops after push for independent review.
