from __future__ import annotations

import importlib.util
from dataclasses import replace
from types import SimpleNamespace
from pathlib import Path

import numpy as np
import pytest

from mephc.phase_space_geometry import PhaseSpaceStateIdentity, ReferenceCellIdentity, h_state_from_normalized_vectors


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "audit" / "local_affine" / "frozen_13_state_solver_free_reduction.py"


def _module():
    spec = importlib.util.spec_from_file_location("p72_reducer", TARGET)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _states(module):
    graph = module.json.loads((ROOT / "audit" / "local_affine" / "p2_frozen_13_state_request_graph.json").read_text(encoding="utf-8"))
    reference = ReferenceCellIdentity(resolution=64, spatial_shape=(64, 64), lattice_size=(1.0, 1.0))
    vector = np.asarray([1.0 + 0.0j, 0.0j])
    states = {}
    for row in graph["states"]:
        q = tuple(row["public_q"])
        identity = PhaseSpaceStateIdentity(q, row["s"], q, ((1.0, 0.0), (0.0, 1.0)), ((1.0, 0.0), (0.0, 1.0)), "synthetic-geometry", reference, "synthetic-solver")
        frequency = 1.0 + 0.2 * float(row["s"]) + 0.1 * q[0] + 0.05 * q[1]
        states[row["role"]] = h_state_from_normalized_vectors(identity, vector, frequencies=(frequency,), band_indices=(0,))
    return states


def _snapshot(reference=None):
    reference = reference or {
        "representation": "mpb_periodic_h_l2_v1", "bloch_phase_excluded": True, "resolution": 64,
        "spatial_shape": [64, 64], "lattice_size": [1.0, 1.0], "component_order": "supplied final axis order",
        "component_basis": "LAB_CARTESIAN", "mu_contract": "MU1_NONMAGNETIC", "orientation_sign": 1,
        "fractional_material_indexing_identity": "same", "reference_cell_identity": "common",
    }
    vector = np.asarray([1.0 + 0.0j, 0.0j])
    return SimpleNamespace(
        spatial_shape=(64, 64), component_count=3, frequencies=np.ones(6), raw_norms=np.ones(6),
        normalized_vectors=tuple(vector.copy() for _ in range(6)), gram_matrix=np.eye(6, dtype=complex),
        provenance={"representation": "mpb_periodic_h_l2_v1", "local_affine_reference_cell_contract": reference},
    )


def test_complete_reduction_exercises_four_reverse_diamonds_and_flattened_scalars(monkeypatch):
    module = _module()
    states = _states(module)
    calls = []
    original = module.reverse_mixed_curvature

    def tracked(diamond):
        calls.append(diamond)
        return original(diamond)

    monkeypatch.setattr(module, "reverse_mixed_curvature", tracked)
    result = module.reduce_states(states)
    assert len(calls) == 4
    assert result["reverse_diamond_count"] == 4
    assert result["two_scale_reduction_status"] == "ESTIMATES_AVAILABLE"
    for field in ("omega_qx_s_primary", "omega_qx_s_refined", "omega_qy_s_primary", "omega_qy_s_refined", "domega_ds_primary", "domega_ds_refined", "abs_delta_omega_qx_s", "abs_delta_omega_qy_s", "abs_delta_domega_ds", "relative_delta_omega_qx_s", "relative_delta_omega_qy_s", "relative_delta_domega_ds"):
        assert field in result and (result[field] is None or np.isfinite(result[field]))


def test_reverse_orientation_mismatch_is_fail_closed(monkeypatch):
    module = _module()
    states = _states(module)
    def wrong_orientation(diamond):
        value = module.rank1_mixed_curvature(diamond)
        return replace(value, phase=0.1, omega_qs=0.1)

    monkeypatch.setattr(module, "reverse_mixed_curvature", wrong_orientation)
    with pytest.raises(ValueError, match="P72_REVERSE_ORIENTATION_SIGN_MISMATCH"):
        module.reduce_states(states)


@pytest.mark.parametrize("field,mutator,code", [
    ("frequencies", lambda s: setattr(s, "frequencies", np.array([np.nan] + [1.0] * 5)), "P72_FREQUENCIES_INVALID"),
    ("raw_norms", lambda s: setattr(s, "raw_norms", np.array([0.0] + [1.0] * 5)), "P72_RAW_NORMS_INVALID"),
    ("normalized_vectors", lambda s: setattr(s, "normalized_vectors", (np.array([np.nan + 0j, 0j]),) + s.normalized_vectors[1:]), "P72_VECTOR_INVALID"),
    ("gram_matrix", lambda s: setattr(s, "gram_matrix", np.full((6, 6), np.nan + 0j)), "P72_GRAM_INVALID"),
])
def test_snapshot_nonfinite_and_invalid_numeric_fields_fail_closed(field, mutator, code):
    module = _module()
    snapshot = _snapshot()
    mutator(snapshot)
    with pytest.raises(ValueError, match=code):
        module.validate_snapshot_structure(snapshot)


def test_reference_cell_missing_field_and_cross_state_lattice_mismatch_fail_closed():
    module = _module()
    snapshot = _snapshot()
    del snapshot.provenance["local_affine_reference_cell_contract"]["lattice_size"]
    with pytest.raises(ValueError, match="P72_REFERENCE_CELL_FIELD_MISSING"):
        module.validate_snapshot_structure(snapshot)
    states = _states(module)
    reference = ReferenceCellIdentity(resolution=64, spatial_shape=(64, 64), lattice_size=(2.0, 1.0))
    old = states["CENTER"].identity
    bad_identity = PhaseSpaceStateIdentity(old.public_q, old.s, old.derived_kappa, old.A_s, old.F_s, old.geometry_identity, reference, old.solver_configuration_identity)
    states["CENTER"] = h_state_from_normalized_vectors(bad_identity, states["CENTER"].h_vectors[0], frequencies=states["CENTER"].frequencies, band_indices=(0,))
    with pytest.raises(ValueError, match="P72_REFERENCE_CELL_CROSS_STATE_MISMATCH"):
        module.validate_cross_state_reference_cells(states)


def test_static_contract_contains_digest_detf_and_result_guards():
    source = TARGET.read_text(encoding="utf-8")
    for required in ("P71_REFERENCE_CELL_DIGEST_MISMATCH", "P72_DET_F_NONPOSITIVE", "P72_REVERSE_ORIENTATION_SIGN_MISMATCH", "P72_REFERENCE_CELL_CROSS_STATE_MISMATCH", "reverse_diamond_count", "relative_delta", "ESTIMATES_AVAILABLE", "field_payload_retained"):
        assert required in source
    assert "import meep" not in source and "from meep" not in source
    assert "resolve_dataset_record" not in source and "LocalAffineStateProvider" not in source and "MPBLiveSpectralProvider" not in source
    assert ".solve(" not in source
