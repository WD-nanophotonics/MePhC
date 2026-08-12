# MePhC Affine Architecture R5.1

R5.1 closes the existing-runtime MPB smoke gap without changing the sealed R5
bundle or starting R6. The accepted R4 control and both downstream real
periodic-supercell smokes use `/home/icy/miniconda3/envs/mp/bin/python`.

The required starting refs are recorded in `preflight.json`. Final refs are
authoritatively recorded in `completion.json` after the payload and metadata
seal commits. The only production correction is the allowed TriLatt R5
pattern normalization in `r5_deformation.py`; MePhC production code and
SqrLatt production code are unchanged.

The smoke fixture is a deterministic nonzero spatial wave declared periodic
on a 2x2 integer supercell. Both downstream integrations create the rigid
replicated motif through the shared MePhC R5 field authority. Each smoke runs
real `meep.mpb.ModeSolver` at Gamma with resolution 2 and one band. Primitive
K/M/X labels, primitive symmetry reduction, unfolding, Berry, and EFS
interpretation are explicitly disabled.

See `solver_smokes.json`, `validation_report.md`, and `logs/` for the exact
commands, runtime origins, numerical shapes, and complete logs.
