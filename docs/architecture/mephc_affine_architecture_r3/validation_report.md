# R3 Validation Report

The accepted baselines were MePhC `690a543e33967fc449fd7d3b28d9c30a07b1a848`
and TriLatt `5d84f992310fbe0141df811704a9ffb3811807cb`.

- MePhC full suite: 29 passed.
- TriLatt full suite with `PYTHONPATH=/home/icy/MePhC`: 26 passed.
- R2 artifact validator: passed.
- Nonidentity MPB smoke: factor 1.05, angle 30 degrees, resolution 2;
  band generic-BZ `(8, 1)`, Berry first-BZ `(7, 1)`, EFS first-BZ `(7, 1)`.
- R3 artifact validator: run after manifest generation.

The historical R1.1 runtime-tree validator fails because it expects the
pre-R2 runtime tree; R1.1 artifacts remain byte-identical. SqrLatt was checked
read-only and remains byte-identical.
