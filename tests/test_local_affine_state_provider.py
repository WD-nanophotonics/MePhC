from __future__ import annotations

import numpy as np
import pytest

from audit.e10f.e8b_local_affine_model import geometry_anchor_status, make_state
from mephc.local_affine_state_provider import LocalAffineProviderError, LocalAffineStateProvider


def test_e8b_anchors_and_public_q_to_kappa_binding_are_deterministic():
    assert geometry_anchor_status()
    state = make_state((0.0, -37.0 / 60.0), 0.01)
    assert np.allclose(np.asarray(state.derived_kappa), np.asarray(state.A_s).T @ np.asarray(state.q))
    assert state.model_id == "E8B_TWO_INCLUSION_AREA_PRESERVING_AFFINE_V1"


def test_provider_rejects_wrong_model_before_live_call():
    state = make_state((0.0, -37.0 / 60.0), 0.0)
    object.__setattr__(state, "model_id", "WRONG")
    with pytest.raises(LocalAffineProviderError, match="MODEL_ID_MISMATCH"):
        LocalAffineStateProvider().solve(state)
