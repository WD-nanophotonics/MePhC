# MePhC Affine Architecture R6.1

This bundle records the corrected local-deformation benchmark and the band-local response gate.

The authoritative benchmark is
`u_A(xi1,xi2)=A*cos(2*pi*xi1)*cos(2*pi*xi2)*e_x`
on fractional coordinates of the 2x2 supercell. At the row-major sites
`(0,0),(0,1),(1,0),(1,1)`, the realized x-center displacement is
`[+A,-A,-A,+A]`.

R6.1 keeps the R6 runtime lock, real `meep.mpb.ModeSolver`, TE polarization,
q0/q1/q2 generic points, six bands, and the fixed 8/12/16 ladder. Eligibility
is band-local: `delta_max(b)` is computed only from the same band across the
four nonzero amplitudes.

The realized geometry gates pass for both SqrLatt and TriLatt. SqrLatt passes
the protected zero ladder at resolution 12, has non-identical raw spectra for
the five amplitudes, and records the band-local response. TriLatt reproduces
the protected zero ladder, but remains BLOCKED_NONCONVERGED under the fixed
8/12/16 ladder; no full five-amplitude TriLatt sweep was performed.

This is an evidence bundle, not a replacement for the protected R6 bundle.
The old R6 files remain byte-for-byte protected.
