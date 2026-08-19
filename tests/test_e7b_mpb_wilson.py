
import json
from dataclasses import replace

import meep as mp
from meep import mpb
import numpy as np
import pytest

from mephc.eigenspace import RawEigenstate
from mephc.mpb_qualified_path import qualify_mpb_spectral_path
from mephc.mpb_spectral import adapt_mpb_h_envelopes
from mephc.mpb_spectral_provider import MPBLiveSpectralProvider
from mephc.mpb_wilson import (
    MPB_WILSON_AUTHORIZATION_SCOPE,
    compose_mpb_wilson_transport,
)
from mephc.path_domain import (
    PATH_INCOMPLETE,
    PATH_SINGLE_BAND_QUALIFIED,
    PATH_SUBSPACE_QUALIFIED,
    PATH_SUBSPACE_REQUIRED,
    PATH_UNQUALIFIED,
)
from mephc.spectral_association import SubspaceQualificationThresholds
from mephc.wilson_geometry import (
    WILSON_INPUT_INCOMPLETE,
    WILSON_INPUT_UNQUALIFIED,
    WILSON_LINE_QUALIFIED,
    WILSON_LOOP_QUALIFIED,
    compose_wilson_transport,
)


THRESHOLDS = SubspaceQualificationThresholds(
    min_singular_value=0.9,
    max_principal_angle=0.45,
    max_projector_distance=0.3,
    min_external_gap=0.05,
)


def benchmark():
    lattice = mp.Lattice(size=mp.Vector3(1, 1))
    geometry = [mp.Cylinder(0.2, material=mp.Medium(epsilon=12))]
    return geometry, lattice


def provider(*, phase_callback=None, num_bands=2):
    geometry, lattice = benchmark()
    return MPBLiveSpectralProvider(
        geometry=geometry,
        geometry_lattice=lattice,
        resolution=6,
        num_bands=num_bands,
        polarization=mp.TE,
        default_material=mp.air,
        eigensolver_tolerance=1e-7,
        deterministic=True,
        mesh_size=3,
        phase_callback=phase_callback,
        orthogonality_tolerance=1e-8,
    )


@pytest.fixture(scope="module")
def live_snapshots():
    points = ((0.17, 0.23), (0.18, 0.23), (0.18, 0.24), (0.17, 0.24))
    solver = provider()
    return tuple(solver.solve(point) for point in points)


@pytest.fixture(scope="module")
def phased_snapshots():
    points = ((0.17, 0.23), (0.18, 0.23), (0.18, 0.24), (0.17, 0.24))
    solver = provider(phase_callback=mpb.fix_hfield_phase)
    return tuple(solver.solve(point) for point in points)


def qualify(snapshots, *, closed=True, thresholds=THRESHOLDS, require_live=True, selection=None):
    return qualify_mpb_spectral_path(
        snapshots,
        selection or [(0,)] * len(snapshots),
        thresholds=thresholds,
        closed=closed,
        require_live=require_live,
    )


def test_live_closed_rectangle_delegates_exact_e5a_result_and_qualifies(live_snapshots):
    path = qualify(live_snapshots)
    result = compose_mpb_wilson_transport(path)
    direct = compose_wilson_transport(path.path_result)

    assert path.status == PATH_SINGLE_BAND_QUALIFIED
    assert result.status == WILSON_LOOP_QUALIFIED
    assert result.is_live_qualified is True
    assert result.mpb_path_result is path
    assert result.wilson_result.provenance == direct.provenance
    assert np.allclose(result.product, direct.product, atol=1e-12)
    assert result.wilson_result.edge_links == direct.edge_links
    assert result.authorization_scope == MPB_WILSON_AUTHORIZATION_SCOPE


def test_live_phase_callback_preserves_rank_one_loop_invariants(live_snapshots, phased_snapshots):
    baseline = compose_mpb_wilson_transport(qualify(live_snapshots))
    phased = compose_mpb_wilson_transport(qualify(phased_snapshots))

    assert phased.status == baseline.status == WILSON_LOOP_QUALIFIED
    assert np.allclose(np.sort_complex(phased.eigenvalues), np.sort_complex(baseline.eigenvalues), atol=1e-8)
    assert phased.determinant == pytest.approx(baseline.determinant, abs=1e-8)
    assert phased.determinant_phase == pytest.approx(baseline.determinant_phase, abs=1e-8)
    assert phased.trace == pytest.approx(baseline.trace, abs=1e-8)
    assert phased.eigenphases == pytest.approx(baseline.eigenphases, abs=1e-8)


