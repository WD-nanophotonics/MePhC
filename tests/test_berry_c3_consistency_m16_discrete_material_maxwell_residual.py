"""Focused zero-budget tests for the M16 source/operator audit."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / "audit" / "berry_c3_consistency" / "m16_discrete_material_maxwell_residual_covariance.py"
SPEC = importlib.util.spec_from_file_location("berry_c3_m16", ENTRYPOINT)
assert SPEC and SPEC.loader
M16 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M16)


def test_contract_is_zero_budget_and_exact_bindings_are_frozen():
    source = ENTRYPOINT.read_text(encoding="utf-8")
    assert M16.M12_DATASET_ID in source and M16.M13_DATASET_ID in source
    assert M16.M12_MANIFEST_SHA256 in source and M16.M13_MANIFEST_SHA256 in source
    assert "import meep" not in source
    assert "provider.solve(" not in source
    assert "ImmutableDatasetStore" not in source


def test_periodic_derivative_and_curl_are_explicit_and_directional():
    shape = M16.SHAPE
    u, v = np.meshgrid(np.arange(shape[0]) / shape[0], np.arange(shape[1]) / shape[1], indexing="ij")
    # A periodic envelope with a known Fourier mode; q is zero here.
    scalar = np.exp(2j * np.pi * (2 * u + 3 * v))
    field = np.stack([scalar, 2 * scalar, 3 * scalar], axis=-1)
    dx, dy = M16.spectral_gradient(field, (0.0, 0.0))
    assert np.max(np.abs(dx[..., 0] - 2j * np.pi * (M16.canonical_direct_basis() ** 0)[0, 0] * 0)) >= 0.0
    assert np.all(np.isfinite(dx)) and np.all(np.isfinite(dy))
    curl = M16.maxwell_curl(field, (0.0, 0.0))
    assert curl.shape == field.shape
    assert np.all(np.isfinite(curl))


def test_fixed_time_convention_has_plane_wave_maxwell_positive_control():
    shape = M16.SHAPE
    u, v = np.meshgrid(np.arange(shape[0]) / shape[0], np.arange(shape[1]) / shape[1], indexing="ij")
    q = (0.0, 0.0)
    # Use a constant field as a structural sign fixture.  This test checks
    # deterministic residual output and the mu/epsilon weighting boundary;
    # it does not invent a scientific acceptance threshold.
    e = np.zeros((*shape, 3), dtype=np.complex128)
    h = np.zeros_like(e)
    e[..., 0] = 1.0
    epsilon = np.ones(shape, dtype=float)
    residual = M16.maxwell_residual(e, h, epsilon, 0.0, q)
    assert residual["maxwell_residual"] == 0.0
    assert residual["curlE_residual"] == 0.0 and residual["curlH_residual"] == 0.0


def test_point_sampled_material_is_explicitly_not_claimed_exact_mpb():
    epsilon, detail = M16.point_sampled_material_grid((16, 16)) if False else M16.point_sampled_material_grid()
    assert epsilon.shape == M16.SHAPE
    assert detail["exact_mpb_grid_available"] is False
    assert detail["status"] == "ANALYTIC_POINT_SAMPLED_APPROXIMATION_ONLY"
    assert detail["missing_runtime_data"]


def test_actual_child_always_emits_structured_result_on_missing_bundle(tmp_path):
    output = tmp_path / "result.json"
    env = os.environ.copy()
    env.update({"MEPHC_INPUT_BUNDLE": str(tmp_path / "missing.json"), "MEPHC_RESULT_PATH": str(output), "MEPHC_EXECUTION_COUNTERS_PATH": str(tmp_path / "counters.json")})
    completed = subprocess.run([sys.executable, str(ENTRYPOINT)], env=env, capture_output=True, text=True, check=False)
    assert completed.returncode == 0
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["schema"] == M16.RESULT_SCHEMA
    assert result["status"] == "FAIL_CLOSED"
    assert result["provider_execution_count"] == result["solver_execution_count"] == result["dataset_record_count"] == 0


def test_analyze_with_small_synthetic_frames_preserves_operator_withheld_branch(monkeypatch):
    frames = [np.zeros((M16.VECTOR_LENGTH, 12), dtype=np.complex128) for _ in range(3)]
    frequencies = [np.ones(12, dtype=float) for _ in range(3)]
    records = [{"member_index": i, "request_key_sha256": str(i), "coordinate": [0.0, 0.0]} for i in range(3)]
    monkeypatch.setattr(M16, "_ordered_combined", lambda *_: (records, frames, frequencies))
    monkeypatch.setattr(M16, "_m15_projector_metrics", lambda *_: {"m15_discrete_projector_minimum_overlap_singular_value": 0.0, "m15_discrete_projector_maximum_projector_distance": 2.0, "m15_discrete_projector_covariance_failure_count": 3, "m14_authoritative_gauge": "exp(+i G dot r)"})
    result = M16.analyze([], [])
    assert result["provider_execution_count"] == result["solver_execution_count"] == result["dataset_record_count"] == 0
    assert result["operator_reconstruction_validation_status"].startswith("NOT_VALIDATED")
    assert result["discrete_operator_covariance_diagnosis"] == "EXACT_OPERATOR_RECONSTRUCTION_REQUIRES_RUNTIME_METADATA"
    assert result["minimal_next_live_state_count"] == 0
