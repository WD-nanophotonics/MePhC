from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "audit/berry_c3_consistency/m56r1_hdf5_epsilon_input_frequency_ab.py"
SPEC = importlib.util.spec_from_file_location("m56r1_test_module", SOURCE)
assert SPEC and SPEC.loader
m56r1 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m56r1)


def _freq(failures):
    return {"failure_set": [{"vertex": v, "band": b, "source_member": s, "target_member": t} for v, b, s, t in failures], "failure_count": len(failures)}


class _FakeDataset:
    def __init__(self, value):
        self.value = np.asarray(value)
        self.shape = self.value.shape
    def __array__(self, dtype=None):
        return np.asarray(self.value, dtype=dtype)


class _FakeFile:
    files = {}
    def __init__(self, path, mode):
        self.path, self.mode = path, mode
    def __enter__(self):
        if self.mode == "w":
            self.data = {}
            _FakeFile.files[self.path] = self.data
        else:
            self.data = _FakeFile.files[self.path]
        return self
    def __exit__(self, *args):
        return False
    def create_dataset(self, name, data):
        self.data[name] = _FakeDataset(data)
    def keys(self):
        return self.data.keys()
    def __getitem__(self, name):
        return self.data[name]
    def visititems(self, visitor):
        for name, node in self.data.items():
            visitor(name, node)


class _FakeWriter:
    File = _FakeFile


def test_hdf5_writer_creates_one_data_dataset_and_exact_roundtrip():
    value = np.ones(m56r1.SHAPE, dtype=float); value[3, 7] = 4.0
    evidence = m56r1.write_and_verify_hdf5(_FakeWriter, Path("epsilon.h5"), value)
    assert evidence["dataset_names"] == ["data"]
    assert evidence["shape"] == [256, 256]
    assert evidence["roundtrip_verified"]
    assert evidence["value_sha256"] == m56r1.hashlib.sha256(value.tobytes()).hexdigest()


def test_projection_is_exact_positive_mean_preserving_and_nontrivial():
    mapping = m56r1.m54.build_index_map(); epsilon = np.ones(m56r1.SHAPE); epsilon[3, 7] = 4.0
    projected, summary = m56r1.projected_epsilon(epsilon, mapping)
    assert np.all(projected > 0)
    assert summary["projection_linf"] > summary["identity_guard"]
    assert summary["global_mean_residual"] <= summary["identity_guard"]


def test_epsilon_input_file_requires_public_source_confirmation():
    class Documented:
        def __init__(self, epsilon_input_file):
            """Public epsilon_input_file names the HDF5 dielectric grid."""
            self.epsilon_input_file = epsilon_input_file
    assert m56r1.epsilon_input_file_evidence(Documented)["epsilon_input_file_exposed"]

    class Unrelated:
        def __init__(self, geometry):
            self.geometry = geometry
    assert not m56r1.epsilon_input_file_evidence(Unrelated)["epsilon_input_file_exposed"]


def test_material_gate_has_init_only_scalar_and_tensor_requirements():
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
            return np.ones(m56r1.SHAPE)
        def get_epsilon_inverse_tensor_point(self, point):
            return np.eye(3)
    solver = Solver(); gate = m56r1.material_operator_gate(solver, np.ones(m56r1.SHAPE), MP)
    assert solver.calls == [(MP.NO_PARITY, False)]
    assert gate["scalar_readback_gate"] and gate["tensor_readback_gate"] and gate["operator_gate"]


def test_no_numpy_file_or_stock_geometry_and_no_solve_before_gate():
    text = SOURCE.read_text(encoding="utf-8")
    assert ".npy" not in text
    assert "epsilon_input_file" in text and "geometry=[]" in text
    assert "get_epsilon_inverse_tensor_point" in text and "run_parity" in text
    assert "solver_execution_count" in text


def test_failure_set_relations_cover_authorized_frequency_outcomes():
    stock = _freq([(0, 1, "IDENTITY", "C3"), (1, 2, "C3", "C3_SQUARED")])
    assert m56r1.classify(stock, _freq([]))[0] == "R256_HDF5_PROJECTED_EPSILON_FULL_FREQUENCY_RESTORATION"
    assert m56r1.classify(stock, _freq([(1, 2, "C3", "C3_SQUARED")]))[0] == "R256_HDF5_PROJECTED_EPSILON_PARTIAL_FREQUENCY_RESTORATION"
    assert m56r1.classify(stock, _freq([(2, 3, "C3_SQUARED", "IDENTITY")]))[0] == "R256_HDF5_PROJECTED_EPSILON_INTRODUCES_NEW_FAILURES"
    assert m56r1.classify(_freq([]), _freq([]))[0] == "R256_STOCK_MESH1_FREQUENCY_FAILURE_NOT_REPRODUCED"
