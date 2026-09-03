from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("m35", ROOT / "audit/berry_c3_consistency/m35_exact_mpb_source_raw_basis_c3_closure.py")
assert SPEC and SPEC.loader
m35 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m35)


def test_provenance_is_metadata_only():
    value = m35.distribution_provenance()
    assert "distributions" in value
    assert "conda_meta" in value
    assert isinstance(value["distributions"], list)


def test_source_match_does_not_accept_version_alone():
    assert m35._source_match({"distributions": [{"package": "meep", "version": "x", "build": "b", "direct_url": None}]}) == "SOURCE_BUILD_IDENTITY_INSUFFICIENT"


def test_source_matching_requires_commit_and_build():
    assert m35._source_match({"distributions": [{"package": "meep", "build": "b", "direct_url": {"vcs_info": {"commit_id": "abc"}}}]}) == "EXACT_COMMIT_MATCH"


def test_no_installed_package_can_be_called_as_mp_or_solver():
    source = (ROOT / "audit/berry_c3_consistency/m35_exact_mpb_source_raw_basis_c3_closure.py").read_text(encoding="utf-8")
    assert "import meep" not in source
    assert "run_parity" not in source
    assert "get_eigenvectors(" not in source


def test_m33_binding_ids_are_fixed():
    assert m35.M33_DATASET_ID.startswith("b92b")
    assert m35.M18_DATASET_ID.startswith("6aff")
