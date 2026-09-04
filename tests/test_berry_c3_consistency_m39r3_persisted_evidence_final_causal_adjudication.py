from __future__ import annotations

import json
import importlib.util
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("m39r3", ROOT / "audit/berry_c3_consistency/m39r3_persisted_evidence_final_causal_adjudication.py")
assert SPEC and SPEC.loader
m39r3 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m39r3)


def test_exact_result_schema_and_canonical_pair_label():
    assert m39r3.RESULT_SCHEMA == "mephc-berry-c3-consistency-m39r3-g15-persisted-evidence-final-causal-adjudication-v1"
    assert m39r3.PARENT_NAMESPACE_SHA256 == "716f5d62a06ba52368f7d3aa151b476da0b1f87c2bbcd4065038557d2965cbee"


def test_historical_raw2_physical_band_three_uses_local_index_one():
    raw = np.zeros((2, m39r3.P, 2), dtype=np.complex128)
    raw[0, 0, 0] = 1.0
    raw[1, 1, 0] = 1.0
    edge = {"edge_source_member": "IDENTITY", "edge_target_member": "C3", "G_edge_integer": [0, 0]}
    result = m39r3._fixed_rank1_links(m39r3.m38, raw, raw, 2, edge, [0.0, 0.0], [0.0, 0.0])
    assert result["physical_band"] == 3
    assert result["local_source_index"] == 1
    assert result["source_band"] == 3


def _synthetic_fixture():
    raw4 = np.zeros((4, m39r3.P, 2), dtype=np.complex128)
    for band in range(4):
        raw4[band, band, 0] = 1.0 + 0.1j * band
    raw2 = raw4[1:3].copy()
    encoded4 = m39r3.m39._encode_raw(raw4)
    encoded2 = m39r3.m39._encode_raw(raw2)
    gaps = {"lower_gap": 1.0, "internal_split": 1.0, "upper_gap": 1.0, "band2_isolation_gap": 1.0, "band3_isolation_gap": 1.0, "minimum_external_rank2_gap": 1.0}
    records = []
    for order, item in enumerate(m39r3.m39.build_recovery_schedule()):
        records.append({"schema": m39r3.m39r2.M39R1_DATASET_SCHEMA, "record_id": f"synthetic-{order}", "request_key_sha256": f"key-{order}", "c3_member_identity": item["c3_member_identity"], "member_index": item["member_index"], "geometry_id": "G15", "deterministic": item["deterministic"], "repeat_index": item["repeat_index"], "coordinate": [0.0, 0.0], "frequencies_bands_1_to_4": [1.0, 2.0, 3.0, 4.0], "adjacent_gaps": gaps, "solver_convergence_evidence": {"iteration_evidence_status": "UNAVAILABLE_NO_PUBLIC_RUNTIME_FIELD"}, "raw_eigenvector": encoded4, "source_commit": "synthetic"})
    controls = {member: {"schema": m39r3.m39r2.M18_SCHEMA, "record_id": f"m18-{member}", "c3_member_identity": member, "geometry_id": "G15", "coordinate": [0.0, 0.0], "frequencies_bands_1_to_6": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]} for member in m39r3.MEMBERS}
    raw_controls = {member: {"schema": m39r3.m39r2.M33_SCHEMA, "record_id": f"m33-{member}", "c3_member_identity": member, "geometry_id": "G15", "raw_eigenvector": encoded2} for member in m39r3.MEMBERS}
    return records, controls, raw_controls


def test_full_synthetic_analysis_reaches_result_serialization():
    records, m18, m33 = _synthetic_fixture()
    original_apply = m39r3.m38.apply_raw_operator
    original_edges = m39r3.m38._edges
    m39r3.m38.apply_raw_operator = lambda raw, *_args: (np.asarray(raw).copy(), {"bijection": True})
    m39r3.m38._edges = lambda states: [{"edge_source_member": "IDENTITY", "edge_target_member": "C3", "G_edge_integer": [0, 0]}, {"edge_source_member": "C3", "edge_target_member": "C3_SQUARED", "G_edge_integer": [0, 0]}, {"edge_source_member": "C3_SQUARED", "edge_target_member": "IDENTITY", "G_edge_integer": [0, 0]}]
    try:
        result = m39r3._result_document("synthetic-m39r3", "synthetic", records, {"dataset_id": "d" * 64, "manifest_sha256": "e" * 64, "namespace_sha256": m39r3.PARENT_NAMESPACE_SHA256}, m18, m33)
    finally:
        m39r3.m38.apply_raw_operator = original_apply
        m39r3.m38._edges = original_edges
    encoded = json.dumps(m39r3._safe(result), allow_nan=False, sort_keys=True)
    decoded = json.loads(encoded)
    assert decoded["schema"] == m39r3.RESULT_SCHEMA
    assert decoded["native_invocation_count"] == decoded["provider_execution_count"] == decoded["solver_execution_count"] == decoded["dataset_record_count"] == 0
    assert decoded["c3_rank2_best_pair_stability"]["canonical_pair_one_based"] == [2, 3]
    assert decoded["primary_causal_class"] in {"RANDOM_INITIALIZATION", "BAND_ASSOCIATION_OR_NEAR_DEGENERACY", "REMAINING_NUMERICAL_OR_PHYSICAL_C3_BREAKING", "MULTIPLE_IDENTIFIED_CAUSES", "UNRESOLVED_UNDER_BOUNDED_EXPERIMENT"}
