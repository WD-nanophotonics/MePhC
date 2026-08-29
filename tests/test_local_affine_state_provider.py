from __future__ import annotations

from types import SimpleNamespace
import sys

import numpy as np
import pytest

import mephc.local_affine_state_provider as provider_module
from mephc.local_affine_state_provider import (
    LOCAL_AFFINE_H_REPRESENTATION,
    LocalAffineProviderError,
    LocalAffineStateProvider,
    canonical_local_affine_state_identity,
    digest_local_affine_state_identity,
)
from mephc.mpb_spectral import MPBHEnvelopeSnapshot, adapt_mpb_h_envelopes


class Size:
    x = 1.0
    y = 1.0


class Lattice:
    size = Size()


def synthetic_state(**changes):
    values = {
        "model_id": "GENERIC_LOCAL_AFFINE_MODEL",
        "reference_cell_id": "GENERIC_REFERENCE_CELL",
        "reference_cell_identity": "GENERIC_REFERENCE_CELL",
        "public_q": (0.125, -0.375),
        "s": 0.02,
        "F_s": ((1.0, 0.0), (0.0, 1.0)),
        "A_s": ((1.0, 0.0), (0.0, 1.0)),
        "derived_kappa": (0.125, -0.375),
        "geometry_digest": "geometry-digest",
        "geometry": (),
        "geometry_lattice": Lattice(),
    }
    values.update(changes)
    return SimpleNamespace(**values)


def fields():
    result = np.zeros((6, 64, 64, 3), dtype=complex)
    for band in range(6):
        result[band, band, 0, band % 3] = band + 1.0
    return result


def snapshot(state, *, top=None, caller=None, metadata=None):
    identity = canonical_local_affine_state_identity(state)
    provenance = {"mpb_k_point": list(top or (*identity["derived_kappa"], 0.0))}
    if caller is not None:
        provenance.update(caller)
    if metadata:
        provenance.update(metadata)
    return adapt_mpb_h_envelopes(
        tuple(identity["public_q"]), (1, 2, 3, 4, 5, 6), fields(),
        mpb_k_point=provenance.pop("mpb_k_point"), provenance=provenance,
    )


def replace_provenance(value, **updates):
    provenance = dict(value.provenance)
    provenance.update(updates)
    return MPBHEnvelopeSnapshot(
        k_point=value.k_point, frequencies=value.frequencies, h_fields=value.h_fields,
        raw_norms=value.raw_norms, normalized_vectors=value.normalized_vectors,
        gram_matrix=value.gram_matrix, max_normalization_error=value.max_normalization_error,
        max_off_diagonal_gram=value.max_off_diagonal_gram,
        orthogonality_status=value.orthogonality_status,
        normalization_tolerance=value.normalization_tolerance,
        orthogonality_tolerance=value.orthogonality_tolerance,
        raw_eigenstates=value.raw_eigenstates, provenance=provenance, e_fields=value.e_fields,
    )


def install_fake_provider(monkeypatch, result):
    class FakeProvider:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def solve(self, _q):
            return result

    monkeypatch.setattr(provider_module, "MPBLiveSpectralProvider", FakeProvider)


def test_canonical_identity_is_complete_and_deterministic_without_meep():
    state = synthetic_state()
    first = canonical_local_affine_state_identity(state)
    second = canonical_local_affine_state_identity(state)
    assert list(first) == [
        "model_id", "reference_cell_id", "public_q", "s", "F_s", "A_s", "derived_kappa",
        "geometry_digest", "resolution", "num_bands", "polarization", "eigensolver_tolerance",
        "mesh_size", "deterministic", "h_representation", "bloch_phase_excluded",
        "component_basis", "mu_contract", "orientation_sign",
        "fractional_material_indexing_identity", "reference_cell_identity", "bloch_phase_convention",
    ]
    assert first == second
    assert digest_local_affine_state_identity(first) == digest_local_affine_state_identity(second)
    assert "meep" not in sys.modules


def test_success_binds_identity_and_preserves_payload_and_provenance(monkeypatch):
    state = synthetic_state()
    source = snapshot(state, caller={"mpb_reciprocal_k_point": [0.125, -0.375, 0.0], "tag": "source"})
    install_fake_provider(monkeypatch, source)
    result = LocalAffineStateProvider().solve(state)
    assert result is not source
    assert np.array_equal(result.frequencies, source.frequencies)
    assert np.array_equal(result.h_fields, source.h_fields)
    assert np.array_equal(result.raw_norms, source.raw_norms)
    assert np.array_equal(result.gram_matrix, source.gram_matrix)
    assert result.provenance["caller_provenance"]["tag"] == "source"
    identity = canonical_local_affine_state_identity(state)
    assert result.to_dict()["provenance"]["local_affine_state_identity"] == identity
    assert result.provenance["local_affine_state_identity_sha256"] == digest_local_affine_state_identity(identity)
    assert result.provenance["local_affine_reference_cell_contract"]["reference_cell_identity"] == state.reference_cell_id


