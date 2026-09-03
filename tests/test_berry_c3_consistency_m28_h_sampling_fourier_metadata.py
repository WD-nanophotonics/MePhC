from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "audit" / "berry_c3_consistency" / "m28_h_point_array_sampling_raw_fourier_metadata.py"
SPEC = importlib.util.spec_from_file_location("m28_test_module", PATH)
assert SPEC is not None and SPEC.loader is not None
M28 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M28)


def test_contract_is_bounded_to_existing_triplet_and_result_channel():
    source = PATH.read_text(encoding="utf-8")
    assert "MEPHC_INPUT_BUNDLE" in source and "MEPHC_RESULT_PATH" in source
    assert "run_parity" in source and "get_field_point" in source
    assert "new_metadata_record_count" in source


def test_preregistered_stencil_is_fixed_and_bounded():
    assert len(M28.STENCIL) == 8
    assert M28.STENCIL[0] == (0, 0) and M28.STENCIL[-1] == (127, 127)


def test_point_arguments_use_both_candidate_charts_without_authority_guess():
    source = PATH.read_text(encoding="utf-8")
    assert "index_over_N" in source and "index_plus_half_over_N" in source
    assert "NO_UNIQUE_CORRECTION_ESTABLISHED" in source


def test_h_array_shape_guard_is_exact():
    value = np.zeros((128, 128, 3), dtype=complex)
    assert M28._array(value).shape == (128, 128, 3)


def test_pre_solve_reuse_probe_never_calls_unsafe_mpb_field_access():
    class Unsolved:
        all_freqs = []

        def get_hfield(self, *_args, **_kwargs):
            raise AssertionError("unsafe field access was attempted")

    with pytest.raises(RuntimeError, match="MPB_FIELD_ACCESS_REQUIRES_SOLVE_KPOINT"):
        M28._attempt_reuse_capture(Unsolved(), None, {})


def test_stateful_public_field_sequence_keeps_band_point_association():
    class Vector3Type:
        def __init__(self, x, y, z):
            self.x, self.y, self.z = x, y, z

    class FakeMP:
        Vector3 = Vector3Type

    class StatefulSolver:
        all_freqs = [1, 2, 3, 4, 5, 6]

        def __init__(self):
            self.current_band = None
            self.calls = []

        def get_hfield(self, which_band, bloch_phase=True):
            self.current_band = which_band
            self.calls.append(("h", which_band, bloch_phase))
            return np.full((128, 128, 3), which_band, dtype=complex)

        def get_field_point(self, p):
            assert self.current_band in (2, 3)
            self.calls.append(("point", self.current_band, p.x, p.y))
            return np.array([self.current_band, 0, 0], dtype=complex)

        def get_bloch_field_point(self, p):
            self.calls.append(("bloch-point", self.current_band, p.x, p.y))
            return np.array([self.current_band, 0, 0], dtype=complex)

    solver = StatefulSolver()
    member = {"member_index": 0, "c3_member_identity": "IDENTITY", "coordinate": [0, 0, 0], "request_key_sha256": "k"}
    record, _frame, used = M28._capture(solver, FakeMP, member, solved=True)
    assert used == 1
    assert record["loaded_field_band_sequence"] == [2, 3]
    assert record["point_query_values"]["2:index_over_N:0,0"][0][0] == 2.0
    assert record["point_query_values"]["3:index_over_N:0,0"][0][0] == 3.0
    assert [call for call in solver.calls if call[0] == "h"][:2] == [("h", 2, False), ("h", 3, False)]


def test_canonical_triplet_binding_uses_semantic_identity():
    base = {"geometry_role": "AREA_MATCHED_G15", "deterministic": False, "frame_convention": "LAB_FIXED", "repeat_index": 1}
    records = [{**base, "c3_member_identity": name, "member_index": index} for index, name in enumerate(("C3_SQUARED", "IDENTITY", "C3"))]
    assert [item["c3_member_identity"] for item in M28.bind_canonical_triplet(records)] == ["IDENTITY", "C3", "C3_SQUARED"]


