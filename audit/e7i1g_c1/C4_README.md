# E7I.1G C4 audit surface

The current audit entry points are deliberately small and solver-neutral:

- `geometry_generator.py` defines the exact K-point Voronoi pieces and emits
  coarse, fine, and refined in-memory meshes with a common domain.
- `trace_generator.py` converts external execution evidence into ordered,
  chunked, count/weight/flux-closed trace records.
- `reducer_c4.py` validates the trace and recomputes periodicity and inversion
  controls from raw pair records.
- `c4_execution.py`, `c4_batch_execution.py`, and `mpb_batch_worker.py` are
  inspectable execution helpers. Their large manifests and generated meshes
  belong outside the repository.

The older C1/C3 execution scripts remain available in Git history as
provenance. They are not the current C4 conclusion-producing entry point.
