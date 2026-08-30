from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "audit" / "local_affine" / "frozen_13_state_solver_free_reduction.py"


def _module():
    spec = importlib.util.spec_from_file_location("p76_reducer", TARGET)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _reference():
    return {
        "representation": "mpb_periodic_h_l2_v1",
        "bloch_phase_excluded": True,
        "resolution": 64,
        "spatial_shape": [64, 64],
        "lattice_size": [1.0, 1.0],
        "component_order": "supplied final axis order",
        "component_basis": "LAB_CARTESIAN",
        "mu_contract": "MU1_NONMAGNETIC",
        "orientation_sign": 1,
        "fractional_material_indexing_identity": "same",
        "reference_cell_identity": "common",
    }


def _snapshot(reference):
    return SimpleNamespace(
        spatial_shape=(64, 64),
        component_count=3,
        frequencies=np.ones(6),
        raw_norms=np.ones(6),
        normalized_vectors=tuple(np.asarray([1.0 + 0.0j, 0.0j]) for _ in range(6)),
        gram_matrix=np.eye(6, dtype=complex),
        provenance={
            "representation": "mpb_periodic_h_l2_v1",
            "local_affine_reference_cell_contract": reference,
        },
    )


@pytest.mark.parametrize(
    "field,observed,expected_value",
    [
        ("representation", "wrong-representation", "wrong-representation"),
        ("bloch_phase_excluded", False, False),
        ("resolution", 32, 32),
        ("spatial_shape", [32, 64], "32,64"),
    ],
)
def test_identity_value_mismatch_preserves_state_role_value_and_type(field, observed, expected_value):
    module = _module()
    reference = _reference()
    reference[field] = observed

    with pytest.raises(module.ReferenceCellIdentityDiagnosticError) as caught:
        module.validate_snapshot_structure(_snapshot(reference), state_id="STATE_09", role="REVERSE_QX_REFINED")

    error = caught.value
    assert error.code == "P72_REFERENCE_CELL_IDENTITY_INVALID"
    assert error.state_id == "STATE_09"
    assert error.role == "REVERSE_QX_REFINED"
    assert error.mismatch_fields == (field,)
    assert error.observed_values[field] == expected_value
    assert error.observed_types[field] == type(observed).__name__

    result = module._future_result("FAIL", failed_stage="bundle-or-reduction", diagnostic=error)
    assert result["schema"] == module.RESULT_SCHEMA
    assert result["scientific_acceptance_status"] == "FAIL"
    assert result["failed_state_id"] == "STATE_09"
    assert result["failed_role"] == "REVERSE_QX_REFINED"
    assert result["failure_code"] == "P72_REFERENCE_CELL_IDENTITY_INVALID"
    assert result["reference_cell_identity_mismatch_fields"] == field
    assert result[f"reference_cell_observed_{field}"] == expected_value
    assert result[f"reference_cell_observed_{field}_type"] == type(observed).__name__
    assert result["native_invocation_count"] == 1
    assert result["provider_execution_count"] == 0
    assert result["solver_execution_count"] == 0
    assert result["dataset_record_count"] == 0
    assert result["mpb_execution"] is False
    assert result["field_payload_retained"] is False


def test_two_identity_mismatches_are_sorted_and_comma_separated():
    module = _module()
    reference = _reference()
    reference["resolution"] = 32
    reference["representation"] = "wrong-representation"

    with pytest.raises(module.ReferenceCellIdentityDiagnosticError) as caught:
        module.validate_snapshot_structure(_snapshot(reference), state_id="STATE_04", role="PERTURBED")

    error = caught.value
    assert error.mismatch_fields == ("representation", "resolution")
    result = module._future_result("FAIL", failed_stage="bundle-or-reduction", diagnostic=error)
    assert result["reference_cell_identity_mismatch_fields"] == "representation,resolution"


def test_complete_expected_identity_preserves_downstream_validation_path():
    module = _module()
    module.validate_snapshot_structure(_snapshot(_reference()), state_id="STATE_01", role="CENTER")


def test_static_runtime_guards_remain_solver_free():
    source = TARGET.read_text(encoding="utf-8")
    for forbidden in (
        "import meep", "from meep", "LocalAffineStateProvider",
        "MPBLiveSpectralProvider", "resolve_dataset_record", "archived runtime",
        ".solve(",
    ):
        assert forbidden not in source
