"""Focused M8 runtime-map and bounded-acquisition tests."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / "audit" / "berry_c3_consistency" / "m8_minimal_runtime_spatial_map_and_rank2_closure.py"
SPEC = importlib.util.spec_from_file_location("berry_c3_m8", ENTRYPOINT)
assert SPEC and SPEC.loader
M8 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M8)


class _Vector:
    def __init__(self, x, y, z=0.0):
        self.x, self.y, self.z = x, y, z


class _Counter:
    def __init__(self):
        self.provider_count = 0
        self.solver_count = 0

    def consume_provider(self):
        self.provider_count += 1

    def consume_solver(self):
        self.solver_count += 1


def _provider():
    return SimpleNamespace(geometry_lattice=SimpleNamespace(basis1=_Vector(1.0, 0.0), basis2=_Vector(0.5, np.sqrt(3.0) / 2.0)))


def _snapshot(shape=(4, 4)):
    rng = np.random.default_rng(7)
    fields = [rng.normal(size=2 * shape[0] * shape[1] * 3) + 1j * rng.normal(size=2 * shape[0] * shape[1] * 3) for _ in range(4)]
    fields = [item / np.linalg.norm(item) for item in fields]
    return SimpleNamespace(spatial_shape=shape, frequencies=np.asarray([1.0, 2.0, 2.5, 4.0]), normalized_vectors=fields, provenance={})


def _targets():
    return [{"request_key_sha256": f"k{member}", "geometry_id": "G16", "member_index": member, "coordinate": [0.2 + member * 0.01, 0.1], "solver_configuration": {"resolution": 128, "deterministic": False, "stencil": "lab_fixed"}} for member in range(3)]


def test_exactly_three_target_states_are_dispatchable_and_identity_is_preserved():
    counter = _Counter()
    calls = []

    def solve(_provider, coordinate):
        calls.append(tuple(coordinate))
        return _snapshot()

    records, failure = M8.acquire_three_states(_targets(), lambda _target: _provider(), solve, counter)
    assert failure is None
    assert len(records) == counter.provider_count == counter.solver_count == 3
    assert len(calls) == 3
    assert {record["member_index"] for record in records} == {0, 1, 2}
    assert all(record["solver_configuration"]["resolution"] == 128 for record in records)


def test_exact_lattice_action_and_full_operator_preserve_norm_and_cube_to_identity():
    provider = _provider()
    metadata = M8.runtime_grid_metadata(provider, _snapshot((128, 128)))
    assert metadata["index_to_coordinate_map_status"].startswith("CAPTURED_FROM_RUNTIME")
    assert metadata["runtime_to_serialized_vector_index_map_status"].startswith("EXACT_C_ORDER")
    validation = M8.validate_full_operator((128, 128), metadata["_index_map"])
    assert validation["synthetic_scalar_norm_preserved"]
    assert validation["synthetic_vector_norm_preserved"]
    assert validation["synthetic_scalar_c3_residual"] <= 1e-12
    assert validation["synthetic_vector_c3_residual"] <= 1e-12


def test_full_operator_contains_no_numerical_degree_of_freedom():
    source = ENTRYPOINT.read_text(encoding="utf-8")
    assert "np.linalg.lstsq" not in source
    assert "nearest" not in source.lower()
    assert "U(2)" not in source
    assert "provider.solve(tuple(float(value) for value in coordinate))" in source


def test_m8_is_bounded_and_does_not_claim_extra_observables():
    source = ENTRYPOINT.read_text(encoding="utf-8")
    assert "TARGET_COUNT = 3" in source
    assert "FULL_M4_COUNT = 24" in source
    assert "Chern" not in source
    assert "Berry curvature" not in source
