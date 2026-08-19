"""E7G live MPB validation at the triangular-lattice K-point degeneracy.

This module is deliberately test-only. It records a bounded physical
benchmark for the sealed E6-E7 stack and does not add a production
observable or infer a scalar Berry quantity at the degenerate point.
"""

from dataclasses import replace

import meep as mp
from meep import mpb
import numpy as np
import pytest

from mephc.eigenspace import RawEigenstate
from mephc.mpb_plaquette_holonomy import compose_mpb_plaquette_holonomy
from mephc.mpb_qualified_plaquette import qualify_mpb_plaquette
from mephc.mpb_spectral_provider import MPBLiveSpectralProvider
from mephc.plaquette_domain import (
    PLAQUETTE_REFINEMENT_UNQUALIFIED,
    PLAQUETTE_REFINEMENT_SUBSPACE_QUALIFIED,
    PLAQUETTE_REFINEMENT_SUBSPACE_REQUIRED,
    PlaquetteRefinementThresholds,
)
from mephc.spectral_association import SubspaceQualificationThresholds
from mephc.wilson_geometry import WILSON_LOOP_QUALIFIED


E3 = SubspaceQualificationThresholds(0.9, 0.45, 0.3, 0.05)
E4C = PlaquetteRefinementThresholds(0.9, 0.45, 0.3, 0.1)
STEPS = (0.02, 0.01, 0.005)
RESOLUTIONS = (16, 24, 32)
PRIMARY_RESOLUTION = 32
DEGENERATE_BANDS = (1, 2)  # one-based bands 2 and 3


def triangular_lattice():
    root3_over_two = np.sqrt(3.0) / 2.0
    return mp.Lattice(
        size=mp.Vector3(1, 1),
        basis1=mp.Vector3(root3_over_two, 0.5),
        basis2=mp.Vector3(root3_over_two, -0.5),
    )


def k_point_geometry():
    lattice = triangular_lattice()
    reciprocal_basis_k = mp.Vector3(-1.0 / 3.0, 1.0 / 3.0)
    cartesian = mp.reciprocal_to_cartesian(reciprocal_basis_k, lattice)
    public_k = (float(cartesian.x), float(cartesian.y))
    round_trip = mp.cartesian_to_reciprocal(
        mp.Vector3(public_k[0], public_k[1]), lattice
    )
    reciprocal = tuple(float(getattr(round_trip, axis)) for axis in ("x", "y"))
    return lattice, public_k, reciprocal, (-1.0 / 3.0, 1.0 / 3.0)


def make_provider(resolution, *, phase_callback=None):
    lattice, _, _, _ = k_point_geometry()
    return MPBLiveSpectralProvider(
        geometry=[mp.Cylinder(0.2, material=mp.Medium(epsilon=12.0))],
        geometry_lattice=lattice,
        resolution=resolution,
        num_bands=4,
        polarization=mp.TM,
        default_material=mp.air,
        eigensolver_tolerance=1e-7,
        deterministic=True,
        mesh_size=3,
        phase_callback=phase_callback,
        orthogonality_tolerance=1e-8,
    )


def plaquette_points(center, step):
    x, y = center
    return (
        (x - step, y - step),
        (x + step, y - step),
        (x + step, y + step),
        (x - step, y + step),
        center,
    )


def solve_levels(resolution, *, phase_callback=None):
    _, center, _, _ = k_point_geometry()
    provider = make_provider(resolution, phase_callback=phase_callback)
    return tuple(
        tuple(provider.solve(point) for point in plaquette_points(center, step))
        for step in STEPS
    )


def selections(rank):
    selected = (1,) if rank == 1 else DEGENERATE_BANDS
    return tuple(tuple(selected for _ in range(5)) for _ in STEPS)


def qualify(levels, rank, *, require_live=True, selection_override=None):
    return qualify_mpb_plaquette(
        levels,
        selections(rank) if selection_override is None else selection_override,
        STEPS,
        thresholds=E3,
        refinement_thresholds=E4C,
        require_live=require_live,
    )


def holonomy(source, *, require_live=True):
    return compose_mpb_plaquette_holonomy(source, require_live=require_live)


def _reorder_levels(levels, order):
    return tuple(tuple(level[index] for index in order) for level in levels)


