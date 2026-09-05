from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "audit/berry_c3_consistency/m54_r256_material_grid_subpixel_c3_readback_ab.py"
SPEC = importlib.util.spec_from_file_location("m54_test_module", SOURCE)
assert SPEC and SPEC.loader
m54 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m54)


class FakeMP:
    NO_PARITY = object()

    class Vector3:
        def __init__(self, x, y, z):
            self.x, self.y, self.z = x, y, z


class FakeSolver:
    def __init__(self):
        self.calls = []

    def init_params(self, *args):
        self.calls.append(("init_params", args))

    def get_epsilon(self):
        self.calls.append("get_epsilon")
        return np.full(16, 2.0)

    def get_epsilon_inverse_tensor_point(self, point):
        self.calls.append("get_epsilon_inverse_tensor_point")
        return np.eye(3) / 2.0

    def run(self, *args, **kwargs):
        raise AssertionError("eigensolver path is forbidden")

    def run_parity(self, *args, **kwargs):
        raise AssertionError("eigensolver path is forbidden")


def test_direct_grid_map_is_exact_bijective_and_cubed():
    mapping = m54.build_index_map((256, 256))
    assert mapping.shape == (256, 256, 2)
    assert len({tuple(item) for item in mapping.reshape(-1, 2)}) == 65536


def test_tensor_canonicalization_and_rotation_are_cartesian():
    tensor = m54.canonical_tensor_grid(np.broadcast_to(np.eye(3), (256, 256, 3, 3)))
    assert tensor.shape == (256, 256, 3, 3)
    assert np.allclose(m54.tensor_rotation(np.eye(3)), np.eye(3))
    check = m54.synthetic_tensor_rotation_check()
    assert check["direct_grid_c3_cubed"]


def test_material_covariance_uses_exact_map_and_audit_projection():
    mapping = m54.build_index_map()
    scalar = np.ones((256, 256))
    tensor = np.broadcast_to(np.eye(3), (256, 256, 3, 3)).copy()
    result = m54.material_covariance(scalar, tensor, mapping)
    assert result["scalar_c3_status"] == "PASS"
    assert result["tensor_c3_status"] == "PASS"
    assert result["projected_material_c3_status"] == "PASS"
    assert result["projection_scientific_status"] == "AUDIT_ONLY_NOT_FED_TO_EIGENSOLVER"


def test_init_and_public_getters_never_call_eigensolver():
    solver, mp = FakeSolver(), FakeMP()
    solver.init_params(mp.NO_PARITY, False)
    epsilon = np.asarray(solver.get_epsilon()).reshape(4, 4)
    tensor = m54._tensor(solver.get_epsilon_inverse_tensor_point(mp.Vector3(0, 0, 0)))
    assert epsilon.shape == (4, 4)
    assert tensor.shape == (3, 3)
    assert solver.calls[0][0] == "init_params"
    assert not any(call in ("run", "run_parity") for call in solver.calls)


def test_frequency_classification_has_one_authorized_route():
    frequency = {str(mesh): {"failure_count": 1 if mesh == 5 else 0} for mesh in (1, 3, 5)}
    material = {str(mesh): {"scalar_c3_status": "PASS", "tensor_c3_status": "PASS"} for mesh in (1, 3, 5)}
    outcome, decision = m54.classify(frequency, material)
    assert outcome == "R256_MATERIAL_READBACK_C3_COVARIANT_DESPITE_FREQUENCY_FAILURE"
    assert decision == "MPB_K_DEPENDENT_DISCRETE_OPERATOR_C3_SOURCE_AUDIT"


def test_source_contains_no_eigensolver_invocation():
    text = SOURCE.read_text(encoding="utf-8")
    assert ".run(" not in text
    assert ".run_parity(" not in text
    assert "solve_kpoint" not in text
    assert "ModeSolver.init_params(NO_PARITY,False)" in text
