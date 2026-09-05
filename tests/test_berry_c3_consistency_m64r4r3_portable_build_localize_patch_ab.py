from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "audit/berry_c3_consistency/m64r4r3_portable_build_localize_patch_ab.py"
SPEC = importlib.util.spec_from_file_location("m64r4r3", SOURCE)
assert SPEC and SPEC.loader
m64r4r3 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m64r4r3)


def test_portable_binding_uses_committed_driver_and_no_machine_home_default():
    binding = m64r4r3.verify_build5_binding()
    driver = (ROOT / "vendor/mpb_c3_patch/build_exact_build5.sh").read_text(encoding="utf-8")
    assert binding["driver_sha256"] == m64r4r3.DRIVER_SHA
    assert "/home/icy" not in driver and "MPB_GNUCONFIG_ROOT" in driver


def test_gnuconfig_resolution_has_only_explicit_prefix_candidates(monkeypatch, tmp_path):
    root = tmp_path / "share" / "gnuconfig"
    root.mkdir(parents=True)
    (root / "config.sub").write_bytes(b"sub")
    (root / "config.guess").write_bytes(b"guess")
    monkeypatch.setenv("MPB_BUILD_PREFIX", str(tmp_path))
    monkeypatch.delenv("MPB_GNUCONFIG_ROOT", raising=False)
    monkeypatch.delenv("MPB_DEP_PREFIX", raising=False)
    result = m64r4r3.resolve_gnuconfig()
    assert result["category"] == "BUILD_PREFIX" and len(result["config_sub_sha256"]) == 64


def test_semantic_prior_schema_and_member_identity_are_explicit():
    text = SOURCE.read_text(encoding="utf-8")
    assert m64r4r3.M64R3_SCHEMA != m64r4r3.DATASET_SCHEMA
    assert "prior[0]" not in text and "maxwell_matrix" not in text
    assert "unpatched:frozen:v" in text and "C3_SQUARED" in text


def test_runtime_library_hash_is_not_confused_with_installed_reference():
    text = SOURCE.read_text(encoding="utf-8")
    assert "built_trace_lib_sha256" in text and "installed_reference_libmpb_sha256" in text