def test_solver_order_permutation_preserves_e7a_and_loop_invariants(live_snapshots):
    order = (1, 0)
    permuted = []
    for snapshot in live_snapshots:
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
                normalized_vectors=tuple(snapshot.normalized_vectors[index] for index in order),
                gram_matrix=snapshot.gram_matrix[np.ix_(order, order)],
                raw_eigenstates=states,
            )
        )

    original_path = qualify(live_snapshots)
    permuted_path = qualify(tuple(permuted), selection=[(1,)] * 4)
    original = compose_mpb_wilson_transport(original_path)
    permuted_result = compose_mpb_wilson_transport(permuted_path)

    assert permuted_path.status == original_path.status == PATH_SINGLE_BAND_QUALIFIED
    assert permuted_result.status == original.status == WILSON_LOOP_QUALIFIED
    for left, right in zip(original_path.vertices, permuted_path.vertices):
        assert np.allclose(left.projector_matrix(), right.projector_matrix(), atol=1e-8)
    assert np.allclose(permuted_result.eigenvalues, original.eigenvalues, atol=1e-8)
    assert permuted_result.determinant == pytest.approx(original.determinant, abs=1e-8)
    assert permuted_result.trace == pytest.approx(original.trace, abs=1e-8)


def test_reverse_live_closed_path_is_hermitian_adjoint(live_snapshots):
    forward = compose_mpb_wilson_transport(qualify(live_snapshots))
    reverse_path = qualify(tuple(reversed(live_snapshots)))
    reverse = compose_mpb_wilson_transport(reverse_path)

    assert reverse.status == WILSON_LOOP_QUALIFIED
    assert np.allclose(reverse.product, forward.product.conj().T, atol=1e-8)


def test_cyclic_live_closed_path_preserves_unordered_invariants(live_snapshots):
    original = compose_mpb_wilson_transport(qualify(live_snapshots))
    shifted_path = qualify(live_snapshots[1:] + live_snapshots[:1])
    shifted = compose_mpb_wilson_transport(shifted_path)

    assert shifted.status == WILSON_LOOP_QUALIFIED
    assert np.allclose(np.sort_complex(shifted.eigenvalues), np.sort_complex(original.eigenvalues), atol=1e-8)
    assert shifted.trace == pytest.approx(original.trace, abs=1e-8)
    assert shifted.determinant == pytest.approx(original.determinant, abs=1e-8)
    assert shifted.determinant_phase == pytest.approx(original.determinant_phase, abs=1e-8)


def test_live_open_path_exposes_only_line_product(live_snapshots):
    result = compose_mpb_wilson_transport(qualify(live_snapshots[:3], closed=False))

    assert result.status == WILSON_LINE_QUALIFIED
    assert result.is_live_qualified is True
    assert result.product.shape == (1, 1)
    assert result.trace is None
    assert result.determinant is None
    assert result.eigenvalues is None
    assert result.eigenphases is None


def static_snapshot(*, fields, frequencies, k_point=(0.1, 0.2)):
    return adapt_mpb_h_envelopes(
        k_point,
        frequencies,
        fields,
        orthogonality_tolerance=1e-12,
    )


def test_static_rank_two_gauge_invariance_and_live_boundary():
    base_vectors = np.eye(6, 2, dtype=complex)
    rng = np.random.default_rng(20260819)
    gauges = []
    snapshots = []
    for index in range(4):
        gauge, _ = np.linalg.qr(
            rng.normal(size=(2, 2)) + 1j * rng.normal(size=(2, 2))
        )
        gauges.append(gauge)
        vectors = base_vectors @ gauge
        fields = np.zeros((3, 2, 1, 3), dtype=complex)
        fields[0] = vectors[:, 0].reshape(2, 1, 3)
        fields[1] = vectors[:, 1].reshape(2, 1, 3)
        fields[2, 0, 0, 2] = 1.0
        snapshots.append(static_snapshot(fields=fields, frequencies=(0.0, 0.0, 5.0), k_point=(0.1 + index * 0.01, 0.2)))

    path = qualify(tuple(snapshots), require_live=False, selection=[(0, 1)] * 4)
    result = compose_mpb_wilson_transport(path, require_live=False)
    canonical_fields = np.zeros((3, 2, 1, 3), dtype=complex)
    canonical_fields[0, 0, 0, 0] = 1.0
    canonical_fields[1, 1, 0, 1] = 1.0
    canonical_fields[2, 0, 0, 2] = 1.0
    canonical_path = qualify(
        tuple(
            static_snapshot(
                fields=canonical_fields,
                frequencies=(0.0, 0.0, 5.0),
                k_point=(0.1 + index * 0.01, 0.2),
            )
            for index in range(4)
        ),
        require_live=False,
        selection=[(0, 1)] * 4,
    )
    canonical = compose_mpb_wilson_transport(canonical_path, require_live=False)
    assert path.status == canonical_path.status == PATH_SUBSPACE_QUALIFIED
    assert result.status == canonical.status == WILSON_LOOP_QUALIFIED
    assert result.is_live_qualified is False
    assert np.allclose(np.sort_complex(result.eigenvalues), np.sort_complex(canonical.eigenvalues), atol=1e-8)
    assert result.trace == pytest.approx(canonical.trace, abs=1e-8)
    assert result.determinant == pytest.approx(canonical.determinant, abs=1e-8)
    assert result.determinant_phase == pytest.approx(canonical.determinant_phase, abs=1e-8)


