from __future__ import annotations

import importlib.util
import math
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "audit" / "local_affine" / "frozen_13_state_solver_free_reduction.py"
ROLES = (
    "CENTER", "PRIMARY_PLUS_QX", "PRIMARY_MINUS_QX", "PRIMARY_PLUS_QY", "PRIMARY_MINUS_QY", "PRIMARY_PLUS_S", "PRIMARY_MINUS_S",
    "REFINED_PLUS_QX", "REFINED_MINUS_QX", "REFINED_PLUS_QY", "REFINED_MINUS_QY", "REFINED_PLUS_S", "REFINED_MINUS_S",
)


def _module():
    spec = importlib.util.spec_from_file_location("p82_reducer", TARGET)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _curvature(phase, omega, area):
    return SimpleNamespace(
        phase=phase,
        omega_qs=omega,
        signed_area_qs=area,
        minimum_link_singular_value=0.999,
        maximum_link_principal_angle=0.2,
    )


def _run_four_pairs(module, monkeypatch, forward, reverse):
    monkeypatch.setattr(module, "_diamond", lambda *args: object())
    monkeypatch.setattr(module, "rank1_mixed_curvature", lambda _diamond: forward)
    monkeypatch.setattr(module, "reverse_mixed_curvature", lambda _diamond: reverse)
    monkeypatch.setattr(module, "fixed_q_frequency_derivative", lambda *args, **kwargs: 1.0)
    return module.reduce_states({role: object() for role in ROLES})


def test_exact_p81_numbers_pass_with_area_scaled_omega_tolerance(monkeypatch):
    module = _module()
    area = 4e-05
    forward = _curvature(7.64082561096276e-06, -0.191020640274069, area)
    reverse = _curvature(-7.640825611240318e-06, 0.19102064028100793, area)
    result = _run_four_pairs(module, monkeypatch, forward, reverse)
    assert result["scientific_acceptance_status"] == "PASS"
    assert module._reverse_omega_tolerance(area) == 2.5e-08
    assert abs(forward.phase + reverse.phase) == pytest.approx(2.7755745022218364e-16)
    assert abs(forward.omega_qs + reverse.omega_qs) == pytest.approx(6.938921659482844e-12)
    assert min(abs(abs(forward.phase) - math.pi), abs(abs(reverse.phase) - math.pi)) == pytest.approx(3.141585012764182)


def test_e10d_reference_like_values_remain_accepted(monkeypatch):
    module = _module()
    area = -0.001248100871279196 / -0.2773557491731547
    forward = _curvature(0.001248100871279196, -0.2773557491731547, area)
    reverse = _curvature(-0.0012481008712791938, 0.2773557491731542, area)
    result = _run_four_pairs(module, monkeypatch, forward, reverse)
    assert result["scientific_acceptance_status"] == "PASS"


def test_phase_residual_failure_is_not_rescued_by_area_scaled_omega_rule(monkeypatch):
    module = _module()
    area = 0.5
    forward = _curvature(0.1, -0.2, area)
    reverse = _curvature(-0.1 + 2e-12, 0.2, area)
    with pytest.raises(module.ReverseOrientationDiagnosticError) as caught:
        _run_four_pairs(module, monkeypatch, forward, reverse)
    assert caught.value.diamond == "primary_qx"
    assert caught.value.diagnostics["reverse_diag_primary_qx_omega_reverse_abs_tolerance"] == 2e-12
    assert caught.value.diagnostics["reverse_diag_primary_qx_absolute_reverse_phase_residual"] > 1e-12


def test_curvature_consistency_failure_remains_fail_closed_when_phase_passes(monkeypatch):
    module = _module()
    area = 0.5
    forward = _curvature(0.1, -0.2, area)
    reverse = _curvature(-0.1, 0.200000000003, area)
    with pytest.raises(ValueError, match="P82_OMEGA_PHASE_CONSISTENCY_MISMATCH"):
        _run_four_pairs(module, monkeypatch, forward, reverse)


def test_principal_branch_direct_phase_rule_still_fails(monkeypatch):
    module = _module()
    phase = math.pi - 1e-6
    forward = _curvature(phase, -phase, 1.0)
    reverse = _curvature(phase, -phase, 1.0)
    with pytest.raises(module.ReverseOrientationDiagnosticError) as caught:
        _run_four_pairs(module, monkeypatch, forward, reverse)
    diagnostics = caught.value.diagnostics
    assert diagnostics["reverse_diag_primary_qx_direct_phase_sum"] > 6.0
    assert abs(diagnostics["reverse_diag_primary_qx_wrapped_phase_sum"]) < 1e-4
    assert diagnostics["reverse_diag_primary_qx_phase_antipode_distance"] < 1e-4


def test_primary_and_refined_area_scaling_is_exactly_derived():
    module = _module()
    assert module._reverse_omega_tolerance(4e-05) == 2.5e-08
    assert module._reverse_omega_tolerance(1e-05) == 1e-07


def test_static_runtime_guards_remain_solver_free():
    source = TARGET.read_text(encoding="utf-8")
    for forbidden in (
        "import meep", "from meep", "LocalAffineStateProvider",
        "MPBLiveSpectralProvider", "resolve_dataset_record", "archived runtime",
        ".solve(",
    ):
        assert forbidden not in source
