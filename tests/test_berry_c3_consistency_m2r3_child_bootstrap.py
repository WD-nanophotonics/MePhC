"""Subprocess bootstrap regression for the M2R2 child exit failure."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / "audit" / "berry_c3_consistency" / "m2_live_c3_acquisition_and_reduction.py"


def test_previous_child_failure_is_concrete_exit_policy_not_generic_code():
    import importlib.util

    spec = importlib.util.spec_from_file_location("m2r3_entrypoint", ENTRYPOINT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.PREVIOUS_CHILD_RETURN_CODE == 2
    assert module.PREVIOUS_CHILD_EXCEPTION_TYPE == "None"
    assert module.PREVIOUS_CHILD_FAILURE_STAGE == "entrypoint_exit_policy"
    assert module.PREVIOUS_CHILD_FAILURE_CODE == "FAIL_CLOSED_RESULT_EXIT_2"


def test_valid_child_bootstrap_reaches_strict_fake_boundary(tmp_path):
    result_path = tmp_path / "child-result.json"
    environment = os.environ.copy()
    environment["MEPHC_M2_TEST_FAKE_BOUNDARY"] = "1"
    environment["MEPHC_RESULT_PATH"] = str(result_path)
    completed = subprocess.run(
        [sys.executable, str(ENTRYPOINT)],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr + completed.stdout
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["status"] == "PASS"
    assert result["provider_request_count"] == 288
    assert result["solver_execution_count"] == 288
    assert result["dataset_record_count"] == 72
    assert result["first_live_request_key"]
    assert result["production_provider_symbol"] == "mephc.mpb_energy_spectral_provider.MPBLiveEnergySpectralProvider"


def test_all_fake_child_records_reach_constituent_boundary():
    import importlib.util

    spec = importlib.util.spec_from_file_location("m2r3_entrypoint_full", ENTRYPOINT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fake = module._BootstrapFakeBoundary()
    plan = module.derive_plan(module.verify_m1_bundle())
    execution = module.execute_injected_plan(plan, fake)
    assert execution["failures"] == []
    assert len(execution["results"]) == 72
    assert fake.provider_count == fake.solver_count == 288
    assert fake.dataset_count == 72
