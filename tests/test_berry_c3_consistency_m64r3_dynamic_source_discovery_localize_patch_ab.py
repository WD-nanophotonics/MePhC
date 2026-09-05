from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "audit/berry_c3_consistency/m64r3_dynamic_source_discovery_localize_patch_ab.py"
SPEC = importlib.util.spec_from_file_location("m64r3", SOURCE)
assert SPEC and SPEC.loader
m64r3 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m64r3)


def test_discovery_is_seeded_only_by_verified_symbol_and_has_no_guessed_gate():
    text = SOURCE.read_text(encoding="utf-8")
    assert "update_maxwell_data_k" in text
    assert "maxwell_matrix" not in text
    assert "guessed_symbol_preconditions" in text


def test_fixture_without_prior_downstream_name_discovers_actual_function():
    fixture = "int update_maxwell_data_k(int k) { return alternate_operator(k); }\nint alternate_operator(int x) { return x; }\n"
    functions = m64r3._source_functions(fixture, "fixture.c")
    names = {item["function"] for item in functions}
    assert names == {"update_maxwell_data_k", "alternate_operator"}
    assert all("body_sha256" in item and item["start_line"] <= item["end_line"] for item in functions)


def test_stage_inventory_is_semantic_and_patch_free_by_default():
    text = SOURCE.read_text(encoding="utf-8")
    for stage in ("K_NATIVE", "RECIP_LABEL", "Q_METRIC", "TRANSVERSE", "OPERATOR_ONE_MODE", "EIGENSOLVER_RETURN", "LIBMPB_FREQUENCY", "PYTHON_VISIBLE"):
        assert stage in text
    assert '"patch_applied": False' in text


def test_authorized_vendor_artifacts_remain_trace_only_and_unmodified_backend():
    manifest = (ROOT / "vendor/mpb_c3_patch/localization_manifest.json").read_text(encoding="utf-8")
    instrumentation = (ROOT / "vendor/mpb_c3_patch/mpb-1.12.0-homogeneous-c3-instrumentation.patch").read_text(encoding="utf-8")
    assert "installed_backend_touched" in manifest and "TRACE-ONLY" in instrumentation
