"""E7H qualified enclosing-loop Dirac Berry-phase benchmark.

This module is test-only.  It records local cone evidence, validates the
qualification boundary, and measures phase only on the qualified enclosing
loop.  It never constructs curvature at K or divides phase by area.
"""

from dataclasses import replace

import meep as mp
from meep import mpb
import numpy as np
import pytest

from mephc.eigenspace import RawEigenstate
from mephc.mpb_qualified_path import qualify_mpb_spectral_path
from mephc.mpb_spectral_provider import MPBLiveSpectralProvider
from mephc.mpb_wilson import compose_mpb_wilson_transport
from mephc.path_domain import (
    PATH_SINGLE_BAND_QUALIFIED,
    PATH_SUBSPACE_REQUIRED,
    PATH_UNQUALIFIED,
)
from mephc.spectral_association import SubspaceQualificationThresholds
from mephc.wilson_geometry import WILSON_LOOP_QUALIFIED


THRESHOLDS = SubspaceQualificationThresholds(0.9, 0.45, 0.3, 0.05)
LOWER_BAND = 1
UPPER_BAND = 2
LOCAL_RADII = (0.02, 0.01)
SIX_DIRECTIONS = tuple(index * np.pi / 3.0 for index in range(6))
GUARD_CASES = ((0.16, 12), (0.04, 24), (0.08, 24), (0.12, 24))
QUALIFIED_CASE = (0.16, 24)


def triangular_lattice():
    root3_over_two = np.sqrt(3.0) / 2.0
    return mp.Lattice(
        size=mp.Vector3(1, 1),
        basis1=mp.Vector3(root3_over_two, 0.5),
        basis2=mp.Vector3(root3_over_two, -0.5),
    )


def k_point():
    lattice = triangular_lattice()
    reciprocal_basis = mp.Vector3(-1.0 / 3.0, 1.0 / 3.0)
    cartesian = mp.reciprocal_to_cartesian(reciprocal_basis, lattice)
    public = (float(cartesian.x), float(cartesian.y))
    round_trip = mp.cartesian_to_reciprocal(mp.Vector3(*public), lattice)
    reciprocal = tuple(float(getattr(round_trip, axis)) for axis in ("x", "y"))
    return lattice, public, reciprocal, (-1.0 / 3.0, 1.0 / 3.0)


def live_provider(*, phase_callback=None):
    lattice, _, _, _ = k_point()
    return MPBLiveSpectralProvider(
        geometry=[mp.Cylinder(0.2, material=mp.Medium(epsilon=12.0))],
        geometry_lattice=lattice,
        resolution=32,
        num_bands=4,
        polarization=mp.TM,
        default_material=mp.air,
        eigensolver_tolerance=1e-7,
        deterministic=True,
        mesh_size=3,
        phase_callback=phase_callback,
        orthogonality_tolerance=1e-8,
    )


def polygon_points(center, radius, vertices):
    x, y = center
    return tuple(
        (
            x + radius * np.cos(2.0 * np.pi * index / vertices),
            y + radius * np.sin(2.0 * np.pi * index / vertices),
        )
        for index in range(vertices)
    )


def radial_points(center, radius):
    x, y = center
    return tuple(
        (x + radius * np.cos(angle), y + radius * np.sin(angle))
        for angle in SIX_DIRECTIONS
    )


def solve_points(points, *, phase_callback=None):
    provider = live_provider(phase_callback=phase_callback)
    return tuple(provider.solve(point) for point in points)


def qualify(snapshots, solver_index):
    return qualify_mpb_spectral_path(
        snapshots,
        [(solver_index,)] * len(snapshots),
        thresholds=THRESHOLDS,
        closed=True,
    )


def wilson(snapshots, solver_index):
    path = qualify(snapshots, solver_index)
    return path, compose_mpb_wilson_transport(path)


def phase(result):
    return float(result.determinant_phase)


def phase_delta(left, right):
    return abs(np.angle(np.exp(1j * (left - right))))


def dirac_phase_error(value):
    return min(abs(value - np.pi), abs(value + np.pi))


