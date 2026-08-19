import json

import numpy as np
import pytest

from mephc.mpb_spectral import (
    MPB_H_ENVELOPE_QUALIFIED,
    MPB_H_ENVELOPE_REPRESENTATION,
    MPB_H_ENVELOPE_UNQUALIFIED,
    MPBHEnvelopeSnapshot,
    adapt_mpb_h_envelopes,
)
from mephc.spectral_association import CLEAR, RawAssociationThresholds, associate_raw_states


def orthogonal_fields():
    fields = np.zeros((3, 2, 1, 3), dtype=complex)
    fields[0, 0, 0, 0] = 2.0
    fields[1, 1, 0, 1] = 3.0j
    fields[2, 0, 0, 2] = -4.0
    return fields


def test_snapshot_adapts_ordered_raw_states_with_exact_h_metric():
    fields = orthogonal_fields()
    snapshot = adapt_mpb_h_envelopes(
        (0.1, 0.2),
        (1.0, 2.0, 3.0),
        fields,
        mpb_k_point=(4.0, 5.0),
        provenance={"fixture": "E6A"},
    )
    assert isinstance(snapshot, MPBHEnvelopeSnapshot)
    assert snapshot.k_point == (0.1, 0.2)
    assert snapshot.spatial_shape == (2, 1)
    assert snapshot.bands == 3
    assert snapshot.status == snapshot.orthogonality_status == MPB_H_ENVELOPE_QUALIFIED
    assert snapshot.is_qualified
    assert np.allclose(snapshot.raw_norms, (2.0, 3.0, 4.0))
    assert np.allclose(snapshot.gram_matrix, np.eye(3))
    assert all(np.isclose(np.linalg.norm(state.vector), 1.0) for state in snapshot)
    assert [state.solver_index for state in snapshot] == [0, 1, 2]
    assert snapshot.provenance["representation"] == MPB_H_ENVELOPE_REPRESENTATION
    assert snapshot.provenance["mpb_k_point"] == (4.0, 5.0)
    assert snapshot.provenance["solver_index_semantics"] == "ordering metadata only"


def test_manual_h_overlap_matches_normalized_raw_state_overlap():
    fields = np.zeros((2, 1, 2, 3), dtype=complex)
    fields[0, 0, 0, 0] = 1.0
    fields[0, 0, 1, 1] = 2.0j
    fields[1, 0, 0, 0] = 2.0
    fields[1, 0, 1, 1] = 1.0j
    snapshot = adapt_mpb_h_envelopes((0.0,), (1.0, 2.0), fields)
    left = fields[0].reshape(-1)
    right = fields[1].reshape(-1)
    expected = np.vdot(left, right) / (np.linalg.norm(left) * np.linalg.norm(right))
    assert np.allclose(np.vdot(snapshot[0].vector, snapshot[1].vector), expected)


def test_qualified_batch_passes_existing_e3_raw_gram_validation():
    snapshot = adapt_mpb_h_envelopes((0.0,), (1.0, 2.0, 3.0), orthogonal_fields())
    result = associate_raw_states(
        snapshot,
        snapshot,
        thresholds=RawAssociationThresholds(
            probability_threshold=0.9,
            margin_threshold=0.1,
            assignment_margin_threshold=0.1,
        ),
    )
    assert result.status == CLEAR


def test_phase_rotation_changes_only_one_vector_and_preserves_gram_magnitudes():
    fields = orthogonal_fields()
    phase = np.exp(0.37j)
    rotated_fields = fields.copy()
    rotated_fields[1] *= phase
    baseline = adapt_mpb_h_envelopes((0.0,), (1.0, 2.0, 3.0), fields)
    rotated = adapt_mpb_h_envelopes((0.0,), (1.0, 2.0, 3.0), rotated_fields)
    assert np.allclose(rotated[0].vector, baseline[0].vector)
    assert np.allclose(rotated[1].vector, phase * baseline[1].vector)
    assert np.allclose(np.abs(rotated.gram_matrix), np.abs(baseline.gram_matrix))


