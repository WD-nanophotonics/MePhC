# MePhC Affine Architecture R7

## Equivalence-aware differential Maxwell response qualification

R7 extends the R6.1 band-local response gate with an explicit spectral
equivalence layer. A solver may return the same Maxwell eigenvalue set in a
different band order; that relabeling is not a physical response.

The R7 workflow is:

1. Verify the semantic identity of the zero and perturbed spectra: q point,
   solver, resolution, polarization, replication, and band count must agree.
2. Find the minimum-cost one-to-one frequency assignment between the baseline
   and each perturbed spectrum.
3. Map every perturbed spectrum into baseline band order.
4. Apply the R6.1 band-local gap and `delta_max` guard to the mapped target band.
5. Report central odd/even Maxwell differences only after matching.

If the target band is numerically equivalent to baseline at every amplitude,
the result is `EQUIVALENT_NULL` and `qualified=false`. A pure permutation can
never qualify as a differential physical response. A genuine matched shift can
return `PASS_DIFFERENTIAL` subject to the existing R6.1 gap and convergence
guards.

The public implementation is in `mephc.r7_response` and is also available
through lazy top-level package exports.
