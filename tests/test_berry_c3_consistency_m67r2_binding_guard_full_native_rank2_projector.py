from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "audit/berry_c3_consistency/m67r2_binding_guard_full_native_rank2_projector.py"
SPEC = importlib.util.spec_from_file_location("m67r2", SOURCE)
assert SPEC and SPEC.loader
m67r2 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m67r2)


def test_manifest_is_built_from_two_valid_halves_and_rejects_old_65_char_value():
    value = m67r2._binding_guard()
    assert len(m67r2.M66_MANIFEST_HALF_1) == 32
    assert len(m67r2.M66_MANIFEST_HALF_2) == 32
    assert value == "96463ece684c248c04097630bd3f133ac41f537a05150884c0e5026db9a88427"
    assert value != "96463ece684c248c04097630bd3f133ac41f537a051508844c0e5026db9a88427"


def test_q_raw_roundtrip_and_true_projector_is_thin():
    rng = np.random.default_rng(672)
    q = rng.normal(size=(m67r2.P * 2, 2)) + 1j * rng.normal(size=(m67r2.P * 2, 2))
    assert np.array_equal(m67r2.raw_to_q(m67r2.q_to_raw(q)), q)
    text = SOURCE.read_text(encoding="utf-8")
    assert "value.T.reshape(2, P, 2)" in text and "value.reshape(2, P * 2).T" in text
    assert "ambient_projector_allocated" in text
    assert "131072,131072" not in text and "argmin" not in text and "np.roll" not in text


def test_zero_execution_and_historical_median_are_explicit():
    text = SOURCE.read_text(encoding="utf-8")
    assert '"native_invocation_count": 0' in text and '"solver_execution_count": 0' in text
    assert "_median_historical_ledger" in text and "_mean_scalar_ledger" in text
    assert "alternate_target_pair_diagnostic" in text and "machine_term" in text
