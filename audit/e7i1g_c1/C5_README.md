# E7I.1G C5 identity-safe corrective

C5 closes the cache-identity and trace-audit gaps identified after C4.  The
current tip is sandbox-only and does not authorize `main`.

`sample_identity.py` defines the complete physical reuse identity: q, valley,
domain radii, resolution, finite-difference step, representation, plaquette,
geometry, selected bands, and rank.  `identity_cache.py` indexes only by that
full identity and raises on disagreeing duplicate results.  `c5_execution.py`
is the current planning entry point; it permits fresh work only for samples
without an exact identity match.  The superseded q-only C4 executor is not
present in the current tip.

`reducer_c5.py` applies strict exact-domain qualification before reduction.
`run_c5_reduction_v2.py` uses the predeclared R64 sentinel median scale, and
`trace_generator_c5.py` binds the compact trace to the evidence and lineage
hashes.  The committed `fixtures/c4_reduction_trace.json` is the compact,
solver-neutral replay artifact; the large MPB evidence remains external.

Run the unit tests from this directory:

```text
<canonical mp environment> -m unittest discover -s tests -v
```
