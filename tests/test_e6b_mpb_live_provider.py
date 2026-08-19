import json

import numpy as np
import pytest

import meep as mp
from meep import mpb

from mephc.mpb_spectral_provider import (
    MPB_LIVE_H_PROVIDER_REPRESENTATION,
    MPBLiveSpectralProvider,
    solve_mpb_h_spectrum,
)
from mephc.spectral_association import CLEAR, RawAssociationThresholds, associate_raw_states


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


def manual_solver():
    geometry, lattice = benchmark()
    reciprocal = mp.cartesian_to_reciprocal(mp.Vector3(0.17, 0.23), lattice)
    solver = mpb.ModeSolver(
        geometry=geometry,
        geometry_lattice=lattice,
        k_points=[reciprocal],
        resolution=6,
        num_bands=2,
        default_material=mp.air,
        tolerance=1e-7,
        deterministic=True,
        mesh_size=3,
    )
    solver.run_parity(mp.TE, False)
    return solver, reciprocal


def test_live_provider_matches_independent_manual_periodic_h_extraction():
    snapshot = provider().solve((0.17, 0.23))
    solver, reciprocal = manual_solver()
    assert np.allclose(snapshot.frequencies, np.asarray(solver.all_freqs[0]), atol=1e-10)
    for band in range(1, 3):
        raw = np.asarray(solver.get_hfield(band, bloch_phase=False))
        manual = raw[:, :, 0, :].reshape(-1) if raw.ndim == 4 else raw.reshape(-1)
        manual /= np.linalg.norm(manual)
        assert abs(np.vdot(snapshot[band - 1].vector, manual)) > 1.0 - 1e-8
    assert snapshot.provenance["live_mpb_extraction_validated"] is True
    assert snapshot.provenance["mpb_k_point"] == (0.17, 0.23, 0.0)
    assert snapshot.provenance["caller_provenance"]["live_provider"] == MPB_LIVE_H_PROVIDER_REPRESENTATION
    assert snapshot[0].metadata["representation_provenance"]["live_mpb_extraction_validated"] is True


def test_live_false_and_true_h_fields_have_expected_mpb_metadata_and_magnitudes():
    solver, reciprocal = manual_solver()
    periodic = solver.get_hfield(1, bloch_phase=False)
    bloch = solver.get_hfield(1, bloch_phase=True)
    assert periodic.bloch_phase is False
    assert bloch.bloch_phase is True
    assert tuple(float(getattr(periodic.kpoint, axis)) for axis in ("x", "y", "z")) == pytest.approx(
        tuple(float(getattr(reciprocal, axis)) for axis in ("x", "y", "z"))
    )
    assert np.allclose(np.abs(np.asarray(periodic)), np.abs(np.asarray(bloch)), atol=1e-10)
    assert not np.allclose(np.asarray(periodic), np.asarray(bloch))


def test_phase_callback_preserves_frequencies_and_one_dimensional_projectors():
    baseline = provider().solve((0.17, 0.23))
    phased = provider(phase_callback=mpb.fix_hfield_phase).solve((0.17, 0.23))
    assert np.allclose(baseline.frequencies, phased.frequencies, atol=1e-10)
    for left, right in zip(baseline, phased):
        assert abs(np.vdot(left.vector, right.vector)) > 1.0 - 1e-8
    assert phased.provenance["caller_provenance"]["solver_settings"]["phase_callback"].endswith("fix_hfield_phase")


def test_nearby_live_batches_enter_existing_e3_association_without_identity_claim():
    left = provider(num_bands=1).solve((0.17, 0.23))
    right = provider(num_bands=1).solve((0.18, 0.24))
    result = associate_raw_states(
        [left[0]],
        [right[0]],
        thresholds=RawAssociationThresholds(
            probability_threshold=0.8,
            margin_threshold=0.0,
            assignment_margin_threshold=0.0,
        ),
    )
    assert result.status == CLEAR
    assert "physical" not in json.dumps(left[0].to_dict()).lower()
    assert "band_id" not in json.dumps(left[0].to_dict()).lower()


def test_live_result_is_readonly_json_safe_and_static_adapter_is_not_trusted_live():
    snapshot = solve_mpb_h_spectrum(
        (0.17, 0.23),
        geometry=benchmark()[0],
        geometry_lattice=benchmark()[1],
        resolution=6,
        num_bands=2,
        deterministic=True,
        mesh_size=3,
    )
    with pytest.raises(ValueError):
        snapshot.h_fields.flat[0] = 2.0
    with pytest.raises(ValueError):
        snapshot.gram_matrix.flat[0] = 2.0
    encoded = json.dumps(snapshot.to_dict(include_h_fields=False, include_vectors=True))
    assert json.loads(encoded)["provenance"]["live_mpb_extraction_validated"] is True
    assert "berry" not in encoded.lower()
    assert "wilson" not in encoded.lower()
    assert "chern" not in encoded.lower()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"resolution": 0},
        {"num_bands": 0},
        {"eigensolver_tolerance": 0.0},
        {"mesh_size": 0},
        {"deterministic": 1},
    ],
)
def test_provider_controls_fail_closed(kwargs):
    geometry, lattice = benchmark()
    with pytest.raises(ValueError):
        config = {"resolution": 6, "num_bands": 2}
        config.update(kwargs)
        MPBLiveSpectralProvider(geometry=geometry, geometry_lattice=lattice, **config)


def test_provider_rejects_invalid_public_k_point():
    with pytest.raises(ValueError):
        provider().solve((0.17,))
    with pytest.raises(ValueError):
        provider().solve((0.17, np.nan))