def test_open_static_qualified_path_requires_explicit_non_live_mode():
    fields = np.zeros((2, 1, 1, 3), dtype=complex)
    fields[0, 0, 0, 0] = 1.0
    fields[1, 0, 0, 1] = 1.0
    snapshots = tuple(static_snapshot(fields=fields, frequencies=(0.0, 5.0)) for _ in range(3))
    path = qualify(tuple(snapshots), closed=False, require_live=False)
    with pytest.raises(ValueError, match="live MPB"):
        compose_mpb_wilson_transport(path)
    result = compose_mpb_wilson_transport(path, require_live=False)
    assert result.status == WILSON_LINE_QUALIFIED
    assert result.is_live_qualified is False


def test_path_failures_delegate_to_e5a_and_expose_no_product(live_snapshots):
    incomplete_fields = np.zeros((1, 1, 1, 3), dtype=complex)
    incomplete_fields[0, 0, 0, 0] = 1.0
    incomplete_path = qualify(
        tuple(static_snapshot(fields=incomplete_fields, frequencies=(0.0,)) for _ in range(2)),
        closed=False,
        require_live=False,
    )
    incomplete = compose_mpb_wilson_transport(incomplete_path, require_live=False)
    assert incomplete_path.status == PATH_INCOMPLETE
    assert incomplete.status == WILSON_INPUT_INCOMPLETE
    assert incomplete.product is None

    isolated_fields = np.zeros((2, 1, 1, 3), dtype=complex)
    isolated_fields[0, 0, 0, 0] = 1.0
    isolated_fields[1, 0, 0, 1] = 1.0
    isolated_path = qualify(
        tuple(
            static_snapshot(fields=isolated_fields, frequencies=(0.0, 0.01))
            for _ in range(4)
        ),
        closed=False,
        require_live=False,
    )
    # The rank-one source is not externally isolated at the fixed threshold.
    isolated = compose_mpb_wilson_transport(isolated_path, require_live=False)
    assert isolated_path.status == PATH_SUBSPACE_REQUIRED
    assert isolated.status == WILSON_INPUT_UNQUALIFIED
    assert isolated.product is None

    bad_thresholds = SubspaceQualificationThresholds(
        min_singular_value=0.9,
        max_principal_angle=1e-7,
        max_projector_distance=0.3,
        min_external_gap=0.05,
    )
    unqualified_path = qualify(live_snapshots, thresholds=bad_thresholds)
    unqualified = compose_mpb_wilson_transport(unqualified_path)
    assert unqualified_path.status == PATH_UNQUALIFIED
    assert unqualified.status == WILSON_INPUT_UNQUALIFIED
    assert unqualified.product is None


def test_result_is_readonly_json_safe_and_exposes_no_forbidden_claims(live_snapshots):
    result = compose_mpb_wilson_transport(qualify(live_snapshots))
    with pytest.raises(ValueError):
        result.product[0, 0] = 2.0
    with pytest.raises(TypeError):
        result.provenance["new"] = "not allowed"
    encoded = json.dumps(result.to_dict()).lower()
    for forbidden in (
        "berry",
        "chern",
        "curvature",
        "matrix-logarithm",
        "observable-convergence",
        "production-authorization",
        "physical_band_id",
        "branch_id",
        "adiabatic_band_id",
    ):
        assert forbidden not in encoded
    assert json.loads(encoded)["authorization_scope"] == MPB_WILSON_AUTHORIZATION_SCOPE
