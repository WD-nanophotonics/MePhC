# Root cause and residual-data audit

The original R6 benchmark used
`A*sin(2*pi*xi1)*sin(pi*xi2)^2*e_x`. At all four 2x2 motif sites this field
is zero, so the downstream realized polygons were unchanged even when the
amplitude metadata changed. That made the old raw spectra identical across
the amplitude sweep and allowed a geometry/data disconnect to pass unnoticed.

R6.1 corrects the field to
`A*cos(2*pi*xi1)*cos(2*pi*xi2)*e_x`, and checks realized downstream polygon
centers, rigid shape invariants, boundary verification, Jacobians, sign, half
scaling, and distinct geometry fingerprints before solving.

The protected TriLatt R6 artifact also contains a reproducibility anomaly:
at q2/resolution 8 its stored bands 5/6 are approximately 0.293056/0.293574,
while a fresh locked-ref solve exposes the intermediate band near 0.28457 and
then 0.29306. At q2/resolution 12, fresh solves can reproduce the protected
branch only after bounded MPB retry because a nearly-degenerate subspace is
initialized differently. R6.1 does not rewrite or silently reinterpret the R6
artifact. The bounded replay records this solver-branch sensitivity without
rewriting the protected evidence. TriLatt reproduces the zero ladder, while
the fixed ladder still yields BLOCKED_NONCONVERGED, so no full response sweep
is claimed.