def path_metrics(path):
    edges = path.path_result.edge_results
    first_failure = next(
        (
            (index, edge.status)
            for index, edge in enumerate(edges)
            if edge.status != PATH_SINGLE_BAND_QUALIFIED
        ),
        None,
    )
    return {
        "path_status": path.status,
        "min_external_gap": float(min(edge.external_gap for edge in edges)),
        "max_projector_distance": float(
            max(edge.projector_distance for edge in edges)
        ),
        "max_principal_angle": float(
            max(edge.overlap.max_principal_angle for edge in edges)
        ),
        "min_singular_value": float(
            min(edge.overlap.min_singular_value for edge in edges)
        ),
        "first_failing_edge": first_failure,
    }


def _permute_solver_order(snapshots):
    order = (1, 0, 2, 3)
    permuted = []
    for snapshot in snapshots:
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
        permuted.append(
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
    return tuple(permuted)


def _apply_local_u1(snapshots):
    phases = np.linspace(0.13, 2.17, len(snapshots))
    gauged = []
    for value, snapshot in zip(phases, snapshots):
        fields = np.array(snapshot.h_fields, copy=True)
        fields[LOWER_BAND] *= np.exp(1j * value)
        fields[UPPER_BAND] *= np.exp(-1j * (value + 0.37))
        gauged.append(replace(snapshot, h_fields=fields))
    return tuple(gauged)


def _reverse_same_basepoint(snapshots):
    return tuple((snapshots[0],) + tuple(reversed(snapshots[1:])))


@pytest.fixture(scope="module")
def live_benchmark():
    lattice, center, reciprocal, reciprocal_basis = k_point()
    provider = live_provider()
    polygons = {
        case: tuple(
            provider.solve(point)
            for point in polygon_points(center, case[0], case[1])
        )
        for case in GUARD_CASES + (QUALIFIED_CASE,)
    }
    radial = {
        radius: tuple(
            provider.solve(point) for point in radial_points(center, radius)
        )
        for radius in LOCAL_RADII
    }
    return {
        "lattice": lattice,
        "center": center,
        "reciprocal": reciprocal,
        "reciprocal_basis": reciprocal_basis,
        "polygons": polygons,
        "radial": radial,
    }


def test_e7h_k_and_local_cone_diagnostics(live_benchmark):
    _, center, reciprocal, reciprocal_basis = k_point()
    round_trip_residual = max(
        abs(left - right) for left, right in zip(reciprocal, reciprocal_basis)
    )
    assert round_trip_residual < 1e-12

    diagnostics = {}
    for radius in LOCAL_RADII:
        splittings = [
            abs(
                float(snapshot.frequencies[UPPER_BAND])
                - float(snapshot.frequencies[LOWER_BAND])
            )
            for snapshot in live_benchmark["radial"][radius]
        ]
        assert all(value > 0.0 for value in splittings)
        slopes = [value / radius for value in splittings]
        variation = (max(slopes) - min(slopes)) / np.mean(slopes)
        diagnostics[radius] = {
            "splittings": splittings,
            "splitting_over_radius": slopes,
            "mean_slope": float(np.mean(slopes)),
            "relative_directional_variation": float(variation),
        }
        assert variation < 0.20

    radial_change = abs(
        diagnostics[0.01]["mean_slope"] - diagnostics[0.02]["mean_slope"]
    ) / max(
        abs(diagnostics[0.01]["mean_slope"]),
        abs(diagnostics[0.02]["mean_slope"]),
    )
    assert radial_change < 0.20
    print({
        "K_public_cartesian": center,
        "K_reciprocal_basis": reciprocal_basis,
        "K_round_trip_residual": round_trip_residual,
        "local_cone_diagnostics": diagnostics,
        "relative_mean_slope_change": radial_change,
    })


def test_e7h_qualification_boundary_guard_cases(live_benchmark):
    report = {}
    for radius, vertices in GUARD_CASES:
        snapshots = live_benchmark["polygons"][(radius, vertices)]
        report[(radius, vertices)] = {}
        for branch in (LOWER_BAND, UPPER_BAND):
            path = qualify(snapshots, branch)
            metrics = path_metrics(path)
            report[(radius, vertices)][branch] = metrics
            if (radius, vertices) == (0.16, 12):
                assert path.status == PATH_UNQUALIFIED
                assert metrics["first_failing_edge"][1] == (
                    "SUBSPACE_CONTINUITY_UNQUALIFIED"
                )
            else:
                assert path.status == PATH_SUBSPACE_REQUIRED
                assert metrics["first_failing_edge"][1] == "SUBSPACE_NOT_ISOLATED"
                assert metrics["min_external_gap"] < THRESHOLDS.min_external_gap
    print({"qualification_boundary": report})


def test_e7h_qualified_enclosing_loop_has_pi_phase(live_benchmark):
    snapshots = live_benchmark["polygons"][QUALIFIED_CASE]
    report = {}
    for branch in (LOWER_BAND, UPPER_BAND):
        path, result = wilson(snapshots, branch)
        assert path.status == PATH_SINGLE_BAND_QUALIFIED
        assert result.status == WILSON_LOOP_QUALIFIED
        value = phase(result)
        error = dirac_phase_error(value)
        assert error <= 0.1
        report[branch] = {
            "path_status": path.status,
            "wilson_status": result.status,
            "phase": value,
            "dirac_phase_error": error,
            "metrics": path_metrics(path),
        }
    print({"qualified_enclosing_loop": report})


def test_e7h_phase_callback_preserves_qualified_loop_phase(live_benchmark):
    snapshots = live_benchmark["polygons"][QUALIFIED_CASE]
    phased = solve_points(
        polygon_points(live_benchmark["center"], *QUALIFIED_CASE),
        phase_callback=mpb.fix_hfield_phase,
    )
    deltas = []
    for branch in (LOWER_BAND, UPPER_BAND):
        base_path, base = wilson(snapshots, branch)
        phased_path, candidate = wilson(phased, branch)
        assert base_path.status == phased_path.status == PATH_SINGLE_BAND_QUALIFIED
        assert base.status == candidate.status == WILSON_LOOP_QUALIFIED
        deltas.append(phase_delta(phase(base), phase(candidate)))
    print({"phase_callback_phase_deltas": deltas})
    assert max(deltas) < 1e-6


def test_e7h_solver_order_preserves_qualified_loop_phase(live_benchmark):
    snapshots = live_benchmark["polygons"][QUALIFIED_CASE]
    permuted = _permute_solver_order(snapshots)
    deltas = []
    for branch, permuted_branch in ((LOWER_BAND, 0), (UPPER_BAND, 2)):
        base_path, base = wilson(snapshots, branch)
        candidate_path, candidate = wilson(permuted, permuted_branch)
        assert base_path.status == candidate_path.status == PATH_SINGLE_BAND_QUALIFIED
        assert base.status == candidate.status == WILSON_LOOP_QUALIFIED
        deltas.append(phase_delta(phase(base), phase(candidate)))
    print({"solver_order_phase_deltas": deltas})
    assert max(deltas) < 1e-8


def test_e7h_local_u1_reverse_and_cyclic_contracts(live_benchmark):
    snapshots = live_benchmark["polygons"][QUALIFIED_CASE]
    gauged = _apply_local_u1(snapshots)
    u1_deltas = []
    reverse_products = []
    reverse_phases = []
    cyclic_products = []
    for branch in (LOWER_BAND, UPPER_BAND):
        _, base = wilson(snapshots, branch)
        _, gauged_result = wilson(gauged, branch)
        u1_deltas.append(phase_delta(phase(base), phase(gauged_result)))

        _, reverse = wilson(_reverse_same_basepoint(snapshots), branch)
        reverse_products.append(
            float(np.max(np.abs(reverse.product - base.product.conj().T)))
        )
        reverse_phases.append(phase_delta(phase(reverse), -phase(base)))

        _, cyclic = wilson(snapshots[1:] + snapshots[:1], branch)
        cyclic_products.append(float(np.max(np.abs(cyclic.product - base.product))))

    print({
        "local_u1_phase_deltas": u1_deltas,
        "reverse_product_residuals": reverse_products,
        "reverse_phase_residuals": reverse_phases,
        "cyclic_product_residuals": cyclic_products,
    })
    assert max(u1_deltas) < 1e-8
    assert max(reverse_products) < 1e-8
    assert max(reverse_phases) < 1e-8
    assert max(cyclic_products) < 1e-8
