from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("m32", ROOT / "audit/berry_c3_consistency/m32_installed_mpb_reciprocal_h_export_forensics.py")
assert SPEC and SPEC.loader
m32 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m32)


def test_artifact_inventory_is_bounded_and_typed():
    inventory = m32.installed_mpb_artifact_inventory()
    assert isinstance(inventory, list)
    assert all("evidence_type" in item or "artifact_type" in item or "kind" in item for item in inventory)


def test_no_symbol_name_is_treated_as_safe_raw_access():
    candidates = m32.reciprocal_candidate_inventory([])
    assert all(item["accessibility_status"] in {"NOT_FOUND", "NOT_PROVEN_ACCESSIBLE"} for item in candidates)


def test_missing_wrapper_path_is_explicit():
    path = m32.get_hfield_wrapper_callpath([], [])
    assert path[0]["status"] == "SOURCE_PATH_NOT_FOUND"


def test_forensics_source_does_not_invoke_mp_or_abi_guessing():
    source = (ROOT / "audit/berry_c3_consistency/m32_installed_mpb_reciprocal_h_export_forensics.py").read_text(encoding="utf-8")
    assert "import meep" not in source
    assert "ctypes" not in source
    assert "cffi" not in source
    assert "run_parity" not in source