def test_solver_permutation_only_permuted_output_order_and_frequencies():
    fields = orthogonal_fields()
    permutation = (2, 0, 1)
    permuted_fields = fields[list(permutation)]
    permuted = adapt_mpb_h_envelopes((0.0,), np.asarray((1.0, 2.0, 3.0))[list(permutation)], permuted_fields)
    baseline = adapt_mpb_h_envelopes((0.0,), (1.0, 2.0, 3.0), fields)
    for output_index, baseline_index in enumerate(permutation):
        assert permuted[output_index].solver_index == output_index
        assert permuted[output_index].eigenvalue == baseline[baseline_index].eigenvalue
        assert np.allclose(permuted[output_index].vector, baseline[baseline_index].vector)


def test_nonorthogonal_batch_is_inspectable_but_not_qualified_and_not_repaired():
    fields = np.zeros((2, 1, 1, 3), dtype=complex)
    fields[0, 0, 0] = (1.0, 0.0, 0.0)
    fields[1, 0, 0] = (1.0, 1.0, 0.0)
    snapshot = adapt_mpb_h_envelopes((0.0,), (1.0, 2.0), fields)
    expected = 1.0 / np.sqrt(2.0)
    assert snapshot.status == MPB_H_ENVELOPE_UNQUALIFIED
    assert snapshot.max_off_diagonal_gram == pytest.approx(expected)
    assert np.vdot(snapshot[0].vector, snapshot[1].vector) == pytest.approx(expected)
    assert not np.allclose(snapshot.gram_matrix, np.eye(2))


@pytest.mark.parametrize(
    "fields",
    [
        np.zeros((2, 2, 3), dtype=complex),
        np.zeros((2, 2, 2, 2), dtype=complex),
        np.zeros((0, 2, 2, 3), dtype=complex),
        np.zeros((2, 0, 2, 3), dtype=complex),
        np.zeros((2, 2, 0, 3), dtype=complex),
    ],
)
def test_shape_contract_is_strict(fields):
    with pytest.raises(ValueError, match="numeric|shape"):
        adapt_mpb_h_envelopes((0.0,), (1.0, 2.0), fields)


def test_numeric_frequency_and_finite_input_contract_is_strict():
    with pytest.raises(ValueError, match="numeric"):
        adapt_mpb_h_envelopes((0.0,), (1.0, 2.0), [["bad"]])
    with pytest.raises(ValueError, match="real"):
        adapt_mpb_h_envelopes((0.0,), np.array([1.0 + 1.0j, 2.0]), orthogonal_fields()[:2])
    bad = orthogonal_fields()[:2].copy()
    bad[0, 0, 0, 0] = np.nan
    with pytest.raises(ValueError, match="finite"):
        adapt_mpb_h_envelopes((0.0,), (1.0, 2.0), bad)
    with pytest.raises(ValueError, match="length"):
        adapt_mpb_h_envelopes((0.0,), (1.0,), orthogonal_fields()[:2])


def test_zero_norm_and_invalid_tolerance_are_rejected():
    fields = orthogonal_fields()[:2]
    fields[0] = 0.0
    with pytest.raises(ValueError, match="norm"):
        adapt_mpb_h_envelopes((0.0,), (1.0, 2.0), fields)
    with pytest.raises(ValueError, match="positive"):
        adapt_mpb_h_envelopes((0.0,), (1.0, 2.0), orthogonal_fields()[:2], norm_tolerance=0.0)


def test_readonly_arrays_and_json_safe_provenance():
    snapshot = adapt_mpb_h_envelopes((0.0,), (1.0, 2.0, 3.0), orthogonal_fields())
    for array in (snapshot.h_fields, snapshot.frequencies, snapshot.raw_norms, snapshot.gram_matrix, snapshot[0].vector):
        with pytest.raises(ValueError):
            array.flat[0] = 9.0
    encoded = json.dumps(snapshot.to_dict(include_h_fields=True, include_vectors=True))
    decoded = json.loads(encoded)
    assert decoded["provenance"]["representation"] == MPB_H_ENVELOPE_REPRESENTATION
    assert "berry" not in encoded.lower()
    assert "wilson" not in encoded.lower()
    assert "chern" not in encoded.lower()
