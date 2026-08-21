# E7I.1G/C1 audit provenance

The C1 result was generated outside the repository in the Windows staging
project. The files under `executed/` are byte-for-byte copies of the scripts
used by that run, including the wrapper substitutions that selected the fixed
coordinate geometry and fixed result directory. They are preserved for direct
inspection; they are not presented as a cleaner reimplementation.

## Executed conclusion-producing paths

| Repository path | Role | Exact executed version | Inputs | Outputs / command |
| --- | --- | --- | --- | --- |
| `executed/e7i1g_c1_exact_geometry.py` | Exact Voronoi-piece clipping and triangulation | Yes, initial geometry construction | `.e7i1g_geometry.json` | `.e7i1g_c1_exact_geometry.json` |
| `executed/e7i1g_c1_fix_geometry_coords.py` | Correct absolute-q versus K-offset coordinate provenance | Yes | initial exact geometry | `.e7i1g_c1_exact_geometry_fixed.json` |
| `executed/e7i1g_c1_quadrature_supervisor_v2.py` | Centroid/three-point plans, deduplication, worker execution, qualification aggregation | Yes, executed through the wrapper | fixed exact geometry, base geometry, prior E7I.1G manifest | fixed C1 manifest |
| `executed/e7i1g_c1_run_corrected.py` | Exact runtime wrapper selecting fixed geometry and fixed output directory | Yes | supervisor v2 | corrected C1 run |
| `executed/e7i1g_c1_coarse_supervisor.py` | Coarse centroid point generation and aggregation | Yes | base geometry and E7I.1G evidence | coarse centroid aggregate |
| `executed/e7i1g_c1_analysis2.py` | Flux reduction, convergence, hybrid metric, seam/inversion pairing, eligibility classification | Yes, executed through the wrapper | fixed C1 manifest, geometry, coarse aggregate, original evidence | C1 analysis JSON |
| `executed/e7i1g_c1_run_analysis_corrected.py` | Exact analysis wrapper selecting fixed inputs and corrected seam pairing | Yes | analysis2 | corrected C1 analysis JSON |
| `executed/e7i1b_point_worker.py` | MPB point solve and local qualification record | Yes | one q point and fixed solver parameters | per-point result records |
| `executed/repair_c1_incomplete_v3.py` | Re-runs and records the one missing final point | Yes | fixed C1 manifest | repaired fixed C1 manifest |

The full raw fixed manifest is intentionally not committed (235 MB). Its
SHA-256 was `285bd52f46917a7a74af1bca3d60d10194c37076d4787e4ea4e6d55fd52d36f8`.
The base geometry fixture is committed because it is small enough to inspect;
the compact aggregate fixture and replay script preserve the reduction
anchors without archiving raw point payloads.

## Provenance qualification

`C1_IMPLEMENTATION_PROVENANCE=COMPLETE_WITH_DOCUMENTED_RECONSTRUCTION`.
The exact executed scripts are present, while the solver-neutral replay uses
compact stored aggregates rather than the omitted raw payload.

## Single-point repair

The initial supervisor serialized a negative scientific-notation q coordinate
as a separate argparse value. That child exited before an MPB result record
was produced; the failure was argument serialization, not service failure,
numerical qualification, or a post-result transport failure. A direct point
rerun using the corrected `--qx=<value>` form produced `QUALIFIED_VALUE`, and
the final manifest records it as `REPAIRED_SINGLE_POINT`.

Thus the narrow `runtime_failures=0` count remains true for MPB runtime
failures, but the original report should also have stated
`argument_serialization_failures=1`, `initial_fresh_solved=39519`, and
`repaired_physical_points=1`. Because a physical rerun was required, the
classification is `SINGLE_POINT_REPAIR_CLASSIFICATION=NUMERICAL_RERUN_REQUIRES_CORRECTIVE`.
