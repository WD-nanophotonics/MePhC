"""Focused tests for the final M13 six-band extension and discriminator."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / "audit" / "berry_c3_consistency" / "m13_g15_adjacent_band_window_discrimination.py"
SPEC = importlib.util.spec_from_file_location("berry_c3_m13", ENTRYPOINT)
assert SPEC and SPEC.loader
M13 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M13)


def _target(member):
    return {"request_key_sha256": f"m12-key-{member}", "geometry_id": "G15", "deterministic": False, "frame_convention": "LAB_FIXED", "repeat_index": 1, "c3_member_identity": ("IDENTITY", "C3", "C3_SQUARED")[member], "member_index": member, "coordinate": [0.2 + member * 0.01, 0.1], "solver_configuration": {"resolution": 128, "tolerance": 1e-7, "mesh_size": 3, "deterministic": False, "stencil": "lab_fixed"}}


def _frame(dimension=96, seed=5):
    rng = np.random.default_rng(seed)
    matrix = rng.normal(size=(dimension, 12)) + 1j * rng.normal(size=(dimension, 12))
    matrix, _ = np.linalg.qr(matrix)
    return matrix[:, :12]


class _Counter:
    provider_count = solver_count = 0

    def consume_provider(self): self.provider_count += 1
    def consume_solver(self): self.solver_count += 1


def test_same_triplet_selection_excludes_g16_and_keeps_m12_identity():
    selected = M13.select_same_triplet([_target(i) for i in range(3)] + [{**_target(0), "geometry_id": "G16"}])
    assert [item["c3_member_identity"] for item in selected] == ["IDENTITY", "C3", "C3_SQUARED"]
    assert all(item["geometry_id"] == "G15" for item in selected)


def test_only_bands7_to12_are_serialized_and_combination_is_ordered():
    frame = _frame()
    encoded = M13.encode_window(frame[:, 6:])
    record = {"normalized_vectors_bands_7_to_12": encoded, "frequencies_bands_7_to_12": list(np.arange(7.0, 13.0))}
    old = {"normalized_vectors_bands_1_to_6": M13._load_m12().encode_bands(frame[:, :6]), "frequencies_bands_1_to_6": list(np.arange(1.0, 7.0))}
    combined, frequencies = M13.combine_bands(old, record)
    assert combined.shape == (96, 12)
    assert np.array_equal(combined, frame)
    assert np.array_equal(frequencies, np.arange(1.0, 13.0))
    assert "normalized_vectors_bands_1_to_6" not in M13._record.__code__.co_consts


def test_synthetic_localization_distinguishes_same_pair_other_pair_and_broad_rank():
    target = np.eye(12, dtype=np.complex128)
    source23 = target[:, 1:3]
    source34 = target[:, 2:4]
    source_broad = np.column_stack([target[:, 1], target[:, 3]])
    same = M13.localize(source23, target, np.arange(1.0, 13.0), [2.0, 3.0])
    other = M13.localize(source34, target, np.arange(1.0, 13.0), [3.0, 4.0])
    broad = M13.localize(source_broad, target, np.arange(1.0, 13.0), [2.0, 3.0])
    assert same["minimal"]["band_set"] == [2, 3]
    assert other["minimal"]["band_set"] == [3, 4]
    assert broad["minimal"]["rank"] == 2
    assert same["pairs"][1]["spectral_consistency_status"] == "SPECTRALLY_CONSISTENT_WITH_SOURCE_ISOLATED_WINDOW"


def test_three_state_acquisition_counts_only_new_window_and_preserves_identity():
    counter = _Counter(); calls = []
    original_length = M13.ENERGY_VECTOR_LENGTH
    M13.ENERGY_VECTOR_LENGTH = 96

    def solve(_provider, coordinate):
        calls.append(tuple(coordinate)); frame = _frame(96, 20 + len(calls))
        return SimpleNamespace(frequencies=np.arange(1.0, 13.0), normalized_vectors=tuple(frame[:, i] for i in range(12)), provenance={"representation": "mpb_energy_eh_v1", "solver_settings": {"num_bands": 12}}, orthogonality_status="MPB_H_ENVELOPE_QUALIFIED", max_off_diagonal_gram=0.0, max_normalization_error=0.0)

    try:
        records, failure = M13.acquire_states([_target(i) for i in range(3)], lambda _target: object(), solve, counter)
        assert failure is None and len(records) == len(calls) == counter.provider_count == counter.solver_count == 3
        assert all(len(record["normalized_vectors_bands_7_to_12"]) == 6 for record in records)
        assert all(record["frequencies_bands_1_to_6_reproduction"] == list(np.arange(1.0, 7.0)) for record in records)
    finally:
        M13.ENERGY_VECTOR_LENGTH = original_length


def test_m13_is_final_window_and_never_requests_higher_bands():
    source = ENTRYPOINT.read_text(encoding="utf-8")
    assert M13.NUM_BANDS == 12
    assert "range(13, 14)" not in source
    assert "Chern" not in source and "Berry curvature" not in source
