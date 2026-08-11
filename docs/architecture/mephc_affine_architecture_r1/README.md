# MePhC Affine Architecture R1.1 Corrective

This is a corrective completion round for R1. It adds only audit artifacts,
characterization tests, a deterministic validator, and machine-readable
delivery metadata. It does not change production/runtime code, scientific
records, images, diagnostics, or start R2.

## Preflight

| Repository | Branch/upstream | HEAD before | Dirty before |
|---|---|---|---|
| MePhC | `main` / `origin/main` | `ec8a4ec8ec1ffd5db01e60c5e008a2af67c50ffb` | false |
| MePhC-TriLatt | `main` / `origin/main` | `38f1c66ec2c0eb441a5fc5dbd440c2f45eec919c` | false |
| MePhC-SqrLatt | `main` / `origin/main` | `8a1e4534a48e01a83996fb199ccd55e0983e72b2` | false |

The reviewed parent commit is an ancestor of current MePhC HEAD. The WSL
environment is `/home/icy/miniconda3/envs/mp/bin/python`, Python 3.13.13,
with Meep, MPB, NumPy, SciPy, Shapely, and Matplotlib available.

## Reproducibility commands and observed results

Commands are shown with their observed exit code and test counts. The SqrLatt
baseline command is recorded as a pre-existing discovery gap, not a new test
failure.

| Phase | Command | Exit | Result |
|---|---|---:|---|
| preflight | `git -C /home/icy/MePhC merge-base --is-ancestor ec8a4ec8ec1ffd5db01e60c5e008a2af67c50ffb HEAD` | 0 | reviewed commit contained |
| baseline | `/home/icy/miniconda3/envs/mp/bin/python -m unittest discover -s /home/icy/MePhC/tests` | 0 | 8 passed, 0 failed, 0 skipped, 0 xfailed, 0.003 s |
| baseline | `/home/icy/miniconda3/envs/mp/bin/python -m unittest discover -s /home/icy/TriLatt/tests` | 0 | 22 passed, 0 failed, 0 skipped, 0 xfailed, 0.269 s |
| baseline | `/home/icy/miniconda3/envs/mp/bin/python -m unittest discover -s /home/icy/SqrLatt/tests` | 1 | no importable tests directory |
| focused | `PYTHONPATH=/home/icy/MePhC /home/icy/miniconda3/envs/mp/bin/python -m unittest discover -s /home/icy/MePhC/tests` | 0 | 18 passed, 0 failed, 0 skipped, 0 xfailed, 0.010 s |
| compile | `/home/icy/miniconda3/envs/mp/bin/python -m compileall -q /home/icy/MePhC/mephc /home/icy/MePhC/tests` | 0 | compiled |
| validator | `/home/icy/miniconda3/envs/mp/bin/python /home/icy/MePhC/tests/validate_affine_r1_1.py` | 0 | all artifact/integrity checks passed |
| hygiene | `git -C /home/icy/MePhC diff --check` | 0 | clean |

## Lock result

LOCK-01 through LOCK-06 and LOCK-08 through LOCK-10 are locked by executable
tests. LOCK-07 is blocked: TriLatt has `auto -> c3`, but SqrLatt currently
sets `symmetry = "c4q"` explicitly in its case script. There is no existing
geometry-driven C4 auto-selection to characterize, and adding one would be a
forbidden production change in R1.1. Therefore the overall status is
`blocked`, accurately reflecting the contract rather than weakening it.

## Artifact index

- `README.md`
- `current_architecture.md`
- `dependency_graph.mmd`
- `api_inventory.csv`
- `lattice_truth_sources.csv`
- `symmetry_assumptions.csv`
- `behavior_baseline.json`
- `characterization_matrix.md`
- `migration_contract.md`
- `open_questions.md`
- `artifact_manifest.json`
- `completion.json`

Test support is outside the artifact root in `tests/test_affine_characterization.py`
and `tests/validate_affine_r1_1.py`. The manifest covers these support files.
The manifest excludes itself and `completion.json`: completion records the
manifest hash, so including both raw files would create a recursive hash
cycle. This reverse-reference exclusion is explicit and validator-enforced.

## Known limitation and stop condition

No R2 implementation is included. The corrective branch must stop until a
future task decides whether C4 should be a verified full-structure property or
an explicit user declaration. Existing runtime and scientific evidence remain
byte-identical.
