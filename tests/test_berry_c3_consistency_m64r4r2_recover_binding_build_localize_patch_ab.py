from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "audit/berry_c3_consistency/m64r4r2_recover_binding_build_localize_patch_ab.py"
SPEC = importlib.util.spec_from_file_location("m64r4r2", SOURCE)
assert SPEC and SPEC.loader
m64r4r2 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m64r4r2)


def test_build_binding_helper_is_defined_and_verifies_committed_inputs():
    binding = m64r4r2.verify_build5_binding()
    assert callable(m64r4r2.verify_build5_binding)
    assert binding["package_build"] == "mpi_mpich_hef3cbd5_5"
    assert len(binding["driver_sha256"]) == 64 and binding["installed_backend_touched"] is False


def test_helper_closure_has_callable_preflight_helpers():
    assert callable(m64r4r2.index_probe_rows)
    assert callable(m64r4r2._failure_set)
    assert callable(m64r4r2.compatibility_guard)
    command = m64r4r2.prepare_build_command(Path("source.tgz"), Path("build"), Path("prefix"))
    assert command[0] == "bash" and command[1].endswith("build_exact_build5.sh")


def test_semantic_probe_mapping_and_derived_guard_are_not_positional_or_fixed():
    rows = [{"probe": "unpatched:generic:k0"}, {"probe": "unpatched:frozen:v2:C3"}, {"probe": "unpatched:frozen:v2:IDENTITY"}, {"probe": "unpatched:frozen:v2:C3_SQUARED"}]
    assert list(m64r4r2.index_probe_rows(rows)) == [row["probe"] for row in rows]
    assert m64r4r2.compatibility_guard(0.25, None, 0.0) == 0.25
    assert m64r4r2.compatibility_guard(0.25, 0.1, 0.01) == 0.36


def test_runtime_identity_is_path_and_hash_bound_and_old_guesses_are_absent():
    text = SOURCE.read_text(encoding="utf-8")
    assert "maxwell_matrix" not in text and "prior[0]" not in text
    assert "loaded_library_ledger" in text and "built_trace_lib_sha256" in text