@pytest.mark.parametrize(
    "changes, match",
    [
        ({"derived_kappa": (0.0, 0.0)}, "derived_kappa"),
        ({"public_q": (0.0, 0.0)}, "derived_kappa"),
        ({"reference_cell_id": "other"}, "reference_cell_identity"),
        ({"reference_cell_identity": "other"}, "reference_cell_identity"),
        ({"h_representation": "wrong"}, "h_representation"),
        ({"bloch_phase_excluded": False}, "bloch_phase_excluded"),
        ({"component_basis": "wrong"}, "component_basis"),
        ({"mu_contract": "wrong"}, "mu_contract"),
        ({"orientation_sign": -1}, "orientation_sign"),
        ({"resolution": 32}, "resolution"),
        ({"bloch_phase_convention": "included"}, "bloch_phase_convention"),
    ],
)
def test_state_contract_mismatches_fail_closed(monkeypatch, changes, match):
    state = synthetic_state(**changes)
    install_fake_provider(monkeypatch, None)
    with pytest.raises(LocalAffineProviderError, match=match):
        LocalAffineStateProvider().solve(state)


@pytest.mark.parametrize(
    "metadata, match",
    [
        ({"representation": "wrong"}, "REPRESENTATION"),
        ({"periodic_h_envelope": False}, "PERIODIC_H_ENVELOPE"),
        ({"bloch_phase_excluded": False}, "BLOCH_PHASE_EXCLUDED"),
        ({"component_count": 2}, "COMPONENT_COUNT"),
        ({"spatial_shape": [1, 1]}, "SPATIAL_SHAPE"),
        ({"component_order": "wrong"}, "COMPONENT_ORDER"),
        ({"component_basis": "wrong"}, "COMPONENT_BASIS"),
        ({"mu_contract": "wrong"}, "MU_CONTRACT"),
        ({"orientation_sign": -1}, "ORIENTATION_SIGN"),
        ({"resolution": 32}, "RESOLUTION"),
    ],
)
def test_provider_result_metadata_mismatches_fail_closed(monkeypatch, metadata, match):
    state = synthetic_state()
    install_fake_provider(monkeypatch, snapshot(state, metadata=metadata))
    with pytest.raises(LocalAffineProviderError, match=match):
        LocalAffineStateProvider().solve(state)


def test_wrong_geometry_identity_in_provider_result_fails_closed(monkeypatch):
    state = synthetic_state()
    identity = canonical_local_affine_state_identity(state)
    identity["geometry_digest"] = "wrong"
    install_fake_provider(monkeypatch, snapshot(state, metadata={"local_affine_state_identity": identity}))
    with pytest.raises(LocalAffineProviderError, match="STATE_IDENTITY"):
        LocalAffineStateProvider().solve(state)


def test_top_level_reciprocal_mismatch_fails_closed(monkeypatch):
    state = synthetic_state()
    install_fake_provider(monkeypatch, snapshot(state, top=(0.2, -0.375, 0.0)))
    with pytest.raises(LocalAffineProviderError, match="RECIPROCAL"):
        LocalAffineStateProvider().solve(state)


def test_caller_reciprocal_disagreement_fails_closed(monkeypatch):
    state = synthetic_state()
    install_fake_provider(monkeypatch, snapshot(state, caller={"mpb_reciprocal_k_point": [0.2, -0.375, 0.0]}))
    with pytest.raises(LocalAffineProviderError, match="CALLER_RECIPROCAL"):
        LocalAffineStateProvider().solve(state)


def test_nonfinite_frequency_is_rejected_by_snapshot_adapter():
    bad = fields()
    with pytest.raises(ValueError, match="finite"):
        adapt_mpb_h_envelopes((0.125, -0.375), (1, np.nan, 3, 4, 5, 6), bad, mpb_k_point=(0.125, -0.375, 0.0))


def test_nonfinite_and_nonunit_normalized_vectors_fail_closed(monkeypatch):
    state = synthetic_state()
    source = snapshot(state)
    bad_vectors = list(source.normalized_vectors)
    bad_vectors[0] = bad_vectors[0] * 2.0
    bad = replace_provenance(source)
    bad = MPBHEnvelopeSnapshot(
        k_point=bad.k_point, frequencies=bad.frequencies, h_fields=bad.h_fields,
        raw_norms=bad.raw_norms, normalized_vectors=tuple(bad_vectors), gram_matrix=bad.gram_matrix,
        max_normalization_error=bad.max_normalization_error, max_off_diagonal_gram=bad.max_off_diagonal_gram,
        orthogonality_status=bad.orthogonality_status, normalization_tolerance=bad.normalization_tolerance,
        orthogonality_tolerance=bad.orthogonality_tolerance, raw_eigenstates=bad.raw_eigenstates,
        provenance=bad.provenance, e_fields=bad.e_fields,
    )
    install_fake_provider(monkeypatch, bad)
    with pytest.raises(LocalAffineProviderError, match="NONUNIT"):
        LocalAffineStateProvider().solve(state)


def test_meep_remains_absent_before_and_after_provider_tests():
    assert "meep" not in sys.modules
    assert LOCAL_AFFINE_H_REPRESENTATION == "mpb_periodic_h_l2_v1"
    assert "meep" not in sys.modules
