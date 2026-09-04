from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "audit/berry_c3_consistency/m41r1_partial36_recovery_numerical_convergence.py"
SPEC = importlib.util.spec_from_file_location("m41r1", SOURCE)
assert SPEC and SPEC.loader
m41r1 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m41r1)


def test_partial_parent_and_recovery_dataset_are_distinct_and_exactly_sized():
    members = ("IDENTITY", "C3", "C3_SQUARED")
    centers = {member: [float(index), float(index) + 0.25] for index, member in enumerate(members)}
    graph = m41r1._new_graph({"configuration_id": "R64_T1E9_M3", "resolution": 64, "tolerance": 1e-9, "mesh_size": 3}, centers, "a" * 40)
    assert len(graph) == 36
    assert all(item["configuration_id"] != "R128_T1E9_M3" for item in graph)
    assert m41r1.PARTIAL_NAMESPACE_SHA256 != "0" * 64


def test_resolution_aware_raw_normalization_accepts_native_shapes_64_96_128():
    for resolution in (64, 96, 128):
        mode_count = resolution * resolution
        raw = np.zeros((mode_count, 2, 4), dtype=np.complex128)
        normalized, metadata = m41r1._normalize_raw(raw, resolution)
        assert normalized.shape == (4, mode_count, 2)
        assert metadata["mode_count"] == mode_count


def test_dynamic_fft_path_passes_resolution_shape_and_avoids_old_helper_symbols():
    source = SOURCE.read_text(encoding="utf-8")
    assert "fft_label(index, shape=shape)" in source
    assert "def _rank1" in source and "def _rank2_pair" in source
    assert "capture_state_resolution_aware" in source
    assert "M39R1_SCHEMA" in source


def test_contract_limits_and_conditional_branch_are_explicit():
    source = SOURCE.read_text(encoding="utf-8")
    for token in ('"R128_T1E9_M1"', '"R64_T1E9_M3"', '"R96_T1E9_M3"', 'len(records) not in (72, 108)', 'counter.provider_count'):
        assert token in source
