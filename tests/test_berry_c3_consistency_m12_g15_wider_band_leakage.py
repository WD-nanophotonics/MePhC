"""Focused M12 tests: fixed targets, six-band layout, and subspace localization."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / "audit" / "berry_c3_consistency" / "m12_g15_wider_band_subspace_leakage_localization.py"
SPEC = importlib.util.spec_from_file_location("berry_c3_m12", ENTRYPOINT)
assert SPEC and SPEC.loader
M12 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M12)


class _Counter:
    provider_count = 0
    solver_count = 0

    def consume_provider(self):
        self.provider_count += 1

    def consume_solver(self):
        self.solver_count += 1


def _target(member, geometry="G15", deterministic=False, frame="LAB_FIXED"):
    return {"request_key_sha256": f"key-{member}", "geometry_id": geometry, "deterministic": deterministic, "frame_convention": frame, "repeat_index": 1, "c3_member_identity": ("IDENTITY", "C3", "C3_SQUARED")[member], "member_index": member, "coordinate": [0.2 + member * 0.01, 0.1], "solver_configuration": {"resolution": 128, "tolerance": 1e-7, "mesh_size": 3, "deterministic": deterministic, "stencil": "lab_fixed"}}


def _six_band_frame(dimension=96, seed=2):
    rng = np.random.default_rng(seed)
    matrix = rng.normal(size=(dimension, 6)) + 1j * rng.normal(size=(dimension, 6))
    matrix, _ = np.linalg.qr(matrix)
    return matrix[:, :6]


def test_target_selection_is_semantic_and_excludes_g16_and_controls():
    records = [_target(i) for i in range(3)] + [_target(0, geometry="G16"), _target(0, deterministic=True), _target(0, frame="C3_COVARIANT")]
    selected = M12.select_g15_targets(records)
    assert [item["c3_member_identity"] for item in selected] == ["IDENTITY", "C3", "C3_SQUARED"]
    assert all(item["geometry_id"] == "G15" and item["deterministic"] is False and item["frame_convention"] == "LAB_FIXED" for item in selected)


def test_six_band_encoding_preserves_exact_order_and_energy_shape():
    frame = _six_band_frame(M12.ENERGY_VECTOR_LENGTH)
    decoded = M12.decode_bands(M12.encode_bands(frame))
    assert decoded.shape == (M12.ENERGY_VECTOR_LENGTH, 6)
    assert np.array_equal(decoded, frame)


def test_fixed_operator_is_not_overlap_selected_and_preserves_c3_cube():
    action = np.asarray([[-1, -1], [1, 0]], dtype=int)
    mapping = np.empty((4, 4, 2), dtype=int)
    inverse = action @ action
    for i in range(4):
        for j in range(4):
            mapping[i, j] = np.rint(inverse @ np.asarray([i / 4, j / 4]) * 4).astype(int) % 4
    source = _six_band_frame(2 * 4 * 4 * 3, 4)[:, :2]
    once = M12.apply_energy_frame(source, (4, 4), mapping)
    twice = M12.apply_energy_frame(once, (4, 4), mapping)
    thrice = M12.apply_energy_frame(twice, (4, 4), mapping)
    assert once.shape == source.shape
    assert np.allclose(thrice, source, rtol=0.0, atol=1e-12)
    assert "lstsq" not in ENTRYPOINT.read_text(encoding="utf-8")
    assert "maximize overlap" not in ENTRYPOINT.read_text(encoding="utf-8")


def test_localization_finds_synthetic_two_band_and_rank3_families():
    target = np.eye(12, dtype=np.complex128)
    pair23 = target[:, 1:3]
    pair34 = target[:, 2:4]
    rank3 = target[:, 1:4]
    assert M12.localize_transformed_source(pair23, target)["minimal_target_band_set"] == [2, 3]
    assert M12.localize_transformed_source(pair34, target)["minimal_target_band_set"] == [3, 4]
    assert M12.localize_transformed_source(rank3, target)["minimal_target_subspace_rank_within_bands1_6"] == 3


def test_each_live_state_consumes_exactly_one_provider_and_solver():
    counter = _Counter()
    calls = []

    def solve(_provider, coordinate):
        calls.append(tuple(coordinate))
        return SimpleNamespace(frequencies=np.arange(1.0, 7.0), normalized_vectors=tuple(_six_band_frame(M12.ENERGY_VECTOR_LENGTH, 10 + len(calls))[:, i] for i in range(6)), provenance={"representation": "mpb_energy_eh_v1", "solver_settings": {"num_bands": 6}}, orthogonality_status="MPB_H_ENVELOPE_QUALIFIED", max_off_diagonal_gram=0.0, max_normalization_error=0.0)

    records, failure = M12.acquire_states([_target(i) for i in range(3)], lambda _target: object(), solve, counter)
    assert failure is None
    assert len(records) == len(calls) == counter.provider_count == counter.solver_count == 3
    assert all(len(record["frequencies_bands_1_to_6"]) == 6 for record in records)


def test_m12_is_scoped_and_does_not_add_forbidden_science():
    source = ENTRYPOINT.read_text(encoding="utf-8")
    assert "import meep" in source
    assert "NUM_BANDS = 6" in source
    assert "G16" not in source.split("def main", 1)[0]
    assert "Chern" not in source
    assert "Berry curvature" not in source
