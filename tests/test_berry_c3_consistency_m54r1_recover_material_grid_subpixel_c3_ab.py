from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "audit/berry_c3_consistency/m54r1_recover_material_grid_subpixel_c3_ab.py"
SPEC = importlib.util.spec_from_file_location("m54r1_test_module", SOURCE)
assert SPEC and SPEC.loader
m54r1 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m54r1)


def _rows():
    return {(vertex, repeat, member): {"frequencies_bands_1_to_4": [1, 2, 3, 4]} for vertex in range(4) for repeat in range(3) for member in ("IDENTITY", "C3", "C3_SQUARED")}


def _material(status="PASS"):
    return {"scalar_c3_status": status, "tensor_c3_status": status}


def test_canonical_frequency_map_uses_only_integer_mesh_keys():
    result = m54r1.canonical_frequency_map({1: _rows(), 3: _rows(), 5: _rows()})
    assert set(result) == {1, 3, 5}
    assert all(type(key) is int for key in result)


def test_mixed_mesh_keys_fail_before_native():
    try:
        m54r1.canonical_frequency_map({1: _rows(), "3": _rows(), 5: _rows()})
    except ValueError as exc:
        assert str(exc) == "M54R1_MESH_KEY_SET_INVALID"
    else:
        raise AssertionError("mixed mesh keys must fail closed")


def test_recovery_classification_keeps_integer_keys_until_final_route():
    frequency = {1: {"failure_count": 0}, 3: {"failure_count": 0}, 5: {"failure_count": 1}}
    material = {1: _material(), 3: _material(), 5: _material()}
    outcome, decision = m54r1.classify(frequency, material)
    assert outcome == "R256_MATERIAL_READBACK_C3_COVARIANT_DESPITE_FREQUENCY_FAILURE"
    assert decision == "MPB_K_DEPENDENT_DISCRETE_OPERATOR_C3_SOURCE_AUDIT"


def test_grid_and_tensor_audits_remain_zero_interpolation():
    mapping = m54r1.m54.build_index_map()
    tensor = np.broadcast_to(np.eye(3), (256, 256, 3, 3)).copy()
    result = m54r1.m54.material_covariance(np.ones((256, 256)), tensor, mapping)
    assert result["scalar_c3_status"] == "PASS"
    assert result["tensor_c3_status"] == "PASS"
    assert result["projected_material_c3_status"] == "PASS"


def test_entrypoint_is_recovery_only_and_does_not_call_solver():
    text = SOURCE.read_text(encoding="utf-8")
    assert ".run(" not in text
    assert ".run_parity(" not in text
    assert "solve_kpoint" not in text
    assert "m54.capture_material" in text
