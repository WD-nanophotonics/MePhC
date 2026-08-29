from __future__ import annotations

from types import SimpleNamespace

from mephc.local_affine_state_provider import _metadata


def test_canonical_snapshot_representation_wins_over_nested_solver_representation():
    snapshot = SimpleNamespace(provenance={
        "representation": "mpb_periodic_h_l2_v1",
        "solver_settings": {
            "representation": "mpb_live_periodic_h_l2_v1",
            "resolution": 64,
            "polarization": "TM",
        },
    })

    metadata = _metadata(snapshot)

    assert metadata["representation"] == "mpb_periodic_h_l2_v1"
    assert metadata["resolution"] == 64
    assert metadata["polarization"] == "TM"

