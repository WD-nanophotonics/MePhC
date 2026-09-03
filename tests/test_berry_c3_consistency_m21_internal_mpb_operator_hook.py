"""M21 bounded internal-hook tests using strict fake solver objects."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / "audit" / "berry_c3_consistency" / "m21_internal_mpb_staggering_constitutive_hook.py"
SPEC = importlib.util.spec_from_file_location("berry_c3_m21", ENTRYPOINT)
assert SPEC and SPEC.loader
M21 = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(M21)


class Counter:
    def __init__(self):
        self.solver_count = 0
    def consume_solver(self):
        self.solver_count += 1


class FakeSolver:
    def __init__(self):
        self.calls = []
        self.public_grid = [1, 2, 3]
    def run_parity(self, parity, reset):
        self.calls.append(("run_parity", parity, reset))
    def get_efield(self, band, bloch_phase=False):
        raise AssertionError("hook must not invoke public field getters")


def members():
    return [{"member_index": index, "c3_member_identity": identity, "request_key_sha256": f"{index:064x}", "coordinate": [0.0, 0.0]} for index, identity in enumerate(("IDENTITY", "C3", "C3_SQUARED"))]


def factory(member):
    return FakeSolver(), type("Point", (), {"x": 0.0, "y": 0.0, "z": 0.0})(), "TE"


def test_exactly_three_fixed_solves_and_no_public_getter_calls():
    created = []
    def make(member):
        solver, reciprocal, parity = factory(member); created.append(solver); return solver, reciprocal, parity
    counter = Counter(); records = M21.capture_triplet(members(), make, counter)
    assert len(records) == 3 and counter.solver_count == 3
    assert all(solver.calls == [("run_parity", "TE", False)] for solver in created)
    assert all(item["direct_mpb_methods_invoked"] == ["ModeSolver.run_parity"] for item in records)


def test_hook_distinguishes_metadata_from_raw_arrays():
    observed = M21.observe_internal_metadata(FakeSolver())
    assert observed["hook_status"] == "CAPTURED_PARTIAL_NATIVE_METADATA"
    assert all("value" in item and "scalar_value" not in item["value"] for item in observed["metadata"] if item["access"] == "READ_ONLY")


def test_hook_failure_is_bounded_and_serializable():
    class Broken:
        def __dir__(self):
            return ["staggered_grid"]
        @property
        def staggered_grid(self):
            raise RuntimeError("unavailable")
    observed = M21.observe_internal_metadata(Broken())
    encoded = json.dumps(observed, allow_nan=False)
    assert "FAILED" in encoded and observed["hook_status"] == "INTERNAL_MPB_OPERATOR_OBJECT_NOT_ACCESSIBLE_IN_INSTALLED_RUNTIME"


def test_entrypoint_has_no_solver_factory_or_provider_import():
    text = ENTRYPOINT.read_text(encoding="utf-8")
    assert "MPBLiveSpectralProvider" not in text and "solve_mpb_energy" not in text
