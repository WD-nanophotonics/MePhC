from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "audit/berry_c3_consistency/m55r1_public_epsilon_input_frequency_ab.py"
SPEC = importlib.util.spec_from_file_location("m55r1_test_module", SOURCE)
assert SPEC and SPEC.loader
m55r1 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m55r1)


def _freq(failures):
    return {"failure_set": [{"vertex": v, "band": b, "source_member": s, "target_member": t} for v, b, s, t in failures], "failure_count": len(failures)}


def test_exact_projection_is_positive_mean_preserving_and_c3_covariant():
    mapping = m55r1.m54.build_index_map()
    epsilon = np.ones(m55r1.SHAPE); epsilon[3, 7] = 4.0
    projected, summary = m55r1.projected_epsilon(epsilon, mapping)
    assert np.all(projected > 0)
    assert summary["projected_c3_residual_max"] <= summary["identity_guard"]
    assert summary["global_mean_residual"] <= summary["identity_guard"]
    assert np.isclose(projected.mean(), epsilon.mean())
    assert m55r1.scalar_patch_needed({"scalar_c3_status": "FAIL", "scalar_projection_linf": 1.0, "scalar_identity_guard": 1e-12})
    assert not m55r1.scalar_patch_needed({"scalar_c3_status": "PASS", "scalar_projection_linf": 1.0, "scalar_identity_guard": 1e-12})


def test_failure_set_relations_define_all_frequency_classifications():
    stock = _freq([(0, 1, "IDENTITY", "C3"), (1, 2, "C3", "C3_SQUARED")])
    assert m55r1.classify(stock, _freq([]))[0] == "R256_PROJECTED_EPSILON_FULL_FREQUENCY_RESTORATION"
    assert m55r1.classify(stock, _freq([(1, 2, "C3", "C3_SQUARED")]))[0] == "R256_PROJECTED_EPSILON_PARTIAL_FREQUENCY_RESTORATION"
    assert m55r1.classify(stock, _freq([(2, 3, "C3_SQUARED", "IDENTITY")]))[0] == "R256_PROJECTED_EPSILON_INTRODUCES_NEW_FAILURES"
    assert m55r1.classify(_freq([]), _freq([]))[0] == "R256_STOCK_MESH1_FREQUENCY_FAILURE_NOT_REPRODUCED"


def test_readback_gate_requires_identity_c3_and_mean_and_calls_init_only():
    class MP:
        NO_PARITY = object()

    class Solver:
        _m = np.ones(m55r1.SHAPE, dtype=float)
        def __init__(self):
            self.calls = []
        def init_params(self, parity, flag):
            self.calls.append((parity, flag))
        def get_epsilon(self):
            return self._m

    solver = Solver()
    projected = Solver._m
    gate = m55r1._readback_gate(solver, projected, MP)
    assert solver.calls == [(MP.NO_PARITY, False)]
    assert gate["readback_gate"]
    assert gate["readback_c3_residual_max"] >= 0.0


def test_public_probe_contract_does_not_reuse_stock_geometry_or_solve_before_gate():
    text = SOURCE.read_text(encoding="utf-8")
    assert "MEEP_MATERIAL_GRID_DEFAULT_MATERIAL" in text
    assert "MEEP_MATERIAL_GRID_FULL_CELL_BLOCK" in text
    assert "MPB_MATERIAL_GRID" in text
    assert "init_params" in text and "get_epsilon" in text
    assert "geometry=[material]" not in text
    assert "run_parity" in text
    assert "solver_execution_count" in text


def test_fixed_solver_contract_and_no_forbidden_science_outputs():
    text = SOURCE.read_text(encoding="utf-8")
    assert "resolution=256" in text and "mesh_size=1" in text and "tolerance=1e-9" in text
    assert "Berry" not in text.split("def main", 1)[0]
    assert "fields_gaps_subspaces_wilson_berry_computed" in text
