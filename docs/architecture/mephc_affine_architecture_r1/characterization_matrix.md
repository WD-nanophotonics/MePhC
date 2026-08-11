# R1.1 Characterization Matrix

Every original minimum target has exactly one row. Test node IDs refer to
`tests.test_affine_characterization.AffineCharacterizationTests`.

| Lock ID | Status | Test node ID | Evidence | Expected behavior | Reason |
|---|---|---|---|---|---|
| LOCK-01 | locked | `test_lock_01_real_space_and_solver_basis_parity` | `mephc.lattice.maketriangularlattice`; `mephc.band.Band._make_geometry_lattice` | Independent real-space translations `(1,0)` and `(1/2,sqrt(3)/2)` transform to the ordered MPB basis `(1/2,+sqrt(3)/2),(1/2,-sqrt(3)/2)` | Direct-site and solver paths agree under an explicit unimodular basis change |
| LOCK-02 | locked | `test_triangular_and_square_direct_basis_are_explicit` | `Band.geo_latt.basis1/basis2` | Triangular and square MPB basis vectors retain current orientation and order | Direct assertion against current solver construction |
| LOCK-03 | locked | `test_direct_reciprocal_duality_and_two_pi_convention` | direct-basis reciprocal calculation in test; `mephc.band.Band` | Reciprocal vectors use the documented `2*pi` scale | `D.T @ G = I` without changing the package convention |
| LOCK-04 | locked | `test_direct_reciprocal_duality_and_two_pi_convention` | same reciprocal dual calculation | Direct and reciprocal bases are dual within `1e-12` | Explicit numeric tolerance is tested |
| LOCK-05 | locked | `test_lock_02_ordered_first_bz_contract` | `TriangularKSpace.first_bz_poly` | Six ordered non-closed vertices, start at `+kx`, counter-clockwise winding, area `2*sqrt(3)/3` | Vertex values and signed area are both asserted |
| LOCK-06 | locked | `test_lock_08_square_and_triangular_path_conventions` | `square_gxm_path`; `triangular_gkm_path` | Current Gamma-X-M-Gamma and Gamma-K-M-Gamma labels/coordinates remain stable | Path vertices are asserted, not only labels |
| LOCK-07 | blocked | `test_lock_05_c4_selection_is_explicit_and_alias_stable` plus C3 assertions | `TriLatt.workflow.resolve_symmetry_mode`; `SqrLatt/square_hole/berry_curvature.py` | C3 auto-selection is locked; SqrLatt C4 is explicit `c4q` and alias `c4 -> c4q` | No current SqrLatt geometry-driven C4 auto-selection exists; implementing one is forbidden in R1.1 |
| LOCK-08 | locked | `test_lock_03_minimal_triangular_motif_site_placement` | `mephc.lattice.Lattice.PolygonPattern` | Site center, local triangle vertices, translation, and vertex order remain distinct and stable | Uses a minimal triangular lattice case |
| LOCK-09 | locked | `test_lock_06_triangular_identity_behavior` and `test_lock_07_square_identity_behavior` | TriLatt `config.geometry_id`; SqrLatt `square_hole.config.geometry_id`; `mephc.records.make_task_key` | Active physical IDs and order-independent task keys remain stable; resolution/plot settings are not geometry IDs | Both downstream cases are loaded from their committed files |
| LOCK-10 | locked | `test_lock_10_low_resolution_solver_smoke` | Meep/MPB via `Band.run_simulation_te` | One low-resolution square solve returns at least one frequency | Dependencies are available and the smoke ran successfully |

## Gate result

LOCK-01 through LOCK-06 and LOCK-08 through LOCK-10 are locked. LOCK-07 is
blocked specifically because the current square workflow has an explicit C4
case parameter rather than an automatic geometry decision. No production
change is allowed to close that gap in R1.1. Overall R1.1 status is therefore
`blocked`, not `completed`.
