from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "audit" / "local_affine" / "local_dimensionless_trajectory_benchmark.py"


def _module():
    spec = importlib.util.spec_from_file_location("p111_benchmark", TARGET)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _record(module, omega):
    return {"grad_q_freq_x": 1e-7, "grad_q_freq_y": -0.09, "omega_qx_qy": omega, "omega_qx_s": module.CERTIFIED["omega_qx_s"], "omega_qy_s": 0.0, "partial_s_freq": module.CERTIFIED["partial_s_freq"]}


def test_p110_keyerror_reproducer_now_has_explicit_canonical_shape():
    module = _module()
    assert module.CANONICAL_COEFFICIENT_FIELDS == ("grad_q_freq_x", "grad_q_freq_y", "omega_qx_qy", "omega_qx_s", "omega_qy_s", "partial_s_freq")
    primary = _record(module, 1.25)
    refined = _record(module, 1.2)
    module.validate_canonical_coefficient_record(primary)
    module.validate_canonical_coefficient_record(refined)
    with pytest.raises(ValueError, match="P111_CANONICAL_COEFFICIENT_FIELDS_INVALID"):
        module.validate_canonical_coefficient_record({"omega_qx_qy": 1.25})


def test_missing_required_coefficient_does_not_get_a_silent_default():
    module = _module()
    missing = _record(module, 1.25)
    del missing["omega_qx_qy"]
    with pytest.raises(ValueError, match="P111_CANONICAL_COEFFICIENT_FIELDS_INVALID"):
        module.validate_canonical_coefficient_record(missing)
    source = TARGET.read_text(encoding="utf-8")
    assert '"omega_qx_qy": 0.0' not in source
    assert "result.get(\"omega_qx_qy\"" not in source


def test_synthetic_end_to_end_benchmark_reaches_compact_pass_with_shared_schema(monkeypatch):
    module = _module()
    primary = _record(module, 1.25)
    refined = _record(module, 1.2)
    monkeypatch.setattr(module, "reconstruct_coefficients", lambda _states: {"primary": {"omega_qx_qy": 1.25}, "refined": {"omega_qx_qy": 1.2}, "grad_q_frequency": {"primary": [1e-7, -0.09], "refined": [1.1e-7, -0.089]}, "reconstruction": "synthetic"})
    monkeypatch.setattr(module, "canonical_coefficient_record", lambda coefficients: primary if coefficients.omega_qx_qy == 1.25 else refined)
    trajectory = {"endpoint": [0.01, -0.04], "q_endpoint": [0.0, -0.616], "rho": [[0.0, 0.0], [0.01, -0.04]], "q": [[0.0, -0.6166666667], [0.0, -0.616]], "times": [0.0, 0.5], "integrator": "CLASSICAL_RK4_FIXED_STEP_V1"}
    monkeypatch.setattr(module, "_trajectory", lambda *args, **kwargs: trajectory)
    result = module.benchmark({})
    assert result["scientific_acceptance_status"] == "PASS"
    assert result["primary_omega_qx_qy"] == 1.25
    assert result["refined_omega_qx_qy"] == 1.2
    assert result["primary_transverse_displacement"] == -0.04
    assert result["benchmark_classification"] == "CANONICAL_DIMENSIONLESS_VALIDATION_ONLY_NOT_A_PHYSICAL_DEVICE_PREDICTION"


def test_all_runtime_branches_are_built_from_coefficients_before_projection():
    source = TARGET.read_text(encoding="utf-8")
    assert source.count("canonical_coefficient_record") >= 3
    assert "primary_record = canonical_coefficient_record(coefficients)" in source
    assert "refined_record = canonical_coefficient_record(refined_coefficients)" in source
    assert "return compact_success_projection(full_result)" in source
