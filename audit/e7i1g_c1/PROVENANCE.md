# E7I.1G/C1-C5 audited implementation provenance

The historical C1 execution is preserved by sandbox commit
`89972eaffaca03fb57c3cc5144c3e82c0b35df9d`; C3 is preserved by
`b5133abff5cb7543dafc1dee44ee0e10fd3a8bbd`. Their generated artifacts and
execution scripts are provenance, not current entry points.

The accepted main baseline is `ef558e87f905d5a436624267af8661de764ae3e0`.
The current sandbox tip contains the compact exact-domain C4 reducer and the
C5 identity-safe corrective. The large generated evidence and MPB logs remain
outside the repository.

Current C4/C5 audit components:

- `geometry_generator.py`, `trace_generator.py`, and `reducer_c4.py` define the
  compact exact-domain geometry, trace, and solver-neutral reduction;
- `mpb_batch_worker.py` is the inspectable bounded solver worker;
- `sample_identity.py`, `identity_cache.py`, and `c5_execution.py` bind reuse
  to the complete physical identity and fail closed on disagreeing collisions;
- `reducer_c5.py`, `run_c5_reduction_v2.py`, and `trace_generator_c5.py` enforce
  strict qualification, predeclared R64 sentinel scaling, and trace lineage.

The superseded q-only `c4_execution.py` and `c4_batch_execution.py` cache
implementations are intentionally absent from the current tip. Their
historical copies remain in Git history for auditability only.

`C1_IMPLEMENTATION_PROVENANCE=COMPLETE_WITH_DOCUMENTED_RECONSTRUCTION`.
`HISTORICAL_EXECUTION_PROVENANCE=PRESERVED`.
`C4_CURRENT_SURFACE=COMPACT_GENERATOR_TRACE_AND_FAIL_CLOSED_REDUCER`.
`C5_IDENTITY_SURFACE=COMPLETE_IDENTITY_AND_FAIL_CLOSED_COLLISION_POLICY`.

`C6_CURRENT_SURFACE=EXACT_Q_PROVENANCE_AND_SELF_VERIFYING_TRACE`.
`C6_PHYSICAL_SEAL=PENDING_DUE_TO_STORED_Q_PROVENANCE_MISMATCH`.

`C7_CURRENT_SURFACE=NOMINAL_EVALUATED_COORDINATE_SEMANTICS_AND_IMPACT_AUDIT`.
`C7_PHYSICAL_SEAL=PENDING_DUE_TO_UNRESOLVED_HISTORICAL_MAPPING`.
