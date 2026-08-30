from __future__ import annotations

import importlib.util
import math
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "audit" / "local_affine" / "frozen_13_state_solver_free_reduction.py"


def _module():
    spec = importlib.util.spec_from_file_location("p80_reducer", TARGET)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _curvature(phase, omega, *, area=None, singular=0.8, angle=0.4):
    area = -phase / omega if area is None and omega else (1.0 if area is None else area)
    return SimpleNamespace(
        phase=phase,
        omega_qs=omega,
        signed_area_qs=area,
        minimum_link_singular_value=singular,
        maximum_link_principal_angle=angle,
    )


def _run_four_pairs(module, monkeypatch, forward, reverse):
    monkeypatch.setattr(module, "_diamond", lambda *args: object())
    monkeypatch.setattr(module, "rank1_mixed_curvature", lambda _diamond: forward)
    monkeypatch.setattr(module, "reverse_mixed_curvature", lambda _diamond: reverse)
    monkeypatch.setattr(module, "fixed_q_frequency_derivative", lambda *args, **kwargs: 1.0)
    return module.reduce_states({role: object() for role in (
        "CENTER", "PRIMARY_PLUS_QX", "PRIMARY_MINUS_QX", "PRIMARY_PLUS_QY", "PRIMARY_MINUS_QY", "PRIMARY_PLUS_S", "PRIMARY_MINUS_S",
        "REFINED_PLUS_QX", "REFINED_MINUS_QX", "REFINED_PLUS_QY", "REFINED_MINUS_QY", "REFINED_PLUS_S", "REFINED_MINUS_S",
    )})


def test_exact_sign_reversal_and_e10d_like_values_are_accepted(monkeypatch):
    module = _module()
    forward = _curvature(0.001248100871279196, -0.2773557491731547)
    reverse = _curvature(-0.0012481008712791938, 0.2773557491731542)
    result = _run_four_pairs(module, monkeypatch, forward, reverse)
    assert result["scientific_acceptance_status"] == "PASS"
    assert result["reverse_diamond_count"] == 4


@pytest.mark.parametrize("residual", [0.5e-12, 2.0e-12])
def test_direct_abs_tol_boundary_is_preserved_and_diagnosed(monkeypatch, residual):
    module = _module()
    forward = _curvature(0.1, 0.2, area=-0.5)
    reverse_phase = -0.1 + residual
    reverse = _curvature(reverse_phase, -reverse_phase / -0.5, area=-0.5)
    if residual < 1e-12:
        result = _run_four_pairs(module, monkeypatch, forward, reverse)
        assert result["scientific_acceptance_status"] == "PASS"
    else:
        with pytest.raises(module.ReverseOrientationDiagnosticError) as caught:
            _run_four_pairs(module, monkeypatch, forward, reverse)
        error = caught.value
        assert error.diamond == "primary_qx"
        assert error.diagnostics["reverse_diag_primary_qx_absolute_reverse_phase_residual"] == pytest.approx(residual, rel=1e-6)
        result = module._future_result("FAIL", failed_stage="bundle-or-reduction", diagnostic=error)
        assert result["failure_code"] == "P72_REVERSE_ORIENTATION_SIGN_MISMATCH"
        assert result["reverse_diag_failed_diamond"] == "primary_qx"
        assert result["reverse_diag_primary_qx_forward_phase"] == 0.1
        assert result["reverse_diag_primary_qx_reverse_omega_qs"] == pytest.approx(-0.2, abs=1e-11)
        assert result["native_invocation_count"] == 1
        assert result["provider_execution_count"] == 0
        assert result["solver_execution_count"] == 0
        assert result["dataset_record_count"] == 0
        assert result["mpb_execution"] is False
        assert result["field_payload_retained"] is False


def test_principal_branch_diagnostic_does_not_replace_direct_sign_rule(monkeypatch):
    module = _module()
    phase = math.pi - 1e-6
    forward = _curvature(phase, -phase, area=1.0)
    reverse = _curvature(phase, phase, area=1.0)
    with pytest.raises(module.ReverseOrientationDiagnosticError) as caught:
        _run_four_pairs(module, monkeypatch, forward, reverse)
    result = module._future_result("FAIL", failed_stage="bundle-or-reduction", diagnostic=caught.value)
    assert result["reverse_diag_failed_diamond"] == "primary_qx"
    assert result["reverse_diag_primary_qx_direct_phase_sum"] > 6.0
    assert abs(result["reverse_diag_primary_qx_wrapped_phase_sum"]) < 1e-4
    assert result["reverse_diag_primary_qx_phase_antipode_distance"] < 1e-4
    assert result["reverse_diag_primary_qx_absolute_reverse_phase_residual"] > 6.0


def test_all_required_pair_diagnostics_are_bounded_scalars():
    module = _module()
    diagnostics = module._reverse_orientation_diagnostics(
        "refined_qy", _curvature(0.2, 0.3), _curvature(-0.2 + 2e-12, -0.3 + 3e-12)
    )
    required = (
        "forward_phase", "reverse_phase", "forward_omega_qs", "reverse_omega_qs", "signed_area_qs",
        "minimum_link_singular_value_forward", "minimum_link_singular_value_reverse",
        "maximum_link_principal_angle_forward", "maximum_link_principal_angle_reverse",
        "direct_phase_sum", "direct_omega_sum", "wrapped_phase_sum", "phase_antipode_distance",
        "absolute_reverse_phase_residual", "absolute_reverse_omega_residual",
    )
    for suffix in required:
        value = diagnostics[f"reverse_diag_refined_qy_{suffix}"]
        assert isinstance(value, float) and math.isfinite(value)


def test_static_runtime_guards_remain_solver_free():
    source = TARGET.read_text(encoding="utf-8")
    for forbidden in (
        "import meep", "from meep", "LocalAffineStateProvider",
        "MPBLiveSpectralProvider", "resolve_dataset_record", "archived runtime",
        ".solve(",
    ):
        assert forbidden not in source
