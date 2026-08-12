# R6 response contract

The response layer stores value-semantic generic supercell q points, solver settings, raw ordered spectra, fixed-ladder convergence evidence, eligibility guards, sign-reversal algebra, and deterministic fingerprints.

Production path: canonical geometry authority -> verified PeriodicSupercellField -> downstream supercell adapter -> MePhC Band.run_supercell -> real meep.mpb.ModeSolver -> raw spectra -> shared response algebra.

No primitive high-symmetry labels, symmetry reduction, unfolding, Berry/BCD, EFS, transport, or far-field interpretation is attached. Raw spectra precede eligibility filtering.

