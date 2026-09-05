from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "audit/berry_c3_consistency/m55_c3_projected_epsilon_frequency_ab.py"
SPEC = importlib.util.spec_from_file_location("m55_test_module", SOURCE)
assert SPEC and SPEC.loader
m55 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m55)


def _freq(failures):
    return {"failure_set": [{"vertex": v, "band": b, "source_member": s, "target_member": t} for v, b, s, t in failures], "failure_count": len(failures)}


def test_exact_projection_preserves_mean_and_direct_c3():
    mapping = m55.m54.build_index_map()
    epsilon = np.ones((256, 256)); epsilon[3, 7] = 4.0
    projected, summary = m55.projected_epsilon(epsilon, mapping)
    assert summary["projected_c3_residual_max"] <= summary["identity_guard"]
    assert summary["global_mean_residual"] <= summary["identity_guard"]
    assert np.isclose(projected.mean(), epsilon.mean())


def test_exact_failure_set_relations_define_classification():
    stock = _freq([(0, 1, "IDENTITY", "C3"), (1, 2, "C3", "C3_SQUARED")])
    full = _freq([])
    partial = _freq([(1, 2, "C3", "C3_SQUARED")])
    introduced = _freq([(2, 3, "C3_SQUARED", "IDENTITY")])
    assert m55.classify(stock, full)[0] == "R256_C3_PROJECTED_SCALAR_EPSILON_FULL_FREQUENCY_RESTORATION"
    assert m55.classify(stock, partial)[0] == "R256_C3_PROJECTED_SCALAR_EPSILON_PARTIAL_FREQUENCY_RESTORATION"
    assert m55.classify(stock, introduced)[0] == "R256_C3_PROJECTED_SCALAR_EPSILON_INTRODUCES_NEW_FAILURES"


def test_public_material_grid_input_is_project_contained_and_no_geometry_reused():
    text = SOURCE.read_text(encoding="utf-8")
    assert "MaterialGrid" in text
    assert "geometry=[material]" in text
    assert "get_epsilon" in text
    assert "init_params" in text
    assert "provider_execution_count" in text


def test_only_fixed_solver_contract_is_present():
    text = SOURCE.read_text(encoding="utf-8")
    assert "resolution=256" in text and "mesh_size=1" in text and "tolerance=1e-9" in text
    assert "Berry" not in text.split("def main", 1)[0]
