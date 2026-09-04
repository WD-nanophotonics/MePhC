from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("m40", ROOT / "audit/berry_c3_consistency/m40_deterministic_raw_h_worst_orbit_berry_plaquette_closure.py")
assert SPEC and SPEC.loader
m40 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m40)


def test_exact_18_plaquette_schedule_and_72_vertices():
    schedule = m40.build_plaquette_schedule()
    assert len(schedule) == 18
    assert len(schedule) * 4 == 72
    assert all(item["deterministic"] and item["geometry_id"] == "G15" for item in schedule)
    assert {(item["c3_member_identity"], item["repeat_index"], item["stencil"]) for item in schedule}.__len__() == 18


def test_actual_counterclockwise_area_is_computed_from_vertices_for_both_stencils():
    for member_index in range(3):
        for stencil in ("LAB_FIXED", "C3_COVARIANT"):
            vertices, area = m40.plaquette_vertices(m40.CENTER, stencil, member_index)
            assert len(vertices) == 4
            assert area > 0.0
            shoelace = sum(vertices[index][0] * vertices[(index + 1) % 4][1] - vertices[(index + 1) % 4][0] * vertices[index][1] for index in range(4)) / 2.0
            assert np.isclose(area, shoelace)


def test_request_is_deterministic_four_band_raw_h_contract():
    item = m40.build_plaquette_schedule()[0]
    vertices, _ = m40.plaquette_vertices(m40.CENTER, item["stencil"], item["member_index"])
    spec = m40.request_spec(m40.CENTER, item, 0, vertices[0], "source")
    assert spec["deterministic"] is True
    assert spec["num_bands"] == 4
    assert spec["stencil"] in {"LAB_FIXED", "C3_COVARIANT"}
    assert len(spec["request_key_sha256"]) == 64


def test_neighbor_transfer_has_no_c3_rotation_or_dense_projector_path():
    source = (ROOT / "audit/berry_c3_consistency/m40_deterministic_raw_h_worst_orbit_berry_plaquette_closure.py").read_text(encoding="utf-8")
    assert "apply_raw_operator" not in source
    assert "32768, 32768" not in source
