from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "audit/berry_c3_consistency/m56_exact_scalar_epsilon_input_frequency_ab.py"
SPEC = importlib.util.spec_from_file_location("m56_test_module", SOURCE)
assert SPEC and SPEC.loader
m56 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m56)


def _freq(failures):
    return {"failure_set": [{"vertex": v, "band": b, "source_member": s, "target_member": t} for v, b, s, t in failures], "failure_count": len(failures)}


def test_projection_and_scalar_gate_are_nontrivial_and_exact():
    mapping = m56.m54.build_index_map(); epsilon = np.ones(m56.SHAPE); epsilon[3, 7] = 4.0
    projected, summary = m56.projected_epsilon(epsilon, mapping)
    assert summary["projection_linf"] > summary["identity_guard"]
    assert summary["projected_c3_residual_max"] <= summary["identity_guard"]
    assert summary["global_mean_residual"] <= summary["identity_guard"]
    assert m56.scalar_patch_needed({"scalar_c3_status": "FAIL", "scalar_projection_linf": 1.0, "scalar_identity_guard": 1e-12})
    assert not m56.scalar_patch_needed({"scalar_c3_status": "PASS", "scalar_projection_linf": 1.0, "scalar_identity_guard": 1e-12})


def test_only_source_confirmed_direct_parameters_are_admitted():
    class Documented:
        def __init__(self, epsilon_input):
            """Public epsilon_input array is consumed as scalar material data."""
            self.epsilon_input = epsilon_input

    candidates = m56.source_confirmed_candidates(Documented)
    assert len(candidates) == 1
    assert candidates[0]["kind"] == "array"
    assert candidates[0]["parameter"] == "epsilon_input"

    class Unrelated:
        def __init__(self, geometry):
            self.geometry = geometry

    assert m56.source_confirmed_candidates(Unrelated) == []


def test_frequency_failure_relations_define_all_adjudications():
    stock = _freq([(0, 1, "IDENTITY", "C3"), (1, 2, "C3", "C3_SQUARED")])
    assert m56.classify(stock, _freq([]))[0] == "R256_DIRECT_SCALAR_EPSILON_FULL_FREQUENCY_RESTORATION"
    assert m56.classify(stock, _freq([(1, 2, "C3", "C3_SQUARED")]))[0] == "R256_DIRECT_SCALAR_EPSILON_PARTIAL_FREQUENCY_RESTORATION"
    assert m56.classify(stock, _freq([(2, 3, "C3_SQUARED", "IDENTITY")]))[0] == "R256_DIRECT_SCALAR_EPSILON_INTRODUCES_NEW_FAILURES"
    assert m56.classify(_freq([]), _freq([]))[0] == "R256_STOCK_MESH1_FREQUENCY_FAILURE_NOT_REPRODUCED"


def test_material_gate_calls_init_only_and_requires_tensor_gate():
    class MP:
        NO_PARITY = object()
        class Vector3:
            def __init__(self, *values):
                self.values = values

    class Solver:
        def __init__(self):
            self.calls = []
        def init_params(self, parity, flag):
            self.calls.append((parity, flag))
        def get_epsilon(self):
            return np.ones(m56.SHAPE)
        def get_epsilon_inverse_tensor_point(self, point):
            return np.eye(3)

    gate = m56.material_operator_gate(Solver(), np.ones(m56.SHAPE), MP)
    assert gate["scalar_readback_gate"]
    assert gate["operator_gate"]
    assert gate["tensor_readback_gate"]


def test_no_generic_materialgrid_retrial_and_no_eigensolve_before_gate():
    text = SOURCE.read_text(encoding="utf-8")
    assert "getattr(mp, \"MaterialGrid\")" not in text
    assert "init_params" in text and "get_epsilon" in text and "get_epsilon_inverse_tensor_point" in text
    assert "run_parity" in text
    assert "geometry=[]" in text
    assert "solver_execution_count" in text


def test_fixed_solver_contract_and_forbidden_outputs():
    text = SOURCE.read_text(encoding="utf-8")
    assert "resolution=256" in text and "mesh_size=1" in text and "tolerance=1e-9" in text
    assert "Berry" not in text.split("def main", 1)[0]
    assert "fields_gaps_subspaces_wilson_berry_computed" in text
