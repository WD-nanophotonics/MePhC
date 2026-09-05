from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "audit/berry_c3_consistency/m57_hdf5_epsilon_input_semantics_and_frequency_ab.py"
SPEC = importlib.util.spec_from_file_location("m57_test_module", SOURCE)
assert SPEC and SPEC.loader
m57 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m57)


class FakeDataset:
    def __init__(self, value):
        self.value = np.asarray(value); self.shape = self.value.shape
    def __array__(self, dtype=None):
        return np.asarray(self.value, dtype=dtype)


class FakeFile:
    files = {}
    def __init__(self, path, mode): self.path, self.mode = path, mode
    def __enter__(self):
        if self.mode == "w": self.data = {}; FakeFile.files[self.path] = self.data
        else: self.data = FakeFile.files[self.path]
        return self
    def __exit__(self, *args): return False
    def create_dataset(self, name, data): self.data[name] = FakeDataset(data)
    def __getitem__(self, name): return self.data[name]
    def visititems(self, visitor):
        for name, node in self.data.items(): visitor(name, node)


class FakeWriter:
    File = FakeFile


def _freq(failures):
    return {"failure_set": [{"vertex": v, "band": b, "source_member": s, "target_member": t} for v, b, s, t in failures], "failure_count": len(failures)}


def test_bounded_semantic_matrix_is_finite_and_declared():
    candidates = m57.semantic_candidates()
    assert len(candidates) == 10
    assert {c["axis_mode"] for c in candidates} == {"direct", "transpose"}
    assert {tuple(c["periodic_shift"]) for c in candidates} == {(0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)}
    assert all(c["dataset_name"] == "data" for c in candidates)


def test_hdf5_variant_writer_reopens_exactly_one_data_dataset():
    projected = np.ones(m57.SHAPE); projected[3, 7] = 4.0
    values = m57.hdf5_variant_values(projected, "transpose", (1, 0))
    evidence = m57.write_verify_hdf5(FakeWriter, Path("m57.h5"), values)
    assert evidence["dataset_names"] == ["data"]
    assert evidence["shape"] == [256, 256]
    assert evidence["roundtrip_verified"]


def test_projection_and_scalar_need_gate():
    mapping = m57.m54.build_index_map(); epsilon = np.ones(m57.SHAPE); epsilon[3, 7] = 4.0
    projected, summary = m57.projected_epsilon(epsilon, mapping)
    assert summary["projection_linf"] > summary["identity_guard"]
    assert summary["global_mean_residual"] <= summary["identity_guard"]
    assert m57.scalar_patch_needed({"scalar_c3_status": "FAIL", "scalar_projection_linf": 1.0, "scalar_identity_guard": 1e-12})


def test_source_audit_requires_epsilon_input_file_public_semantics():
    class Documented:
        def __init__(self, epsilon_input_file):
            """Public epsilon_input_file reads an HDF5 first dataset."""
            self.epsilon_input_file = epsilon_input_file
    evidence = m57.binding_evidence(Documented)
    assert evidence["epsilon_input_file_exposed"] and evidence["hdf5_or_first_dataset_evidence"]


def test_material_gate_requires_init_only_scalar_and_tensor_c3():
    class MP:
        NO_PARITY = object()
        class Vector3:
            def __init__(self, *values): self.values = values
    class Solver:
        def __init__(self): self.calls = []
        def init_params(self, parity, flag): self.calls.append((parity, flag))
        def get_epsilon(self): return np.ones(m57.SHAPE)
        def get_epsilon_inverse_tensor_point(self, point): return np.eye(3)
    solver = Solver(); gate = m57.material_gate(solver, np.ones(m57.SHAPE), MP)
    assert solver.calls == [(MP.NO_PARITY, False)]
    assert gate["scalar_readback_gate"] and gate["tensor_readback_gate"] and gate["operator_gate"]


def test_exact_failure_set_relations_only_classify_frequency_outcomes():
    stock = _freq([(0, 1, "IDENTITY", "C3"), (1, 2, "C3", "C3_SQUARED")])
    assert m57.classify(stock, _freq([]))[0] == "R256_HDF5_SEMANTICS_FULL_FREQUENCY_RESTORATION"
    assert m57.classify(stock, _freq([(1, 2, "C3", "C3_SQUARED")]))[0] == "R256_HDF5_SEMANTICS_PARTIAL_FREQUENCY_RESTORATION"
    assert m57.classify(stock, _freq([(2, 3, "C3_SQUARED", "IDENTITY")]))[0] == "R256_HDF5_SEMANTICS_INTRODUCES_NEW_FAILURES"
    assert m57.classify(_freq([]), _freq([]))[0] == "R256_STOCK_MESH1_FREQUENCY_FAILURE_NOT_REPRODUCED"


def test_no_solver_before_material_gate_and_no_scientific_expansion():
    text = SOURCE.read_text(encoding="utf-8")
    assert "solver.run_parity" in text
    assert "geometry=[]" in text
    assert "fields_gaps_subspaces_wilson_berry_computed" in text
    assert "correlation" not in text.lower()
