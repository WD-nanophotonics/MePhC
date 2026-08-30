from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "audit" / "local_affine" / "local_dimensionless_trajectory_benchmark.py"
HELPER = ROOT / "tools" / "mephc-flow" / "wsl_native_exec.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _representative_full_result(module):
    primary = {"omega_qx_qy": 1.25}
    refined = {"omega_qx_qy": 1.2}
    return {
        "primary": primary, "refined": refined,
        "reconstruction": {"grad_q_frequency": {"primary": [1e-7, -0.09], "refined": [1.1e-7, -0.089]}},
        "transverse_displacement": {"primary": 0.01, "refined": 0.011},
        "longitudinal_displacement": {"primary": 0.2, "refined": 0.19},
        "maximum_excursion": {
            "primary": {"qx_abs": 0.001, "qy_abs": 0.617, "s_abs": 0.0001},
            "refined": {"qx_abs": 0.0005, "qy_abs": 0.617, "s_abs": 0.0001},
        },
        "analytic_numeric_residual": [1e-15, -2e-15],
    }


def test_compact_projection_preserves_decisive_fields_and_omits_large_structures():
    module = _load(TARGET, "p109_projection")
    result = module.compact_success_projection(_representative_full_result(module))
    required = {
        "primary_omega_qx_qy", "refined_omega_qx_qy", "primary_grad_q_freq_x", "refined_grad_q_freq_y",
        "omega_qx_s", "omega_qy_s", "partial_s_freq", "primary_transverse_displacement",
        "refined_transverse_displacement", "primary_refined_abs_delta_transverse",
        "primary_longitudinal_displacement", "refined_longitudinal_displacement",
        "maximum_abs_qx_excursion", "maximum_abs_qy_excursion", "maximum_abs_s",
        "analytic_numeric_max_residual", "final_tau_stop", "final_deformation_gradient_x",
        "final_deformation_gradient_y", "normalization_status", "local_validity_status",
        "trajectory_kernel_certification_status", "benchmark_classification",
    }
    assert required <= result.keys()
    assert not any(isinstance(value, (list, dict)) for key, value in result.items() if key not in {"mpb_execution", "field_payload_retained"})
    assert result["benchmark_classification"] == "CANONICAL_DIMENSIONLESS_VALIDATION_ONLY_NOT_A_PHYSICAL_DEVICE_PREDICTION"
    encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode()
    assert len(encoded) < 65536


def test_actual_load_result_and_finalize_paths_accept_compact_success_and_failure(tmp_path):
    module = _load(TARGET, "p109_runtime_projection")
    helper = _load(HELPER, "p109_wsl_native_exec")
    success = module.compact_success_projection(_representative_full_result(module))
    failure = module.failure_result(ValueError("representative failure"))
    stdout = tmp_path / "stdout.log"
    stderr = tmp_path / "stderr.log"
    stdout.write_bytes(b"")
    stderr.write_bytes(b"")
    for index, value in enumerate((success, failure)):
        result_path = tmp_path / f"result-{index}.json"
        result_path.write_bytes(module.canonical(value))
        loaded, artifact, warnings = helper.load_result(result_path, module.RESULT_SCHEMA)
        assert loaded["schema"] == module.RESULT_SCHEMA
        assert artifact["size_bytes"] < helper.MAX_INLINE_RESULT_BYTES
        assert warnings == []
        finalized = helper.finalize_child_result(
            {"expected_output": {"result_schema": module.RESULT_SCHEMA}}, stdout, stderr, 0,
            result_path=result_path,
        )
        assert finalized["state"] == "succeeded"
        assert finalized["result_summary"]["schema"] == module.RESULT_SCHEMA


def test_actual_validator_diagnosis_is_byte_based_and_externalizes_old_large_artifact(tmp_path):
    helper = _load(HELPER, "p109_wsl_native_exec_diagnosis")
    path = tmp_path / "old-result.json"
    path.write_text(json.dumps({"schema": "old", "large": "x" * 69770}), encoding="utf-8")
    summary, artifact, warnings = helper.load_result(path, "old")
    assert artifact["size_bytes"] > helper.MAX_INLINE_RESULT_BYTES
    assert artifact["size_bytes"] < helper.MAX_RESULT_ARTIFACT_BYTES
    assert summary["result_externalized"] is True
    assert warnings == ["result_summary_externalized"]
    assert helper.MAX_INLINE_RESULT_BYTES == 65536
    assert helper.MAX_RESULT_ARTIFACT_BYTES == 64 * 1024 * 1024
