# E7I.1G/C1-C4 audited implementation provenance

The historical C1 execution was preserved by sandbox commit
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

The C3 sandbox audit commit
`b5133abff5cb7543dafc1dee44ee0e10fd3a8bbd` is also preserved as history. Its
Gamma reclassification and compact controls remain audit evidence, while the
C4 current tip replaces its large generated geometry and weak reducer entry
points with the compact C4 surface.

C4 manifest lineage is explicit:

- `7485db568bd83058d536d70f535743345d924559af1fe0d1ba4845fb706a32a9` is the
  pre-C1 coarse/fine legacy manifest with incomplete-domain geometry.
- `285bd52f46917a7a74af1bca3d60d10194c37076d4787e4ea4e6d55fd52d36f8` is the
  corrected exact-domain C1 manifest after coordinate correction and the one
  recorded serialization repair.

C4 reuses the corrected cache only on exact sample identity. Fresh C4 child
results are recorded in an external authoritative evidence artifact; the
structured trace records that artifact's single SHA-256 as its source digest.
The old legacy hash is retained only to explain lineage and is never treated as
the C4 source.

The current C4 audit surface is:

- `geometry_generator.py`: compact exact Voronoi specification and deterministic
  same-domain midpoint meshes;
- `trace_generator.py`: ordered chunk trace with record-digest, count, weight,
  qualified-count, and flux closure;
- `reducer_c4.py`: fail-closed reduction, raw-pair periodicity and inversion
  recomputation, and Gamma classification;
- `c4_execution.py`, `c4_batch_execution.py`, and `mpb_batch_worker.py`:
  inspectable bounded execution helpers.

The full generated meshes, raw manifests, and solver logs remain outside the
repository. No current tracked file contains machine-specific absolute paths,
credentials, or private workflow details.

`C1_IMPLEMENTATION_PROVENANCE=COMPLETE_WITH_DOCUMENTED_RECONSTRUCTION`.
`HISTORICAL_EXECUTION_PROVENANCE=PRESERVED`.
`C4_CURRENT_SURFACE=COMPACT_GENERATOR_TRACE_AND_FAIL_CLOSED_REDUCER`.
