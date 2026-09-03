"""M20 zero-execution field convention audit tests."""
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
ENTRYPOINT = ROOT / "audit" / "berry_c3_consistency" / "m20_mpb_staggering_constitutive_operator_calibration.py"
SPEC = importlib.util.spec_from_file_location("berry_c3_m20", ENTRYPOINT)
assert SPEC and SPEC.loader
M20 = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(M20)


def test_collocated_reference_curl_validation_is_explicitly_not_mpb_calibration():
    result = M20.synthetic_collocated_curl_validation()
    assert result["synthetic_periodic_field_residual_max"] == pytest.approx(0.0)
    assert "NOT_PROOF" in result["status"]


def test_failure_path_is_structured_and_zero_side_effect():
    output = Path(os.environ.get("TEMP", ".")) / "m20_missing_input_result.json"
    try:
        env = os.environ.copy(); env.update({"MEPHC_INPUT_BUNDLE": str(output.with_name("missing-m20-bundle.json")), "MEPHC_RESULT_PATH": str(output), "MEPHC_EXECUTION_COUNTERS_PATH": str(output.with_name("counters.json"))})
        completed = subprocess.run([sys.executable, str(ENTRYPOINT)], env=env, capture_output=True, text=True, check=False)
        assert completed.returncode == 0
        result = json.loads(output.read_text(encoding="utf-8"))
        assert result["schema"] == M20.RESULT_SCHEMA
        assert result["native_invocation_count"] == result["provider_execution_count"] == result["solver_execution_count"] == result["dataset_record_count"] == 0
    finally:
        output.unlink(missing_ok=True)


def test_projector_or_physics_code_is_not_imported_by_m20_entrypoint():
    text = ENTRYPOINT.read_text(encoding="utf-8")
    assert "run_parity" not in text and "ModeSolver(" not in text
