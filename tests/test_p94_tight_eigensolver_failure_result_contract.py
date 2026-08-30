from __future__ import annotations

import importlib.util
import py_compile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "audit" / "local_affine" / "third_scale_6_state_tight_eigensolver_live_acquisition.py"


def _module():
    spec = importlib.util.spec_from_file_location("p94_acquisition", TARGET)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_synthetic_pass_uses_live_schema_and_exact_counts():
    module = _module()
    result = module.success_result(
        "MEPHC-P94-TEST",
        {"dataset_id": "d" * 64, "manifest_sha256": "m" * 64},
        0.2,
        True,
        [{"state_id": f"STATE_{index:02d}"} for index in range(14, 20)],
    )
    assert result["schema"] == "mephc-local-affine-third-scale-tight-eigensolver-live-acquisition-v1"
    assert "p92" not in result["schema"].lower()
    assert result["scientific_acceptance_status"] == "PASS"
    assert result["dataset_record_count"] == result["completed_state_count"] == 6
    assert result["native_invocation_count"] == 1
    assert result["provider_execution_count"] == result["solver_execution_count"] == 6
    assert result["field_payload_retained"] is False


def test_synthetic_first_state_failure_is_flat_and_bounded():
    module = _module()
    failed = {
        "failed_state_id": "STATE_14",
        "failed_stage": "PROVIDER_SOLVE",
        "failure_code": "UNOBSERVED_TEST_FAILURE",
        "exception_type": "RuntimeError",
        "completed_state_count": 0,
    }
    result = module.failure_result("MEPHC-P94-TEST", failed, provider_count=1, solver_count=1, dataset_record_count=0)
    assert result["schema"] == "mephc-local-affine-third-scale-tight-eigensolver-live-acquisition-v1"
    assert result["scientific_acceptance_status"] == "FAIL"
    assert result["status"] == "PASS"
    for field in ("failed_state_id", "failed_stage", "failure_code", "exception_type", "completed_state_count"):
        assert result[field] == failed[field]
    assert result["native_invocation_count"] == 1
    assert result["provider_execution_count"] == 1
    assert result["solver_execution_count"] == 1
    assert result["dataset_record_count"] == 0
    assert result["field_payload_retained"] is False
    assert "failed_state" not in result


def test_live_schema_is_not_the_p92_preparation_schema():
    module = _module()
    source = TARGET.read_text(encoding="utf-8")
    assert module.RESULT_SCHEMA == "mephc-local-affine-third-scale-tight-eigensolver-live-acquisition-v1"
    assert "mephc-local-affine-p92-third-scale-tight-eigensolver-sensitivity-preparation-v1" not in source


def test_tight_solver_configuration_is_preserved():
    module = _module()
    assert module.SOLVER_CONFIGURATION == {
        "resolution": 64,
        "num_bands": 6,
        "polarization": "TM",
        "eigensolver_tolerance": 1e-9,
        "mesh_size": 3,
        "deterministic": True,
        "phase_callback": None,
    }


def test_entrypoint_compiles_and_keeps_future_acquisition_guards():
    module = _module()
    assert module is not None
    py_compile.compile(str(TARGET), doraise=True)
    source = TARGET.read_text(encoding="utf-8")
    for required in ("encode_snapshot", "isinstance(spec.geometry, tuple)", "identity_before == identity_after", "eigensolver_tolerance=1e-9", "MEPHC_RESULT_PATH"):
        assert required in source
