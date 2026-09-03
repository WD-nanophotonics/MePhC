from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np

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