def _permute_solver_order(levels):
    order = (1, 0, 2, 3)
    permuted = []
    for level in levels:
        permuted_level = []
        for snapshot in level:
            states = tuple(
                RawEigenstate(
                    k_point=snapshot.k_point,
                    solver_index=new_index,
                    eigenvalue=snapshot.raw_eigenstates[old_index].eigenvalue,
                    vector=snapshot.raw_eigenstates[old_index].vector,
                    metadata={
                        **dict(snapshot.raw_eigenstates[old_index].metadata),
                        "synthetic_solver_order_index": new_index,
                    },
                )
                for new_index, old_index in enumerate(order)
            )
            permuted_level.append(
                replace(
                    snapshot,
                    frequencies=snapshot.frequencies[list(order)],
                    h_fields=snapshot.h_fields[list(order)],
                    raw_norms=snapshot.raw_norms[list(order)],
                    normalized_vectors=tuple(
                        snapshot.normalized_vectors[index] for index in order
                    ),
                    gram_matrix=snapshot.gram_matrix[np.ix_(order, order)],
                    raw_eigenstates=states,
                )
            )
        permuted.append(tuple(permuted_level))
    return tuple(permuted)


def _u2_levels(levels):
    rng = np.random.default_rng(20260820)
    gauged = []
    for level in levels:
        gauged_level = []
        for snapshot in level:
            gauge, _ = np.linalg.qr(
                rng.normal(size=(2, 2)) + 1j * rng.normal(size=(2, 2))
            )
            fields = np.array(snapshot.h_fields, copy=True)
            selected = fields[:2].reshape(2, -1)
            fields[:2] = (gauge @ selected).reshape(fields[:2].shape)
            gauged_level.append(replace(snapshot, h_fields=fields))
        gauged.append(tuple(gauged_level))
    return tuple(gauged)


def _invariant_deltas(reference, candidate):
    deltas = []
    for left, right in zip(reference.wilson_results, candidate.wilson_results):
        deltas.append(
            max(
                np.max(
                    np.abs(
                        np.sort_complex(left.eigenvalues)
                        - np.sort_complex(right.eigenvalues)
                    )
                ),
                abs(left.trace - right.trace),
                abs(left.determinant - right.determinant),
                abs(
                    np.angle(
                        np.exp(1j * (left.determinant_phase - right.determinant_phase))
                    )
                ),
            )
        )
    return deltas


@pytest.fixture(scope="module")
def live_benchmark():
    lattice, center, reciprocal, reciprocal_basis = k_point_geometry()
    levels = {resolution: solve_levels(resolution) for resolution in RESOLUTIONS}
    return {
        "lattice": lattice,
        "center": center,
        "reciprocal": reciprocal,
        "reciprocal_basis": reciprocal_basis,
        "levels": levels,
    }


def test_e7g_derived_k_round_trip_and_reported_splittings(live_benchmark):
    _, center, reciprocal, reciprocal_basis = k_point_geometry()
    residual = max(abs(left - right) for left, right in zip(reciprocal, reciprocal_basis))
    assert residual < 1e-12
    diagnostics = {}
    for resolution, levels in live_benchmark["levels"].items():
        frequencies = levels[-1][4].frequencies
        diagnostics[resolution] = {
            "bands": [float(value) for value in frequencies],
            "band_2_3_splitting": abs(float(frequencies[2] - frequencies[1])),
            "nearest_external_gap": min(
                float(frequencies[1] - frequencies[0]),
                float(frequencies[3] - frequencies[2]),
            ),
        }
        assert frequencies.shape == (4,)
        assert diagnostics[resolution]["nearest_external_gap"] > 0.0
    print({
        "K_public_cartesian": center,
        "K_reciprocal_basis": reciprocal_basis,
        "K_round_trip_residual": residual,
        "diagnostic_resolution_ladder": diagnostics,
    })


def test_e7g_rank_one_fails_closed_and_rank_two_qualifies(live_benchmark):
    levels = live_benchmark["levels"][PRIMARY_RESOLUTION]
    rank_one = qualify(levels, 1)
    rank_two = qualify(levels, 2)
    rank_two_wilson = holonomy(rank_two)
    assert rank_one.status == PLAQUETTE_REFINEMENT_UNQUALIFIED
    assert all(
        edge.status == "SUBSPACE_CONTINUITY_UNQUALIFIED"
        for boundary in rank_one.boundary_results
        for edge in boundary.edge_results
    )
    assert all(
        spoke.status == "SUBSPACE_CONTINUITY_UNQUALIFIED"
        for interior in rank_one.interior_results
        for spoke in interior.spoke_results
    )
    assert rank_two.status == PLAQUETTE_REFINEMENT_SUBSPACE_QUALIFIED
    assert rank_two_wilson.status == (WILSON_LOOP_QUALIFIED,) * len(STEPS)
    assert "berry" not in str(rank_one.to_dict()).lower()
    assert "curvature" not in str(rank_one.to_dict()).lower()
    print({
        "rank_one_e7c_status": rank_one.status,
        "rank_two_e7c_status": rank_two.status,
        "rank_two_e7d_status": list(rank_two_wilson.status),
        "rank_one_scalar_berry_at_K": False,
    })


