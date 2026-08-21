# E7I.1G C4 audit surface

The compact solver-neutral C4 surface consists of `geometry_generator.py`,
`trace_generator.py`, `reducer_c4.py`, and the inspectable
`mpb_batch_worker.py`. Large manifests, meshes, and solver logs remain
external.

The superseded q-only C4 cache and batch executors are absent from the current
tip; their historical implementations remain available through Git history.
The current identity-safe planning and C5 corrective surface are documented in
`C5_README.md`.

The older C1/C3 execution scripts remain available in Git history as
provenance. They are not current conclusion-producing entry points.
