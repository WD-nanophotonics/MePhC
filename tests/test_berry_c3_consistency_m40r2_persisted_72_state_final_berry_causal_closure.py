from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "audit/berry_c3_consistency/m40r2_persisted_72_state_final_berry_causal_closure.py"
SPEC = importlib.util.spec_from_file_location("m40r2", SOURCE)
assert SPEC and SPEC.loader
m40r2 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m40r2)


def test_contract_is_append_only_solver_free_and_exactly_zero_budget():
    source = SOURCE.read_text(encoding="utf-8")
    assert "import meep" not in source
    assert "from meep" not in source
    assert '"native_invocation_count": 0' in source
    assert m40r2.PARENT_NAMESPACE_SHA256 == "d96ae5283a04766430ad15c8f1a63a825e34c573c57c7e502bd08b289c2752a8"
    assert m40r2.RESULT_SCHEMA.endswith("final-berry-causal-closure-v1")


def test_exact_schedule_and_parent_identity_are_exposed():
    expected = {(member, repeat, stencil, vertex) for member in m40r2.MEMBERS for repeat in m40r2.REPEATS for stencil in m40r2.STENCILS for vertex in m40r2.VERTICES}
    assert len(expected) == 72
    assert m40r2.PARENT_RECORD_SCHEMA.endswith("vertex-dataset-v1")
    assert m40r2.PARENT_WORK_ORDER_ID.endswith("20260904-103")


def test_wrapped_phase_uncertainty_and_median_are_conservative():
    assert np.isclose(m40r2._circular_distance([3.13, -3.13]), 0.023185, atol=1e-3)
    summary = m40r2._median_uncertainty([1.0, 1.2, 0.8])
    assert summary["median"] == 1.0
    assert np.isclose(summary["uncertainty"], 0.2)


def test_rank2_competing_pairs_are_not_hard_coded_to_canonical_pair():
    source = SOURCE.read_text(encoding="utf-8")
    assert "itertools.combinations(range(4), 2)" in source
    assert '"target_pair": [i + 1 for i in selected]' in source
    assert '"captured_weight"' in source


def test_required_result_fields_and_stencil_specific_c3_paths_are_present():
    source = SOURCE.read_text(encoding="utf-8")
    for field in ("parent_manifest_recovery_status", "rank1_c3_pairwise_comparison_by_stencil", "rank1_c3_status_by_stencil", "rank2_c3_pairwise_comparison_by_stencil", "rank2_c3_status_by_stencil", "m40r2_causal_synthesis", "next_science_decision"):
        assert field in source
    assert "LAB_FIXED" in source and "C3_COVARIANT" in source
