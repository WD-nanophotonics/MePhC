from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("m39r2", ROOT / "audit/berry_c3_consistency/m39r2_persisted_14_state_causal_adjudication.py")
assert SPEC and SPEC.loader
m39r2 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m39r2)


def test_result_schema_and_parent_namespace_are_exact():
    assert m39r2.M39R2_RESULT_SCHEMA == "mephc-berry-c3-consistency-m39r2-g15-deterministic-repeat-band-association-causal-adjudication-v1"
    assert m39r2._namespace()["work_order_id"] == m39r2.M39R1_WORK_ORDER_ID
    assert m39r2.PARENT_NAMESPACE_SHA256 == "716f5d62a06ba52368f7d3aa151b476da0b1f87c2bbcd4065038557d2965cbee"


def test_m18_control_requires_six_band_field_and_returns_first_four():
    assert m39r2._bind_m18_frequency({"frequencies_bands_1_to_6": [1, 2, 3, 4, 5, 6]}) == [1.0, 2.0, 3.0, 4.0]


def test_nested_edge_grouping_uses_edge_identity_and_repeat_dispersion():
    loops = [
        {"repeat_index": 1, "band": 2, "edges": [{"edge_source_member": "IDENTITY", "edge_target_member": "C3", "link_magnitude": 0.90}]},
        {"repeat_index": 2, "band": 2, "edges": [{"edge_source_member": "IDENTITY", "edge_target_member": "C3", "link_magnitude": 0.95}]},
        {"repeat_index": 1, "band": 3, "edges": [{"edge_source_member": "IDENTITY", "edge_target_member": "C3", "link_magnitude": 0.80}]},
        {"repeat_index": 2, "band": 3, "edges": [{"edge_source_member": "IDENTITY", "edge_target_member": "C3", "link_magnitude": 0.75}]},
    ]
    noise, grouped = m39r2._grouped_link_noise(loops)
    assert grouped[("IDENTITY", "C3", 2)] == [0.90, 0.95]
    assert grouped[("IDENTITY", "C3", 3)] == [0.80, 0.75]
    assert np.isclose(noise, 0.05)


def test_wrapped_phase_uncertainty_is_circular_not_linear():
    assert m39r2._circular_range([3.13, -3.13]) < 0.03


def test_source_contains_no_native_or_dense_projector_execution_path():
    source = (ROOT / "audit/berry_c3_consistency/m39r2_persisted_14_state_causal_adjudication.py").read_text(encoding="utf-8")
    assert "import meep" not in source
    assert "import mpb" not in source
    assert "32768, 32768" not in source
