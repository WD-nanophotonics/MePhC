"""M19 zero-execution runtime-grid and projector audit tests."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest


ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / "audit" / "berry_c3_consistency" / "m19_runtime_epsilon_grid_and_spectral_projector_audit.py"
SPEC = importlib.util.spec_from_file_location("berry_c3_m19", ENTRYPOINT)
assert SPEC and SPEC.loader
M19 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M19)


def test_spectral_window_is_derived_from_isolation_not_ordinal_labels():
    values = np.asarray([0.2, 0.35, 0.3507, 0.54, 0.58, 0.69, 0.71, 0.74, 0.78, 0.84, 0.91, 0.92])
    result = M19.spectral_window(values)
    assert result["spectral_window_band_set"] == [2, 3]
    assert result["spectral_window_rank"] == 2
    assert result["spectral_window_bounds"][0] < values[1] < values[2] < result["spectral_window_bounds"][1]


def test_projector_audit_checks_independent_span_and_u2_invariance():
    rng = np.random.default_rng(19)
    frame = rng.normal(size=(32, 4)) + 1j * rng.normal(size=(32, 4))
    result = M19.projector_audit(frame, (1, 2))
    assert result["projector_vector_matrix_shape"] == [32, 2]
    assert result["projector_band_axis"] == "columns"
    assert result["projector_independent_construction_difference_max"] < 1e-12
    assert result["projector_U2_invariance_residual_max"] < 1e-12


def test_projector_audit_rejects_rank_deficient_span():
    frame = np.ones((12, 3), dtype=np.complex128)
    with pytest.raises(M19.M19Error):
        M19.projector_audit(frame, (0, 1))


def test_missing_input_bundle_is_structured_zero_side_effect_failure(tmp_path):
    output = tmp_path / "result.json"
    env = os.environ.copy()
    env.update({"MEPHC_INPUT_BUNDLE": str(tmp_path / "missing.json"), "MEPHC_RESULT_PATH": str(output), "MEPHC_EXECUTION_COUNTERS_PATH": str(tmp_path / "counters.json")})
    completed = subprocess.run([sys.executable, str(ENTRYPOINT)], env=env, capture_output=True, text=True, check=False)
    assert completed.returncode == 0
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["schema"] == M19.RESULT_SCHEMA
    assert result["native_invocation_count"] == result["provider_execution_count"] == result["solver_execution_count"] == result["dataset_record_count"] == 0
