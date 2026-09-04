from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "audit/berry_c3_consistency/m41_g15_covariant_numerical_convergence_pilot.py"
SPEC = importlib.util.spec_from_file_location("m41", SOURCE)
assert SPEC and SPEC.loader
m41 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m41)


def test_pre_native_graph_has_exact_108_mandatory_and_36_conditional_states():
    centers = {member: [float(index), float(index) + 0.25] for index, member in enumerate(m41.MEMBERS)}
    graphs = {config["configuration_id"]: m41.request_graph(config, centers, "a" * 40) for config in m41.CONFIGS}
    conditional = m41.request_graph(m41.CONDITIONAL, centers, "a" * 40)
    assert sum(len(graph) for graph in graphs.values()) == 108
    assert len(conditional) == 36
    assert len({item["request_key_sha256"] for graph in graphs.values() for item in graph}) == 108


def test_only_declared_covariant_configurations_are_in_graph():
    centers = {member: [float(index), float(index) + 0.25] for index, member in enumerate(m41.MEMBERS)}
    graph = m41.request_graph(m41.CONFIGS[0], centers, "a" * 40)
    assert {item["stencil"] for item in graph} == {"C3_COVARIANT"}
    assert {item["resolution"] for item in graph} == {128}
    assert {item["tolerance"] for item in graph} == {1e-9}
    assert {item["mesh_size"] for item in graph} == {3}


def test_conditional_trigger_is_uncertainty_based_and_not_unconditionally_true():
    def analysis(value):
        return {"member_summary": {member: {"rank2_trace_phase_density": {"median": value, "uncertainty": 0.1}, "rank2_best_pairs": [(2, 3)]} for member in m41.MEMBERS}, "rank1_c3_status": "PASS", "rank2_c3_status": "PASS"}
    trigger, reasons = m41.conditional_r96_trigger({"R64_T1E9_M3": analysis(1.0), "R128_T1E9_M3": analysis(1.05)})
    assert trigger is False
    assert reasons == []
    trigger, reasons = m41.conditional_r96_trigger({"R64_T1E9_M3": analysis(1.0), "R128_T1E9_M3": analysis(2.0)})
    assert trigger is True and reasons


def test_native_is_deferred_to_main_and_no_old_dataset_reacquisition_path_exists():
    source = SOURCE.read_text(encoding="utf-8")
    assert "m40r1" not in source.lower()
    assert "Never reacquire" not in source
    assert "store.put" in source and "store.finalize" in source


def test_result_schema_and_zero_or_one_native_contract_metadata_are_explicit():
    source = SOURCE.read_text(encoding="utf-8")
    assert m41.RESULT_SCHEMA == "mephc-berry-c3-consistency-m41-g15-covariant-numerical-convergence-pilot-v1"
    assert '"native_invocation_count": 1' in source
    assert "R128_T1E9_M3" in source and "R128_T1E9_M1" in source and "R64_T1E9_M3" in source and "R96_T1E9_M3" in source
