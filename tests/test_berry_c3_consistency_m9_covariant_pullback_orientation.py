"""M9 direction-sensitive Maxwell covariance tests."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / "audit" / "berry_c3_consistency" / "m9_covariant_pullback_orientation_and_rank2_closure.py"
SPEC = importlib.util.spec_from_file_location("berry_c3_m9", ENTRYPOINT)
assert SPEC and SPEC.loader
M9 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M9)


def test_maxwell_covariance_selects_active_R_and_source_R_inverse():
    convention = M9.maxwell_covariance_convention()
    assert "q_target=R" in convention["public_q_rotation_convention"]
    assert "R^-1" in convention["spatial_pullback_formula"]
    assert "blockdiag(D(R),D(R))" in convention["stored_energy_vector_rotation_formula"]


def test_direction_sensitive_fixture_distinguishes_forward_and_inverse():
    basis = np.asarray([[1.0, 0.5], [0.0, np.sqrt(3.0) / 2.0]])
    action = M9.derive_fractional_action(basis)
    authoritative = M9.build_index_map((32, 32), action)
    inverse = M9.build_index_map((32, 32), action @ action)
    result = M9.direction_sensitive_synthetic_check((32, 32), authoritative, inverse)
    assert result["direction_sensitive_fixture_distinguishes_R_and_R_inverse"]
    assert result["authoritative_norm_preserved"]
    assert result["inverse_negative_control_norm_preserved"]
    assert result["authoritative_scalar_c3_residual"] <= 1e-12


def test_full_energy_operator_rotates_two_band_frame_without_fitting():
    basis = np.asarray([[1.0, 0.5], [0.0, np.sqrt(3.0) / 2.0]])
    action = M9.derive_fractional_action(basis)
    mapping = M9.build_index_map((4, 4), action)
    rng = np.random.default_rng(19)
    frame = rng.normal(size=(2 * 4 * 4 * 3, 2)) + 1j * rng.normal(size=(2 * 4 * 4 * 3, 2))
    transformed = M9.apply_energy_frame(frame, (4, 4), mapping)
    assert transformed.shape == frame.shape
    assert np.isclose(np.linalg.norm(transformed), np.linalg.norm(frame))


def test_m9_has_no_expensive_execution_or_fit_path():
    source = ENTRYPOINT.read_text(encoding="utf-8")
    assert "BudgetCounter" not in source
    assert ".solve(" not in source
    assert "import meep" not in source
    assert "lstsq" not in source
    assert "U(2)" not in source


def test_actual_child_entry_emits_structured_result_on_bounded_input_failure(tmp_path):
    result_path = tmp_path / "m9-result.json"
    completed = subprocess.run([sys.executable, str(ENTRYPOINT)], env={"MEPHC_RESULT_PATH": str(result_path)}, capture_output=True, text=True, check=False)
    assert completed.returncode == 0
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["schema"] == M9.RESULT_SCHEMA
    assert result["status"] == "FAIL_CLOSED"
    assert "failure_code" in result
