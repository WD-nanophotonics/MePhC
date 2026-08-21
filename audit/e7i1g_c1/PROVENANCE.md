# E7I.1G/C1 audited implementation provenance

The historical C1 execution was preserved by the prior sandbox commit
`89972eaffaca03fb57c3cc5144c3e82c0b35df9d`, whose parent is the accepted main
baseline `ef558e87f905d5a436624267af8661de764ae3e0`. The historical commit
contains the exact copies of the geometry builder, coordinate-fix script,
quadrature supervisor, execution wrapper, coarse supervisor, analysis reducer,
analysis wrapper, point worker, and single-point repair script used for C1.

The historical analysis wrapper applied source substitutions for the fixed
geometry/result directories, corrected the deduplicated seam counterpart, and
deferred a self-reference in the classification dictionary. This fact is
retained; the historical scripts are not silently presented as a clean
implementation.

The current tip uses sanitized, deterministic public code under:

- `audit/e7i1g_c1/reducer.py`
- `audit/e7i1g_c1/reducer_geom.py`
- `audit/e7i1g_c1/tests/test_reducer.py`
- `audit/e7i1g_c1/fixtures/control_evidence.json`
- `audit/e7i1g_c1/fixtures/reduction_trace.json`
- `audit/e7i1g_c1/fixtures/exact_geometry_fixed.json`

No current tracked file contains machine-specific absolute paths, credentials,
or private workflow details. The 235 MB raw manifest remains outside the
repository. Its source SHA-256 is
`7485db568bd83058d536d70f535743345d924559af1fe0d1ba4845fb706a32a9`.

The reduction trace was extracted from that manifest and contains rule-level
sample counts, triangle counts, qualified counts, signed weight sums,
weighted curvature sums, resulting fluxes, and the source manifest digest.
The compact control fixture contains all 25 resolution pairs, all 12 seam
pairs, all 8 inversion pairs, three recorded Gamma controls, and orientation
metadata. It contains no raw field arrays.

`C1_IMPLEMENTATION_PROVENANCE=COMPLETE_WITH_DOCUMENTED_RECONSTRUCTION`.
`HISTORICAL_EXECUTION_PROVENANCE=PRESERVED`.