def test_e7g_phase_callback_preserves_rank_two_invariants(live_benchmark):
    base = holonomy(qualify(live_benchmark["levels"][PRIMARY_RESOLUTION], 2))
    phased = holonomy(qualify(
        solve_levels(PRIMARY_RESOLUTION, phase_callback=mpb.fix_hfield_phase), 2
    ))
    assert phased.status == base.status == (WILSON_LOOP_QUALIFIED,) * len(STEPS)
    deltas = _invariant_deltas(base, phased)
    assert max(deltas) < 1e-6
    print({"phase_callback_invariant_deltas": deltas})


def test_e7g_solver_order_permutation_preserves_rank_decisions_and_wilson(live_benchmark):
    levels = live_benchmark["levels"][PRIMARY_RESOLUTION]
    permuted = _permute_solver_order(levels)
    rank_one_permuted_selections = tuple(
        tuple((0,) for _ in range(5)) for _ in STEPS
    )
    rank_two_permuted_selections = tuple(
        tuple((0, 2) for _ in range(5)) for _ in STEPS
    )
    assert qualify(
        permuted, 1, selection_override=rank_one_permuted_selections
    ).status == PLAQUETTE_REFINEMENT_UNQUALIFIED
    base = holonomy(qualify(levels, 2))
    candidate = holonomy(
        qualify(permuted, 2, selection_override=rank_two_permuted_selections)
    )
    assert candidate.status == base.status
    deltas = _invariant_deltas(base, candidate)
    assert max(deltas) < 1e-8
    print({"solver_order_permutation": "preserved", "invariant_deltas": deltas})


def test_e7g_local_u2_rotation_preserves_rank_two_wilson_invariants(live_benchmark):
    levels = live_benchmark["levels"][PRIMARY_RESOLUTION]
    base = holonomy(qualify(levels, 2))
    candidate = holonomy(qualify(_u2_levels(levels), 2))
    assert candidate.status == base.status == (WILSON_LOOP_QUALIFIED,) * len(STEPS)
    deltas = _invariant_deltas(base, candidate)
    assert max(deltas) < 1e-6
    print({"local_u2_invariant_deltas": deltas})


def test_e7g_reverse_orientation_and_cyclic_base_point_preserve_invariants(live_benchmark):
    levels = live_benchmark["levels"][PRIMARY_RESOLUTION]
    forward = holonomy(qualify(levels, 2))
    reverse = holonomy(qualify(_reorder_levels(levels, (0, 3, 2, 1, 4)), 2))
    cyclic = holonomy(qualify(_reorder_levels(levels, (1, 2, 3, 0, 4)), 2))
    assert forward.status == reverse.status == cyclic.status == (
        WILSON_LOOP_QUALIFIED,
    ) * len(STEPS)
    reverse_matrix = []
    reverse_phase = []
    cyclic_deltas = []
    for fwd, rev, cyc in zip(
        forward.wilson_results, reverse.wilson_results, cyclic.wilson_results
    ):
        reverse_matrix.append(np.max(np.abs(rev.product - fwd.product.conj().T)))
        reverse_phase.append(abs(np.angle(np.exp(1j * (rev.determinant_phase + fwd.determinant_phase)))) )
        cyclic_deltas.append(max(
            np.max(np.abs(np.sort_complex(cyc.eigenvalues) - np.sort_complex(fwd.eigenvalues))),
            abs(cyc.trace - fwd.trace),
            abs(cyc.determinant - fwd.determinant),
            abs(np.angle(np.exp(1j * (cyc.determinant_phase - fwd.determinant_phase)))),
        ))
    assert max(reverse_matrix) < 1e-8
    assert max(reverse_phase) < 1e-8
    assert max(cyclic_deltas) < 1e-8
    print({
        "forward_vertex_order": (0, 1, 2, 3, 0),
        "old_reverse_vertex_order": (3, 2, 1, 0, 3),
        "corrected_reverse_vertex_order": (0, 3, 2, 1, 0),
        "same_live_snapshots_reused": True,
    })
    print({
        "reverse_matrix_residuals": reverse_matrix,
        "reverse_phase_residuals": reverse_phase,
        "cyclic_base_point_invariant_deltas": cyclic_deltas,
    })
