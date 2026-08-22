# E7I.1G C8 perturbed-node quadrature audit

C8 treats the historical integral as:

`sum_i WEIGHT_i * Omega(EVALUATED_Q_i)`

with NOMINAL_Q, EVALUATED_Q, DELTA_Q, weight, and complete physical identity
stored separately. It never relabels EVALUATED_Q as NOMINAL_Q.

The implementation in `c8_perturbed_nodes.py` accepts a per-record evidence
file using the existing `rules -> rows -> result` shape. It validates all
50,688 records, closes each rule's signed weight to `1/sqrt(3)`, computes
weighted node-displacement moments, handles correlated evaluated-coordinate
alias reuse, applies the fixed C7 `L_guard = 10 * L_emp` guard, and binds a
compact per-rule provenance digest.

The committed C7 trace is intentionally compact and contains chunk digests,
not per-record coordinate associations. Running C8 without a per-record
evidence file therefore returns `ASSOCIATION_INCOMPLETE`,
`PERTURBED_NODE_ERROR=NOT_COMPARABLE`, and fail-closed broad-recomputation
status. This is evidence insufficiency, not a physical conclusion.

No MPB is run by this audit.
