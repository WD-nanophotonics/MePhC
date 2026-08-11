# MePhC Affine Architecture R1

This directory is the R1 audit and characterization package for the MePhC
family. It records the current architecture of `MePhC`, `MePhC-TriLatt`, and
`MePhC-SqrLatt` without changing production/runtime source code.

## Scope

R1 is a baseline audit and a set of executable characterization locks. It
does not implement affine deformation, does not replace the current solver
or record workflow, and does not start the R2 migration.

The audit covers:

- direct-space lattice bases, motif construction, and normalized geometry;
- MPB lattice construction and Cartesian/MPB coordinate conversion;
- reciprocal-space paths, grids, Brillouin-zone domains, and symmetry helpers;
- MPB solver and observable adapters for bands, Berry curvature, and EFS;
- records, cache identity, plotting, previews, and case-level orchestration;
- public and semi-public APIs that R2 must preserve or deliberately replace.

## Files

- `current_architecture.md`: current layers, ownership, and coupling points.
- `dependency_graph.mmd`: current dependency graph in Mermaid syntax.
- `api_inventory.csv`: symbol-level API inventory and migration risk.
- `lattice_truth_sources.csv`: competing physical truth sources.
- `symmetry_assumptions.csv`: current symmetry assumptions and boundaries.
- `behavior_baseline.json`: repository refs, environment, and baseline results.
- `characterization_matrix.md`: executable locks and expected behavior.
- `migration_contract.md`: R1 invariants and the proposed R2 boundary.
- `open_questions.md`: unresolved questions that must not be hidden by R2.
- `artifact_manifest.json`: SHA-256 manifest and completion metadata.

## Reproduction

Use `/home/icy/miniconda3/envs/mp/bin/python` from the WSL environment. The
characterization tests are in `tests/test_affine_characterization.py` and are
deliberately test-only. Existing TriLatt tests were also run as a baseline;
MePhC and SqrLatt currently have no discoverable `tests/` directory.
