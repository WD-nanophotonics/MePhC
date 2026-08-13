# R7.2 validation report

Status: `PASS_R7_2_SIGN_EQUIVALENCE_DIFFERENTIAL_LADDER`

The closure was generated with the locked `mp` interpreter and real `meep.mpb.ModeSolver` at resolutions 8, 12, and 16. The signed amplitudes were `0`, `+/-0.005`, and `+/-0.0025`; every downstream and q-point has explicit raw provenance in the supercell Brillouin-zone semantic domain.

Sign equivalence is closed in two independent layers. The realized downstream geometries match under declared periodic translations: SqrLatt `[1.0, 0.0]` and TriLatt `[0.5, 0.8660254037844386]`. The resulting +A/-A spectra also match at all three q-points and all three resolutions, with semantic identity preserved.

The differential-resolution ladder accepts SqrLatt at resolution 12: the 8→12 maximum difference is `0.0010497498031782904`, below the `0.002` absolute tolerance, and 12→16 also passes. TriLatt is fully recorded but remains `BLOCKED_DIFFERENTIAL_NONCONVERGED` (`0.017135961465184868` maximum on 8→12 and `0.010854384093676783` on 12→16); no TriLatt response claim is made.

Protected R6/R6.1 inputs remain unchanged. No MPB result outside this R7.2 evidence directory was overwritten, and no email was sent.
