from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "audit/berry_c3_consistency/m64r4r1_recover_isolated_localize_patch_ab.py"
SPEC = importlib.util.spec_from_file_location("m64r4r1", SOURCE)
assert SPEC and SPEC.loader
m64r4r1 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m64r4r1)


def test_prior_schema_is_explicit_and_different_from_current_schema():
    assert m64r4r1.M64R3_SCHEMA == "mephc-berry-c3-consistency-m64r3-patched-frequency-ab-dataset-v1"
    assert m64r4r1.M64R3_SCHEMA != m64r4r1.DATASET_SCHEMA


def test_semantic_probe_index_is_order_independent():
    rows = [{"probe": "unpatched:generic:k0"}, {"probe": "unpatched:frozen:v2:C3"}, {"probe": "unpatched:frozen:v2:IDENTITY"}, {"probe": "unpatched:frozen:v2:C3_SQUARED"}]
    assert m64r4r1._index_prior(rows) == m64r4r1._index_prior(list(reversed(rows)))


def test_loaded_library_ledger_requires_isolated_path_and_expected_hash():
    import tempfile
    with tempfile.TemporaryDirectory() as root:
        path = Path(root) / "libmpb.so.0"
        path.write_bytes(b"exact")
        digest = m64r4r1._hash(path)
        maps = f"0 0 0 0 0 {path}\n"
        result = m64r4r1.loaded_library_ledger(maps, root, digest)
        assert result["under_isolated_prefix"] is True and result["loaded_sha256"] == digest


def test_recovery_forbids_positional_member_and_guessed_symbol_logic():
    text = SOURCE.read_text(encoding="utf-8")
    assert "prior[0]" not in text
    assert "maxwell_matrix" not in text
    assert "counter.consume_solver()" in text
