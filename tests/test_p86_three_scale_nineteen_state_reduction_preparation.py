from __future__ import annotations

import hashlib
import importlib.util
import json
import py_compile
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "audit" / "local_affine" / "p86_three_scale_19_state_binding_plan.json"
TARGET = ROOT / "audit" / "local_affine" / "frozen_19_state_three_scale_solver_free_reduction.py"


def _module():
    spec = importlib.util.spec_from_file_location("p86_reducer", TARGET)
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


def _run_synthetic_reduction(module, monkeypatch):
    def consistent(omega, area):
        return _curvature(-omega * area, omega, area)

    forward = {
        "primary_qx": consistent(-0.191020640274069, 4e-05),
        "primary_qy": consistent(-3.528260452898002e-05, 4e-05),
        "refined_qx": consistent(-0.19120388321536833, 1e-05),
        "refined_qy": consistent(3.5836998125982074e-05, 1e-05),
        "third_qx": consistent(-0.19125, 2.5e-06),
        "third_qy": consistent(0.0001, 2.5e-06),
    }
    reverse = {name: _curvature(-value.phase, -value.omega_qs, value.signed_area_qs) for name, value in forward.items()}
    monkeypatch.setattr(module, "_diamond", lambda _states, prefix, axis, _h_q, _h_s: f"{prefix}_{axis}")
    monkeypatch.setattr(module, "_third_diamond", lambda _states, axis: f"THIRD_{axis}")
    monkeypatch.setattr(module, "rank1_mixed_curvature", lambda diamond: forward[{"PRIMARY_0": "primary_qx", "PRIMARY_1": "primary_qy", "REFINED_0": "refined_qx", "REFINED_1": "refined_qy", "THIRD_0": "third_qx", "THIRD_1": "third_qy"}[diamond]])
    monkeypatch.setattr(module, "reverse_mixed_curvature", lambda diamond: reverse[{"PRIMARY_0": "primary_qx", "PRIMARY_1": "primary_qy", "REFINED_0": "refined_qx", "REFINED_1": "refined_qy", "THIRD_0": "third_qx", "THIRD_1": "third_qy"}[diamond]])
    derivatives = iter((0.009019148867474985, 0.009027508885504909, 0.00903))
    monkeypatch.setattr(module, "fixed_q_frequency_derivative", lambda *_args, **_kwargs: next(derivatives))
    roles = {"CENTER", "PRIMARY_PLUS_QX", "PRIMARY_MINUS_QX", "PRIMARY_PLUS_QY", "PRIMARY_MINUS_QY", "PRIMARY_PLUS_S", "PRIMARY_MINUS_S", "REFINED_PLUS_QX", "REFINED_MINUS_QX", "REFINED_PLUS_QY", "REFINED_MINUS_QY", "REFINED_PLUS_S", "REFINED_MINUS_S", "THIRD_PLUS_QX", "THIRD_MINUS_QX", "THIRD_PLUS_QY", "THIRD_MINUS_QY", "THIRD_PLUS_S", "THIRD_MINUS_S"}
    return module.reduce_states({role: object() for role in roles})


def test_binding_plan_has_nineteen_records_and_two_dataset_bindings():
    module = _module()
    plan = module.load_binding_plan()
    assert plan["record_count"] == plan["unique_record_key_count"] == len(plan["bindings"]) == 19
    assert len(plan["datasets"]) == 2
    assert [item["state_id"] for item in plan["bindings"]] == [f"STATE_{index:02d}" for index in range(1, 20)]
    assert {item["dataset_id"] for item in plan["bindings"]} == {
        "ac421aedcaf748bb0367b92083298e4f4c1d8095f2b5c66b5f2c371b082c8652",
        "4276d93556b41344fa7a6d7b5a71ddcb31e25e3e4de990dcccbac7e7b61cbe07",
    }


def test_p85_keys_and_graph_specific_request_hashes_are_exact():
    module = _module()
    plan = module.load_binding_plan()
    third = plan["bindings"][13:]
    expected = {
        "STATE_14": "43e0834e18f86ef84f82ae9e7133a201399d9a422bf014f844f3931a58528fdf",
        "STATE_15": "55093f7e97ba29fc15be6065556ebc83c03f20ca285fc7f876ffdbe3543416be",
        "STATE_16": "c12607106ed66337ddbcc8de45d9b564db564cd94db4779a2a4e97f3f9aef9c9",
        "STATE_17": "d2e4bda6d3927381c5c7736d25fec7b4bb786648c1bfd58da54039ac5f5f5ac4",
        "STATE_18": "64b6811958291e5b8d6c71bdb03f171ddbdd1f9f9961d52e625ef1b718d87af7",
        "STATE_19": "d3d5d9f3025f41731cc02f1b3b48d0748a323d5308312459a20431eec539b60c",
    }
    assert {item["state_id"]: item["record_key_sha256"] for item in third} == expected
    assert {item["request_graph_sha256"].lower() for item in plan["bindings"][:13]} == {hashlib.sha256((ROOT / "audit/local_affine/p2_frozen_13_state_request_graph.json").read_bytes()).hexdigest()}
    assert {item["request_graph_sha256"].lower() for item in third} == {hashlib.sha256((ROOT / "audit/local_affine/p84_third_scale_6_state_request_graph.json").read_bytes()).hexdigest()}


def test_future_reducer_compiles_and_exposes_six_exact_diamonds(monkeypatch):
    module = _module()
    py_compile.compile(str(TARGET), doraise=True)
    result = _run_synthetic_reduction(module, monkeypatch)
    assert result["state_count"] == 19
    assert result["scale_count"] == 3
    assert result["reverse_diamond_count"] == 6
    assert result["three_scale_reduction_status"] == "ESTIMATES_AVAILABLE"
    for name in ("third_qx", "third_qy"):
        assert f"forward_wilson_phase_{name}" in result
        assert f"reverse_wilson_phase_{name}" in result
        assert f"minimum_link_singular_value_reverse_{name}" in result
        assert f"maximum_link_principal_angle_reverse_{name}" in result


def test_three_scale_difference_ratio_and_sign_reporting_is_descriptive(monkeypatch):
    module = _module()
    result = _run_synthetic_reduction(module, monkeypatch)
    for label in ("qx_s", "qy_s", "domega_ds"):
        assert result[f"{label}_sign_sequence"].count(",") == 2
        assert len(result[f"{label}_absolute_magnitude_sequence"]) == 3
        assert result[f"{label}_primary_to_refined_absolute_difference"] >= 0.0
        assert result[f"{label}_refined_to_third_absolute_difference"] >= 0.0
        ratio = result[f"{label}_empirical_refinement_difference_ratio"]
        assert ratio is None or ratio >= 0.0


def test_p82_tolerance_scaling_is_preserved_at_all_three_scales():
    module = _module()
    assert module._reverse_omega_tolerance(4e-05) == 2.5e-08
    assert module._reverse_omega_tolerance(1e-05) == 1e-07
    assert module._reverse_omega_tolerance(2.5e-06) == pytest.approx(4e-07)


def test_static_reducer_guards_remain_solver_free():
    source = TARGET.read_text(encoding="utf-8")
    for forbidden in (
        "import meep", "from meep", "LocalAffineStateProvider",
        "MPBLiveSpectralProvider", "resolve_dataset_record", "archived runtime",
        ".solve(",
    ):
        assert forbidden not in source
