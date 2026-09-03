from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("m36", ROOT / "audit/berry_c3_consistency/m36_conda_build_provenance_recipe_source_raw_c3_closure.py")
assert SPEC and SPEC.loader
m36 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m36)


def test_provenance_has_package_and_cache_layers():
    value = m36.provenance()
    assert "conda_meta" in value
    assert "package_cache" in value
    assert "distributions" in value


def test_package_row_prefers_exact_conda_record():
    value = {"conda_meta": [{"record": {"name": "meep", "version": "x", "build": "exact"}}], "distributions": [{"package": "meep", "version": "wrong"}]}
    assert m36._package_row(value)["build"] == "exact"


def test_synthetic_operator_closes_without_physical_overlap():
    value = m36.synthetic_operator_metrics()
    assert value["synthetic_single_mode_status"] == "PASS"
    assert value["synthetic_random_field_status"] == "PASS"
    assert value["C3_cubed_residual"] < 1e-12


def test_source_is_zero_execution_and_no_unmatched_upstream():
    source = (ROOT / "audit/berry_c3_consistency/m36_conda_build_provenance_recipe_source_raw_c3_closure.py").read_text(encoding="utf-8")
    assert "import meep" not in source
    assert "run_parity" not in source
    assert "latest upstream" not in source.lower()


def test_m33_binding_is_fixed():
    assert m36.M33_DATASET_ID.startswith("b92b")
    assert m36.M33_MANIFEST_SHA256.startswith("dd03")
