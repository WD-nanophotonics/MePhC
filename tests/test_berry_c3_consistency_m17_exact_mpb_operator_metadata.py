"""M17 metadata-only safety and schema tests; no MPB runtime required."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / "audit" / "berry_c3_consistency" / "m17_exact_mpb_operator_metadata_and_covariance_closure.py"
SPEC = importlib.util.spec_from_file_location("berry_c3_m17", ENTRYPOINT)
assert SPEC and SPEC.loader
M17 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M17)


class FakeSolver:
    def __init__(self, *, epsilon=True):
        self.epsilon = epsilon
        self.calls = []

    def init_params(self):
        self.calls.append("init_params")

    def get_epsilon(self):
        self.calls.append("get_epsilon")
        if not self.epsilon:
            raise RuntimeError("get_epsilon requires solve")
        return np.full(16, 7.0, dtype=np.float64)

    def get_epsilon_inverse(self):
        self.calls.append("get_epsilon_inverse")
        return np.full(16, 1.0 / 7.0, dtype=np.float64)

    def run(self, *args, **kwargs):
        raise AssertionError("forbidden solve path called")

    def run_parity(self, *args, **kwargs):
        raise AssertionError("forbidden solve path called")


def member(index=0):
    return {"member_index": index, "c3_member_identity": ("IDENTITY", "C3", "C3_SQUARED")[index], "request_key_sha256": f"{index:064x}", "coordinate": [0.2, 0.1]}


def test_metadata_capture_calls_only_read_only_apis():
    solver = FakeSolver()
    calls = []
    record = M17.capture_mode_solver_metadata(solver, member=member(), reciprocal_k_point=(0.1, 0.2, 0.0), api_calls=calls, spatial_shape=(4, 4))
    assert record["metadata_status"] == "CAPTURED"
    assert record["exact_mpb_epsilon_grid_shape"] == [4, 4]
    assert record["epsilon_material_representation_type"] == "SCALAR_EPSILON_GRID"
    assert record["forbidden_solver_call_count"] == 0
    assert solver.calls == ["init_params", "get_epsilon", "get_epsilon_inverse"]
    assert all("run" not in call.lower() for call in solver.calls)


def test_get_epsilon_requires_solve_fails_closed_without_solver_call():
    solver = FakeSolver(epsilon=False)
    calls = []
    record = M17.capture_mode_solver_metadata(solver, member=member(), reciprocal_k_point=(0.1, 0.2, 0.0), api_calls=calls, spatial_shape=(4, 4))
    assert record["metadata_status"] == "EXACT_MPB_METADATA_REQUIRES_EIGENSOLVE"
    assert record["record_id"].endswith(":m17")
    assert record["forbidden_solver_call_count"] == 0
    assert solver.calls == ["init_params", "get_epsilon"]


def test_triplet_capture_is_exactly_three_records_and_never_solves():
    solvers = []

    def factory(item):
        solver = FakeSolver()
        solvers.append(solver)
        return solver, (0.0, 0.0, 0.0)

    records, api_calls, forbidden = M17.capture_triplet_metadata([member(0), member(1), member(2)], runtime_factory=factory, spatial_shape=(4, 4))
    assert len(records) == 3
    assert [item["member_index"] for item in records] == [0, 1, 2]
    assert forbidden == 0
    assert all(item["metadata_status"] == "CAPTURED" for item in records)
    assert len(solvers) == 3
    assert all(solver.calls == ["init_params", "get_epsilon", "get_epsilon_inverse"] for solver in solvers)


def test_result_schema_does_not_claim_operator_adjudication_when_metadata_incomplete(monkeypatch):
    records = [dict(member(i), metadata_status="EXACT_MPB_METADATA_REQUIRES_EIGENSOLVE", metadata_error="get_epsilon requires solve", record_id=f"r{i}") for i in range(3)]
    monkeypatch.setattr(M17, "calibrate_exact_metadata", lambda *_: {"status": "NOT_CALIBRATED_METADATA_INCOMPLETE", "exact_mpb_stored_eigenstate_maxwell_residual_max": None, "exact_mpb_stored_eigenstate_curlE_residual_max": None, "exact_mpb_stored_eigenstate_curlH_residual_max": None, "comparison_vs_m16": "not computable"})
    result = M17.result_for(records, ["ModeSolver.init_params", "ModeSolver.get_epsilon"], 0, {"dataset_id": "d", "manifest_sha256": "m"}, [], [])
    assert result["exact_mpb_operator_metadata_status"] == "EXACT_MPB_METADATA_REQUIRES_EIGENSOLVE"
    assert result["solver_execution_count"] == 0
    assert result["discrete_operator_covariance_diagnosis"] == "OPERATOR_RECONSTRUCTION_STILL_INCOMPLETE"
    assert result["minimal_next_live_state_count"] == 0


def test_actual_child_emits_structured_result_without_bundle(tmp_path):
    output = tmp_path / "result.json"
    env = os.environ.copy()
    env.update({"MEPHC_INPUT_BUNDLE": str(tmp_path / "missing.json"), "MEPHC_RESULT_PATH": str(output), "MEPHC_EXECUTION_COUNTERS_PATH": str(tmp_path / "counters.json")})
    completed = subprocess.run([sys.executable, str(ENTRYPOINT)], env=env, capture_output=True, text=True, check=False)
    assert completed.returncode == 0
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["schema"] == M17.RESULT_SCHEMA
    assert result["status"] == "FAIL_CLOSED"
    assert result["native_invocation_count"] == 1
    assert result["provider_execution_count"] == result["solver_execution_count"] == result["dataset_record_count"] == 0
