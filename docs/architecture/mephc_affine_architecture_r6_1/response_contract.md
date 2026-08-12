# R6.1 response contract

Raw spectra are recorded before eligibility filtering. For band ordinal b:

`delta_max(b)=max_{a in {+A,-A,+A/2,-A/2}} |omega_b(a)-omega_b(0)|`.

The nearest-neighbor gap is computed from the same baseline band only. A band
is eligible only when the baseline is above 1e-8, the gap is greater than
max(0.005, 5*convergence_error), and delta_max is strictly below 0.25 times
that gap. Cross-band pooling is forbidden.

SqrLatt may proceed only after geometry gates and zero-ladder reproduction pass.
TriLatt must preserve BLOCKED_NONCONVERGED when the zero ladder reproduces but
does not converge; in this realization it is even earlier blocked by the
protected-artifact reproducibility anomaly. No full TriLatt sweep is included.

No R6 evidence is modified. No R7 claim, primitive-band interpretation,
unfolding, topology, Berry/BCD, transport, or network installation is part of
this bundle.
