# R8 Validation Report

Status: `PASS_R8_EVIDENCE_VALIDATOR`.

The authoritative contract SHA and locked starting refs were verified. The 2x2 rigid-center obstruction was proven by finite geometry regression with zero MPB calls. The 3x1 benchmark passed the full typed polygon/material gate for all six enumerated point-operation/translation candidates: no sign-equivalent candidate matched at 1e-10.

The immutable baseline freeze contains only A=0 spectra at resolutions 12, 16, and 20, with exactly two isolated active targets selected at each of q1, q2, and q3. The response phase executed 15 real `meep.mpb.ModeSolver` calls and preserved the frozen target list. Band identity guards and both full/half odd differential convergence checks passed for all six targets.

Scientific terminal state: `BLOCKED_ODD_RESPONSE_UNRESOLVED`. All six odd signals remained below the required 5-times-final-error and absolute-signal thresholds, so no resolved target was counted. This is a contract-compliant adjudication; the inherited R7.4 numerical-floor reference was recorded diagnostically and was not used to relax the R8 convergence or resolvability rules.

TriLatt received no production change and no fresh solver call. No completion Gmail was sent.
