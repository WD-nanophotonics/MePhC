from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "audit/berry_c3_consistency/m58_hdf5_transfer_inversion_frequency_ab.py"
SPEC = importlib.util.spec_from_file_location("m58_test_module", SOURCE)
assert SPEC and SPEC.loader
m58 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m58)


def _freq(failures):
    return {"failure_set": [{"vertex": v, "band": b, "source_member": s, "target_member": t} for v, b, s, t in failures], "failure_count": len(failures)}


def _blur(value):
    return 0.7 * value + 0.075 * np.roll(value, 1, 0) + 0.075 * np.roll(value, -1, 0) + 0.075 * np.roll(value, 1, 1) + 0.075 * np.roll(value, -1, 1)


def test_affine_shift_equivariant_transfer_calibration():
    offset = np.full(m58.SHAPE, 0.2)
    def read(value): return offset + _blur(np.asarray(value, dtype=float))
    calibration = m58.calibrate_transfer(read, 2.0, 0.01)
    assert calibration["deterministic"]
    assert calibration["affine_linear"]
    assert calibration["shift_equivariant"]
    assert calibration["kernel"].shape == m58.SHAPE


def test_inversion_recovers_positive_target_for_invertible_transfer():
    target = np.full(m58.SHAPE, 2.0); target[3, 7] = 2.4
    calibration = {"kernel": _blur(np.eye(256)[0].reshape(256, 1) @ np.ones((1, 256)) * 0 + np.eye(256)[0].reshape(256, 1) @ np.ones((1, 256)) * 0.0), "affine_offset": np.zeros(m58.SHAPE), "engineering_guard": 1e-12}
    # Identity kernel makes the mathematical inverse exact and keeps this a
    # small unit test of the no-regularization path.
    calibration["kernel"] = np.zeros(m58.SHAPE); calibration["kernel"][0, 0] = 1.0
    result = m58.invert_transfer(calibration, target)
    assert result["invertible"] and result["physical"] and result["prediction_pass"]
    assert np.allclose(result["preimage"], target)


def test_calibration_rejects_nonlinearity_and_non_shift_equivariance():
    def nonlinear(value): return np.asarray(value, dtype=float) ** 2
    assert not m58.calibrate_transfer(nonlinear, 2.0, 0.01)["affine_linear"]
    def nonshift(value):
        result = np.asarray(value, dtype=float).copy(); result[0, 0] = result.mean(); return result
    assert not m58.calibrate_transfer(nonshift, 2.0, 0.01)["shift_equivariant"]


def test_spectral_zero_and_nonphysical_preimage_are_fail_closed():
    zero = {"kernel": np.zeros(m58.SHAPE), "affine_offset": np.zeros(m58.SHAPE), "engineering_guard": 1e-12}
    result = m58.invert_transfer(zero, np.ones(m58.SHAPE))
    assert not result["invertible"]
    calibration = {"kernel": np.zeros(m58.SHAPE), "affine_offset": np.zeros(m58.SHAPE), "engineering_guard": 1e-12}; calibration["kernel"][0, 0] = 1.0
    result = m58.invert_transfer(calibration, np.full(m58.SHAPE, -1.0))
    assert result["invertible"] and not result["physical"]


def test_projection_and_exact_failure_set_classification():
    mapping = m58.m54.build_index_map(); epsilon = np.ones(m58.SHAPE); epsilon[3, 7] = 4.0
    projected, summary = m58.projected_epsilon(epsilon, mapping)
    assert summary["projection_linf"] > summary["identity_guard"]
    stock = _freq([(0, 1, "IDENTITY", "C3"), (1, 2, "C3", "C3_SQUARED")])
    assert m58.classify(stock, _freq([]))[0] == "R256_HDF5_TRANSFER_ADAPTER_FULL_FREQUENCY_RESTORATION"
    assert m58.classify(stock, _freq([(1, 2, "C3", "C3_SQUARED")]))[0] == "R256_HDF5_TRANSFER_ADAPTER_PARTIAL_FREQUENCY_RESTORATION"
    assert m58.classify(stock, _freq([(2, 3, "C3_SQUARED", "IDENTITY")]))[0] == "R256_HDF5_TRANSFER_ADAPTER_INTRODUCES_NEW_FAILURES"


def test_material_gate_and_contract_are_init_only_before_solver():
    class MP:
        NO_PARITY = object()
        class Vector3:
            def __init__(self, *values): self.values = values
    class Solver:
        def __init__(self): self.calls = []
        def init_params(self, parity, flag): self.calls.append((parity, flag))
        def get_epsilon(self): return np.ones(m58.SHAPE)
        def get_epsilon_inverse_tensor_point(self, point): return np.eye(3)
    solver = Solver(); gate = m58.material_gate(solver, np.ones(m58.SHAPE), MP)
    assert solver.calls == [(MP.NO_PARITY, False)] and gate["operator_gate"]
    text = SOURCE.read_text(encoding="utf-8")
    assert "run_parity" in text and "geometry=[]" in text and "get_epsilon_inverse_tensor_point" in text
    assert "np.linalg.pinv" not in text and "65536,65536" not in text
