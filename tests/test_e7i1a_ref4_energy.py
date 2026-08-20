import json
import numpy as np

from mephc.mpb_energy_spectral import MPB_ENERGY_EH_REPRESENTATION, adapt_mpb_energy_eh_envelopes


def fields():
    e = np.zeros((2, 1, 2, 3), dtype=complex)
    h = np.zeros_like(e)
    e[0, 0, 0, 0] = 1.0
    h[0, 0, 0, 1] = 2.0
    e[1, 0, 1, 2] = 2.0j
    h[1, 0, 1, 0] = -1.0
    return e, h


def test_energy_self_overlap_and_single_epsilon_weight():
    e, h = fields()
    snapshot = adapt_mpb_energy_eh_envelopes((0.0, 0.0), (1.0, 2.0), e, h, np.full((1, 2), 4.0))
    assert snapshot.provenance["representation"] == MPB_ENERGY_EH_REPRESENTATION
    assert snapshot.e_fields is not None
    assert np.allclose(np.diag(snapshot.gram_matrix), 1.0)
    # For band 1: epsilon*|E|^2 + |H|^2 = 4 + 4, with no double epsilon.
    assert snapshot.raw_norms[0] == np.sqrt(8.0)


def test_energy_phase_covariance_and_identical_state_overlap():
    e, h = fields()
    baseline = adapt_mpb_energy_eh_envelopes((0.0, 0.0), (1.0, 2.0), e, h, np.full((1, 2), 4.0))
    phase = np.exp(0.37j)
    rotated = adapt_mpb_energy_eh_envelopes((0.0, 0.0), (1.0, 2.0), e * phase, h * phase, np.full((1, 2), 4.0))
    assert np.allclose(np.abs(baseline.gram_matrix), np.abs(rotated.gram_matrix))
    assert abs(np.vdot(baseline[0].vector, rotated[0].vector) - phase) <= 1e-14
    assert abs(np.vdot(rotated[0].vector, rotated[0].vector) - 1.0) <= 1e-14


def test_energy_provenance_is_json_safe_and_distinct_from_h_only():
    e, h = fields()
    snapshot = adapt_mpb_energy_eh_envelopes((0.0, 0.0), (1.0, 2.0), e, h, np.ones((1, 2)), provenance={"fixture": "REF4"})
    encoded = json.dumps(snapshot.to_dict(include_h_fields=True, include_vectors=True))
    assert json.loads(encoded)["provenance"]["representation"] == MPB_ENERGY_EH_REPRESENTATION
    assert "h-only" not in encoded.lower()
    assert "double" not in encoded.lower()
