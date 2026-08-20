
import json
from dataclasses import replace

import meep as mp
from meep import mpb
import numpy as np
import pytest

from mephc.mpb_qualified_path import qualify_mpb_spectral_path
from mephc.mpb_spectral import adapt_mpb_h_envelopes
from mephc.mpb_spectral_provider import MPBLiveSpectralProvider
from mephc.path_domain import PATH_SINGLE_BAND_QUALIFIED, PATH_SUBSPACE_QUALIFIED, PATH_SUBSPACE_REQUIRED
from mephc.spectral_association import SubspaceQualificationThresholds
from mephc.eigenspace import RawEigenstate


LIVE_THRESHOLDS = SubspaceQualificationThresholds(
    min_singular_value=0.9,
    max_principal_angle=0.45,
    max_projector_distance=0.3,
    min_external_gap=0.05,
)


def benchmark():
    lattice = mp.Lattice(size=mp.Vector3(1, 1))
    geometry = [mp.Cylinder(0.2, material=mp.Medium(epsilon=12))]
    return geometry, lattice


def live_provider(*, phase_callback=None, num_bands=2):
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


def live_snapshots(*, phase_callback=None):
    points = ((0.17, 0.23), (0.18, 0.23), (0.18, 0.24), (0.17, 0.24))
    provider = live_provider(phase_callback=phase_callback)
    return tuple(provider.solve(point) for point in points)


def test_live_four_vertex_rank_one_path_records_fixed_threshold_diagnostics():
    snapshots = live_snapshots()
    result = qualify_mpb_spectral_path(
        snapshots,
        [(0,)] * len(snapshots),
        thresholds=LIVE_THRESHOLDS,
        closed=False,
    )
    assert result.status == PATH_SINGLE_BAND_QUALIFIED
    assert result.is_live_qualified is True
    assert len(result.path_result.edge_results) == 3

    minimum_singular = min(edge.overlap.min_singular_value for edge in result.path_result.edge_results)
    maximum_angle = max(edge.overlap.max_principal_angle for edge in result.path_result.edge_results)
    maximum_projector_distance = max(edge.projector_distance for edge in result.path_result.edge_results)
    minimum_external_gap = min(edge.external_gap for edge in result.path_result.edge_results)
    assert minimum_singular >= LIVE_THRESHOLDS.min_singular_value
    assert maximum_angle <= LIVE_THRESHOLDS.max_principal_angle
    assert maximum_projector_distance <= LIVE_THRESHOLDS.max_projector_distance
    assert minimum_external_gap >= LIVE_THRESHOLDS.min_external_gap


def test_live_phase_callback_preserves_path_decision_and_edge_diagnostics():
    baseline = qualify_mpb_spectral_path(
        live_snapshots(),
        [(0,)] * 4,
        thresholds=LIVE_THRESHOLDS,
        closed=False,
    )
    phased = qualify_mpb_spectral_path(
        live_snapshots(phase_callback=mpb.fix_hfield_phase),
        [(0,)] * 4,
        thresholds=LIVE_THRESHOLDS,
        closed=False,
    )
    assert phased.status == baseline.status == PATH_SINGLE_BAND_QUALIFIED
    for left, right in zip(baseline.path_result.edge_results, phased.path_result.edge_results):
        # These are test-expectation tolerances derived from measured MPB repeatability; physical qualification thresholds remain unchanged.
        assert left.external_gap == pytest.approx(right.external_gap, abs=1e-8)
        assert left.overlap.min_singular_value == pytest.approx(right.overlap.min_singular_value, abs=1e-7)
        assert left.overlap.max_principal_angle == pytest.approx(right.overlap.max_principal_angle, abs=2e-5)
        assert left.projector_distance == pytest.approx(right.projector_distance, abs=2e-5)


def test_solver_order_permutation_requires_updated_local_selection_and_preserves_projector():
    original = live_snapshots()
    order = (1, 0)
    permuted = []
    for snapshot in original:
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

    original_result = qualify_mpb_spectral_path(
        original,
        [(0,)] * 4,
        thresholds=LIVE_THRESHOLDS,
        closed=False,
    )
    permuted_result = qualify_mpb_spectral_path(
        tuple(permuted),
        [(1,)] * 4,
        thresholds=LIVE_THRESHOLDS,
        closed=False,
    )
    assert permuted_result.status == original_result.status == PATH_SINGLE_BAND_QUALIFIED
    for left, right in zip(original_result.vertices, permuted_result.vertices):
        assert np.allclose(left.projector_matrix(), right.projector_matrix(), atol=1e-8)
    assert all(edge.external_gap == pytest.approx(other.external_gap, abs=1e-10)
               for edge, other in zip(original_result.path_result.edge_results, permuted_result.path_result.edge_results))


