from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "audit" / "local_affine" / "frozen_13_state_solver_free_reduction.py"


def _module():
    spec = importlib.util.spec_from_file_location("p74_reducer", TARGET)
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
    "missing_field",
    ["representation", "lattice_size", "fractional_material_indexing_identity", "reference_cell_identity"],
)
def test_missing_reference_cell_field_reports_exact_state_and_sorted_keys(missing_field):
    module = _module()
    reference = _reference()
    del reference[missing_field]

    with pytest.raises(module.ReferenceCellContractDiagnosticError) as caught:
        module.validate_snapshot_structure(_snapshot(reference), state_id="STATE_07", role="CENTER")

    error = caught.value
    assert error.code == "P72_REFERENCE_CELL_FIELD_MISSING"
    assert error.state_id == "STATE_07"
    assert error.missing_fields == (missing_field,)
    assert error.observed_keys == tuple(sorted(reference))
    assert f"state_id=STATE_07" in str(error)
    assert f"missing_fields={missing_field}" in str(error)
    assert f"observed_keys={','.join(sorted(reference))}" in str(error)


def test_non_mapping_reference_cell_contract_reports_only_bounded_type():
    module = _module()
    reference = ["raw-payload-marker", {"payload": "must-not-be-reported"}]

    with pytest.raises(module.ReferenceCellContractDiagnosticError) as caught:
        module.validate_snapshot_structure(_snapshot(reference), state_id="STATE_11", role="PERTURBED")

    error = caught.value
    assert error.code == "P74_REFERENCE_CELL_CONTRACT_NOT_MAPPING"
    assert error.state_id == "STATE_11"
    assert error.observed_type == "list"
    assert error.missing_fields == ()
    assert error.observed_keys == ()
    assert "list" in str(error)
    assert "raw-payload-marker" not in str(error)
    assert "must-not-be-reported" not in str(error)


def test_complete_reference_cell_contract_preserves_p72_validation_path():
    module = _module()
    module.validate_snapshot_structure(_snapshot(_reference()), state_id="STATE_01", role="CENTER")


def test_main_preserves_reference_cell_diagnostic_context_and_bounded_fields(monkeypatch, tmp_path):
    module = _module()
    result_path = tmp_path / "result.json"
    bundle = {"schema": module.THIN_BUNDLE_SCHEMA, "work_order_id": "P74", "datasets": []}
    plan = {
        "record_count": 0,
        "unique_record_key_count": 0,
        "source_work_order_id": module.SOURCE_WORK_ORDER_ID,
        "source_dataset_id": "dataset",
        "source_manifest_sha256": "manifest",
        "schema": module.PLAN_SCHEMA,
    }

    monkeypatch.setenv("MEPHC_RESULT_PATH", str(result_path))
    monkeypatch.setattr(module, "load_bundle", lambda: (bundle, tmp_path))
    monkeypatch.setattr(module, "load_binding_plan", lambda: plan)

    def fail_in_state_resolution(*_args):
        raise module.ReferenceCellContractDiagnosticError(
            "P72_REFERENCE_CELL_FIELD_MISSING",
            state_id="STATE_13",
            role="REVERSE_QY_REFINED",
            observed_type="dict",
            missing_fields=("reference_cell_identity",),
            observed_keys=("component_basis", "representation"),
        )

    monkeypatch.setattr(module, "resolve_states", fail_in_state_resolution)
    assert module.main() == 0
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["schema"] == module.RESULT_SCHEMA
    assert result["scientific_acceptance_status"] == "FAIL"
    assert result["failed_state_id"] == "STATE_13"
    assert result["failure_code"] == "P72_REFERENCE_CELL_FIELD_MISSING"
    assert result["exception_type"] == "ReferenceCellContractDiagnosticError"
    assert result["reference_cell_missing_fields"] == "reference_cell_identity"
    assert result["reference_cell_observed_keys"] == "component_basis,representation"
    assert "reference_cell_observed_type" not in result
    assert result["native_invocation_count"] == 1
    assert result["provider_execution_count"] == 0
    assert result["solver_execution_count"] == 0
    assert result["dataset_record_count"] == 0
    assert result["mpb_execution"] is False
    assert result["field_payload_retained"] is False


def test_reducer_has_no_live_or_archived_scientific_runtime_escape_hatch():
    source = TARGET.read_text(encoding="utf-8")
    for forbidden in (
        "import meep", "from meep", "LocalAffineStateProvider",
        "MPBLiveSpectralProvider", "resolve_dataset_record", "archived runtime",
        ".solve(",
    ):
        assert forbidden not in source
