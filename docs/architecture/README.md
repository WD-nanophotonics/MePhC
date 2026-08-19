# MePhC architecture index

This directory is an evidence archive, not the active implementation tree.

## Authority order

1. The current Git `main` commit and its `mephc/` source package are the active implementation baseline.
2. The current test suite under `tests/` is the executable contract for the package.
3. `mephc_affine_architecture_r21/` is the latest sealed scientific evidence bundle. Its `completion.json` records `seal_status: SEALED` and `r22_authorized: false`.
4. `mephc_affine_architecture_r1` through `r20` are historical, immutable evidence bundles. Their blocked or closed terminal states describe those rounds and must not be treated as current implementation instructions.

The recent E1 and E2 solver-neutral kernels live in the active package and tests, not in a new architecture archive. Do not copy historical scripts or generated evidence into `mephc/` or `tests/`.

## What belongs where

- Reusable implementation: `mephc/`.
- Executable regression tests: `tests/`.
- Small user-facing examples: `examples/`.
- Historical scientific evidence: `docs/architecture/mephc_affine_architecture_r*/`.
- Old flat reference scripts: local ignored `legacy/`; they are excluded from packaging and are not part of the active API.
- Project-specific records, images, MPB caches, and diagnostics belong in TriLatt or SqrLatt, not in this repository.

## Clean-worktree rule

Only tracked source, tests, documentation, and intentional evidence artifacts belong in Git. `.pytest_cache/`, `__pycache__/`, and other generated caches are disposable and ignored. They must never be used as source inputs or copied between worktrees.

For normal work use only:

```text
WSL /home/icy/MePhC
WSL /home/icy/miniconda3/envs/mp/bin/python
```

Windows Python is reserved for Gmail Courier transport; it is not a second MePhC development environment.