def test_actual_subprocess_emits_one_result_and_returns_zero_for_bounded_paths(tmp_path):
    bundle_path = tmp_path / "production-shaped-bundle.json"
    bundle_path.write_text(json.dumps({
        "work_order_id": "MEPHC-BERRY-C3-M28R3-SUBPROCESS-REGRESSION",
        "action": "acquire",
        "dataset_bindings_v2": {"inputs": [{"dataset_id": "m18", "record_count": 3}], "outputs": [{"expected_record_count": 3}]},
    }), encoding="utf-8")
    cases = [
        {"schema": M28.RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS"},
        {"schema": M28.RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "runtime_sampling_capture_status": "RUNTIME_FIELD_METADATA_UNAVAILABLE"},
        {"schema": M28.RESULT_SCHEMA, "status": "PASS", "unserializable": object()},
    ]
    for index, payload in enumerate(cases):
        result_path = tmp_path / f"result-{index}.json"
        env = os.environ.copy()
        env.update({"MEPHC_INPUT_BUNDLE": str(bundle_path), "MEPHC_RESULT_PATH": str(result_path), "MEPHC_SOURCE_COMMIT": "test-source"})
        module_path = repr(str(PATH))
        payload_expr = "{'schema': %r, 'status': 'PASS', 'unserializable': object()}" % M28.RESULT_SCHEMA if index == 2 else repr(payload)
        script = (
            "import importlib.util; "
            f"spec=importlib.util.spec_from_file_location('m28_subprocess', {module_path}); "
            "module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module); "
            f"module._science_result=lambda: {payload_expr}; "
            "raise SystemExit(module.main())"
        )
        completed = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True)
        assert completed.returncode == 0, completed.stderr
        lines = result_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        result = json.loads(lines[0])
        assert result["schema"] == M28.RESULT_SCHEMA
        if index == 2:
            assert result["status"] == "FAIL_CLOSED"
            assert result["failure_stage"] == "result_serialization"


@pytest.mark.parametrize("fixture, expected_status", [("runtime_error", "FAIL_CLOSED"), ("system_exit", "FAIL_CLOSED"), ("metadata_unavailable", "METADATA_UNAVAILABLE")])
def test_actual_native_child_launch_capsule_keeps_bounded_outcomes_at_exit_zero(tmp_path, fixture, expected_status):
    state_path = tmp_path / "native-state.json"
    bundle_path = tmp_path / "bundle.json"
    result_path = tmp_path / "child-result.json"
    bundle_path.write_text(json.dumps({"work_order_id": "MEPHC-BERRY-C3-M28R4-CAPSULE-REGRESSION", "action": "acquire"}), encoding="utf-8")
    state_path.write_text(json.dumps({
        "state": "dispatching", "job_id": "MEPHC-SCIENCE-CAPSULE", "native_run_id": "MEPHC-NATIVE-CAPSULE",
        "work_order_id": "MEPHC-BERRY-C3-M28R4-CAPSULE-REGRESSION", "native_invocation_budget": 1,
        "provider_request_budget": 0, "solver_execution_budget": 3,
        "expected_output": {"result_schema": M28.CHILD_RESULT_SCHEMA},
    }), encoding="utf-8")
    helper = ROOT / "tools" / "mephc-flow" / "wsl_native_exec.py"
    module_path = repr(str(PATH))
    if fixture == "runtime_error":
        body = "def body(): raise RuntimeError('capsule fixture runtime error')"
    elif fixture == "system_exit":
        body = "def body(): raise SystemExit(7)"
    else:
        body = "def body(): return {'status':'METADATA_UNAVAILABLE','runtime_sampling_capture_status':'RUNTIME_FIELD_METADATA_UNAVAILABLE'}"
    child_script = textwrap.dedent(f"""
        import importlib.util
        import json
        import os
        spec = importlib.util.spec_from_file_location('m28_capsule_child', {module_path})
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        {body}
        capsule = module._child_capsule(body)
        open(os.environ['MEPHC_RESULT_PATH'], 'w', encoding='utf-8').write(json.dumps(capsule, sort_keys=True) + '\\n')
    """)
    completed = subprocess.run([
        sys.executable, str(helper), "--state", str(state_path), "--checkout", str(ROOT), "--project", str(ROOT),
        "--input-bundle", str(bundle_path), "--result-path", str(result_path), "--", sys.executable, "-c", child_script,
    ], capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["schema"] == M28.CHILD_RESULT_SCHEMA
    assert result["status"] == expected_status
    if fixture != "metadata_unavailable":
        assert result["exception_type"] in {"RuntimeError", "SystemExit"}
