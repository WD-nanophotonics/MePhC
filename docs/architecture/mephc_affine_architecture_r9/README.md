# Affine Architecture R9

R9 is the contract-first mechanism-adjudication record for the same 3x1 sign-inequivalent rigid-center deformation used in R8. It evaluates all 18 q/band channels without selecting new targets.

The workflow is fixed: reuse protected R8 resolution-20 records where authorized, run the prescribed signed amplitude ladder at resolutions 20, 24, 32, and 40, measure exact uniform-translation controls, and trigger the complete 48-resolution branch only when the 32-to-40 adjudication remains unresolved. Every solver call uses the locked Python runtime, real meep.mpb.ModeSolver, TE polarization, six ordinal bands, and tolerance 1e-7.

The analytic record is deliberately scoped to rigid translations of identical primitive motifs about the primitive-periodic A=0 structure. The three site shifts have zero mean, supporting the stated first-order diagonal cancellation within that scope. The period-3 momentum bookkeeping permits an odd cubic term but does not guarantee it; the measured high-resolution response and translation floor decide the terminal classification.

R8 remains immutable and remains a 0/6 scientific blocker. This bundle does not modify production code in any repository.
