# Affine Architecture R8

This bundle is the authoritative evidence record for the R8 minimal sign-inequivalent 3x1 periodic-supercell benchmark. The benchmark uses the locked MePhC runtime and the real `meep.mpb.ModeSolver` through the SqrLatt adapter.

Execution order is intentional:

1. verify the authoritative contract and starting refs;
2. prove the 2x2 rigid-center obstruction without a solver call;
3. verify the 3x1 geometry, periodicity, Jacobian, and full typed polygon comparison;
4. run and freeze the A=0 baseline at resolutions 12, 16, and 20;
5. run the prescribed signed amplitudes only after the freeze commit;
6. validate band identity, odd response, differential convergence, and target resolvability.

The frozen target list is selected from the A=0 spectra only: the lowest two isolated active band ordinals at each of q1, q2, and q3. Response data cannot change that list. The response quantity is the signed finite difference between the paired positive and negative amplitudes; the half-amplitude pair is a convergence diagnostic.

This record is evidence-first. It does not modify the public MePhC API, does not change SqrLatt or TriLatt production code, and does not install or mutate the runtime environment.
