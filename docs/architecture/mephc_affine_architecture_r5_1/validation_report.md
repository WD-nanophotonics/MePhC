# R5.1 validation report

Selected runtime: `/home/icy/miniconda3/envs/mp/bin/python`.

The default `/usr/bin/python3` was rejected because it has no Meep module. The
selected runtime imports real Meep and `meep.mpb.ModeSolver`; no package,
environment, driver, compiler, or system change was made.

## Commands and results

- `python3 docs/architecture/mephc_affine_architecture_r4_1/validate_r4_1.py --check-bundle --bundle-root docs/architecture/mephc_affine_architecture_r4_1` — PASS.
- `python3 docs/architecture/mephc_affine_architecture_r5/validate_r5.py --check-bundle --bundle-root docs/architecture/mephc_affine_architecture_r5` — PASS.
- R4 control: `PYTHONPATH=/home/icy/MePhC:/home/icy/SqrLatt /home/icy/miniconda3/envs/mp/bin/python docs/architecture/mephc_affine_architecture_r4/run_r4_smokes.py` — PASS, 5/5 real MPB smokes.
- MePhC full suite — PASS, 38 tests.
- SqrLatt full suite — PASS, 28 tests.
- TriLatt full suite — PASS, 30 tests.
- R5.1 driver — PASS, 2/2 real supercell MPB smokes.
- `compileall` and import checks — PASS.
- `validate_r5_1.py --check-bundle` — PASS after metadata seal.

The only production correction was the narrow TriLatt conversion of layered
pattern data to the shared one-layer polygon representation before rigid R5
replication. No MePhC production code or SqrLatt production code changed.
