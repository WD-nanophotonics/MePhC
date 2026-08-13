# R7 response contract

For a baseline spectrum `w(0)` and the fixed ladder
`{+A,-A,+A/2,-A/2}`, R7 computes a one-to-one assignment `P_a` minimizing

`sum_b |w_b(0) - w_{P_a(b)}(a)|`.

The assignment is valid only when both raw spectra have the same semantic
identity. For `RawSpectrum`, identity includes q-point, solver, resolution,
polarization, replication, and band count. The amplitude itself is excluded so
the five ladder members can be compared.

After assignment, `w^mapped_b(a)=w_{P_a(b)}(a)`. The R6.1 guard is applied to
`delta_max(b)=max_a |w^mapped_b(a)-w_b(0)|` and the same nearest-neighbor gap.
The central Maxwell response is

`odd_A=(w^mapped_b(+A)-w^mapped_b(-A))/2`,

`even_A=(w^mapped_b(+A)+w^mapped_b(-A))/2-w_b(0)`.

Statuses:

- `PASS_DIFFERENTIAL`: semantic identity, matching, convergence, gap, and
  perturbation guards pass and the target band has a non-null matched shift.
- `EQUIVALENT_NULL`: the target band is equivalent to baseline within the
  declared tolerance for the whole ladder; `qualified` is false.
- `BLOCKED_SEMANTIC_IDENTITY`: q point or solver semantics differ.
- `BLOCKED_INELIGIBLE`: the mapped response fails the existing R6.1 guard.
