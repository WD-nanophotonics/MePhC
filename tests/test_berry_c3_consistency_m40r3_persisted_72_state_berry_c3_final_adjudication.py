from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "audit/berry_c3_consistency/m40r3_persisted_72_state_berry_c3_final_adjudication.py"
SPEC = importlib.util.spec_from_file_location("m40r3", SOURCE)
assert SPEC and SPEC.loader
m40r3 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m40r3)


def test_main_entrypoint_is_solver_free_and_uses_explicit_m39r1_schema():
    source = SOURCE.read_text(encoding="utf-8")
    assert "import meep" not in source and "from meep" not in source
    assert "M39.DATASET_SCHEMA" not in source
    assert "M39R1_SCHEMA" in source
    assert "M39R1_SCHEMA, 14" in source
    assert m40r3.RESULT_SCHEMA.endswith("berry-c3-final-adjudication-v1")


def test_branch_safe_lifting_handles_the_negative_positive_pi_boundary():
    summary = m40r3.branch_safe_phases([3.13, -3.13, 3.12])
    assert summary["branch_stability"] == "STABLE_CIRCULAR_CLUSTER"
    assert summary["maximum_pairwise_wrapped_distance"] < 0.04
    assert len(summary["lifted_phases"]) == 3


def test_exact_parent_schedule_is_3_members_2_stencils_3_repeats_4_vertices():
    identities = {(member, stencil, repeat, vertex) for member in m40r3.MEMBERS for stencil in m40r3.STENCILS for repeat in m40r3.REPEATS for vertex in range(4)}
    assert len(identities) == 72
    assert m40r3.PARENT_NAMESPACE_SHA256 == "d96ae5283a04766430ad15c8f1a63a825e34c573c57c7e502bd08b289c2752a8"


def test_required_full_path_symbols_and_zero_counts_are_present():
    source = SOURCE.read_text(encoding="utf-8")
    for text in ("recover_parent", "_read_dataset", "_centers", "analyze(records", "rank1_c3_status_by_stencil", "rank2_c3_status_by_stencil", "parent_manifest_recovery_status", '"native_invocation_count": 0'):
        assert text in source


def test_circular_reference_is_not_a_linear_branch_cut_statistic():
    values = m40r3.branch_safe_phases([3.14, -3.14, 3.139])
    assert np.isfinite(values["median"])
    assert values["maximum_pairwise_wrapped_distance"] < 0.01


def test_rank2_canonical_edge_is_acyclic_and_json_serializable():
    pairs = [
        {"target_pair": [1, 2], "minimum_singular_value": 0.8, "overlap_matrix": np.eye(2)},
        {"target_pair": [2, 3], "minimum_singular_value": 0.9, "overlap_matrix": np.eye(2)},
        {"target_pair": [3, 4], "minimum_singular_value": 0.7, "overlap_matrix": np.eye(2)},
    ]
    edge = m40r3.m40r2._rank2_edge(pairs, 2)
    assert all(item is not edge for item in edge["competing_target_pairs"])
    assert edge["best_target_pair"] == [2, 3]
    json.dumps(m40r3._safe(edge), allow_nan=False)
