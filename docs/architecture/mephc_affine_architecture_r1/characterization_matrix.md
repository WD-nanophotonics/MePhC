# Characterization Matrix

The executable locks are in `tests/test_affine_characterization.py`. They are
test-only and use the same MP kernel as the workflows.

| Lock | Current behavior | Test |
|---|---|---|
| direct triangular basis orientation | MPB basis columns are `(0.5,+sqrt(3)/2)` and `(0.5,-sqrt(3)/2)` | `test_triangular_and_square_direct_basis_are_explicit` |
| direct square basis parity | MPB basis columns are `(1,0)` and `(0,1)` | same test |
| reciprocal duality | direct basis transpose times reciprocal dual is identity; physical vectors use a `2*pi` scale | `test_direct_reciprocal_duality_and_two_pi_convention` |
| first-BZ geometry | triangular first BZ is the radius-`2/3` regular hexagon | `test_first_bz_geometry_and_high_symmetry_paths` |
| high-symmetry path | triangular Gamma-K-M-Gamma and square Gamma-X-M-Gamma use current Cartesian coordinates | same test |
| square regular grid | `N x N` includes both domain endpoints | `test_square_and_triangular_grid_sampling_contract` |
| C3 auto-selection | TriLatt default active triangular motifs select `c3` | `test_triangular_c3_auto_selection_uses_active_motif` |
| minimal square motif placement | SqrLatt default square hole is a centered four-gon | `test_square_case_motif_is_centered_and_geometry_id_is_physical_only` |
| record identity | task key is order-independent, task changes invalidate it, plot settings are outside the key | `test_record_identity_excludes_plot_parameters_but_keeps_task_parameters` |
| solver smoke | a low-resolution square one-band MPB solve returns a frequency | `test_one_low_resolution_solver_smoke` |

## Baseline observations

TriLatt's existing 22-test suite passed before R1. MePhC and SqrLatt did not
have discoverable test directories. The new MePhC locks close that gap without
altering runtime code. The tests do not claim that an Abelian single-band
Berry curvature is valid at a band degeneracy; that is an open R2 question.

## Not locked yet

- full-structure symmetry verification beyond polygon-side proxies;
- band continuity through crossings and non-Abelian Berry curvature;
- affine deformation semantics and whether deformation is global or local;
- physical units as a typed coordinate object rather than a convention;
- cross-repository package version compatibility.