def static_snapshot(*, bands=2, frequencies=(0.0, 0.01), spatial_shape=(1, 1)):
    nx, ny = spatial_shape
    fields = np.zeros((bands, nx, ny, 3), dtype=np.complex128)
    fields[0, 0, 0, 0] = 1.0
    if bands >= 2:
        fields[1, 0, 0, 1] = 1.0
    if bands >= 3:
        fields[2, 0, 0, 2] = 1.0
    return adapt_mpb_h_envelopes(
        (0.1, 0.2),
        frequencies,
        fields,
        orthogonality_tolerance=1e-12,
    )


def test_rank_one_static_path_fails_closed_when_external_isolation_is_missing():
    snapshots = tuple(static_snapshot() for _ in range(4))
    result = qualify_mpb_spectral_path(
        snapshots,
        [(0,)] * 4,
        thresholds=SubspaceQualificationThresholds(
            min_singular_value=0.9,
            max_principal_angle=0.45,
            max_projector_distance=0.2,
            min_external_gap=0.1,
        ),
        closed=False,
        require_live=False,
    )
    assert result.status == PATH_SUBSPACE_REQUIRED
    assert result.is_live_qualified is False
    assert all(edge.external_gap == pytest.approx(0.01) for edge in result.path_result.edge_results)


def test_static_rank_two_path_qualifies_without_auto_enlargement():
    fields = np.zeros((3, 2, 1, 3), dtype=np.complex128)
    fields[0, 0, 0, 0] = 1.0
    fields[1, 1, 0, 1] = 1.0
    fields[2, 0, 0, 2] = 1.0
    snapshots = tuple(
        adapt_mpb_h_envelopes(
            (0.1 + index * 0.01, 0.2),
            (0.0, 1.0, 5.0),
            fields,
            orthogonality_tolerance=1e-12,
        )
        for index in range(4)
    )
    result = qualify_mpb_spectral_path(
        snapshots,
        [(0, 1)] * 4,
        thresholds=SubspaceQualificationThresholds(
            min_singular_value=0.9,
            max_principal_angle=0.45,
            max_projector_distance=0.2,
            min_external_gap=1.0,
        ),
        closed=False,
        require_live=False,
    )
    assert result.status == PATH_SUBSPACE_QUALIFIED
    assert result.is_live_qualified is False
    assert all(vertex.dimension == 2 for vertex in result.vertices)
    assert all(vertex.ambient_dimension == 6 for vertex in result.vertices)


def test_bridge_rejects_duplicate_rank_mismatch_and_untrusted_live_input():
    snapshots = tuple(static_snapshot() for _ in range(2))
    with pytest.raises(ValueError, match="duplicate"):
        qualify_mpb_spectral_path(
            snapshots, [(0, 0), (0, 0)],
            thresholds=LIVE_THRESHOLDS, closed=False, require_live=False,
        )
    with pytest.raises(ValueError, match="live-extraction"):
        qualify_mpb_spectral_path(
            snapshots, [(0,), (0,)],
            thresholds=LIVE_THRESHOLDS, closed=False,
        )
    with pytest.raises(ValueError, match="out-of-range"):
        qualify_mpb_spectral_path(
            snapshots, [(0, 2), (0, 2)],
            thresholds=LIVE_THRESHOLDS, closed=False, require_live=False,
        )


def test_bridge_result_is_immutable_json_safe_and_path_only():
    snapshots = tuple(static_snapshot(bands=3, frequencies=(0.0, 1.0, 5.0)) for _ in range(2))
    result = qualify_mpb_spectral_path(
        snapshots, [(0, 1), (0, 1)],
        thresholds=SubspaceQualificationThresholds(
            min_singular_value=0.9,
            max_principal_angle=0.45,
            max_projector_distance=0.2,
            min_external_gap=1.0,
        ),
        closed=False,
        require_live=False,
    )
    encoded = json.dumps(result.to_dict())
    lowered = encoded.lower()
    assert "berry" not in lowered
    assert "wilson" not in lowered
    assert "chern" not in lowered
    assert "physical_band_id" not in lowered
    assert "branch_id" not in lowered
    assert "adiabatic_band_id" not in lowered
    with pytest.raises(TypeError):
        result.provenance["new"] = "not allowed"
