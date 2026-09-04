from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("m39", ROOT / "audit/berry_c3_consistency/m39_g15_deterministic_repeat_band_association_worst_orbit_pilot.py")
assert SPEC and SPEC.loader
m39 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m39)


def test_schedule_is_exactly_fifteen_interleaved_unique_states():
    schedule = m39.build_schedule()
    assert len(schedule) == 15
    assert sum(item["deterministic"] for item in schedule) == 9
    assert sum(not item["deterministic"] for item in schedule) == 6
    assert {(item["c3_member_identity"], item["deterministic"], item["repeat_index"]) for item in schedule}.__len__() == 15


def test_native_mode_component_band_layout_normalizes_to_band_mode_component():
    raw = np.zeros((m39.P, 2, m39.BANDS), dtype=np.complex128)
    canonical, layout = m39.normalize_raw(raw)
    assert canonical.shape == (4, m39.P, 2)
    assert layout["layout"] == "NATIVE_MODE_TRANSVERSE_COMPONENT_BAND"


def test_low_rank_projector_distance_does_not_allocate_ambient_projectors():
    rng = np.random.default_rng(39)
    source = rng.normal(size=(4, 12, 2)) + 1j * rng.normal(size=(4, 12, 2))
    target = source.copy()
    result = m39.low_rank_metrics(source, target)
    assert np.allclose(result["singular_values"], [1.0, 1.0])
    assert result["projector_distance"] == 0.0


def test_request_schedule_contains_four_bands_and_fresh_repeat_identity():
    member = {"coordinate": [0.1, 0.2, 0.0]}
    specs = [m39.request_spec(member, item, "d6a29ebb78c791f37931cefab644dacd770ad894") for item in m39.build_schedule()]
    assert all(item["num_bands"] == 4 and item["resolution"] == 128 and item["mesh_size"] == 3 for item in specs)
    assert len({item["request_key_sha256"] for item in specs}) == 15


def test_source_forbids_symmetry_expansion_and_dense_projector_path():
    source = (ROOT / "audit/berry_c3_consistency/m39_g15_deterministic_repeat_band_association_worst_orbit_pilot.py").read_text(encoding="utf-8")
    assert "symmetry" not in source.lower()
    assert "32768, 32768" not in source
