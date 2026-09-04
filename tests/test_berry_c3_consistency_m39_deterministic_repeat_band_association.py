from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("m39", ROOT / "audit/berry_c3_consistency/m39_g15_deterministic_repeat_band_association_worst_orbit_pilot.py")
assert SPEC and SPEC.loader
m39 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m39)


def test_legacy_schedule_is_preserved_as_historical_reference():
    schedule = m39.build_schedule()
    assert len(schedule) == 15
    assert sum(item["deterministic"] for item in schedule) == 9
    assert sum(not item["deterministic"] for item in schedule) == 6
    assert {(item["c3_member_identity"], item["deterministic"], item["repeat_index"]) for item in schedule}.__len__() == 15


def test_recovery_schedule_is_exactly_fourteen_new_states_without_consumed_identity():
    schedule = m39.build_recovery_schedule()
    keys = {(item["c3_member_identity"], item["deterministic"], item["repeat_index"]) for item in schedule}
    assert len(schedule) == 14
    assert len(keys) == 14
    assert sum(item["deterministic"] for item in schedule) == 9
    assert sum(not item["deterministic"] for item in schedule) == 5
    assert ("IDENTITY", True, 0) not in keys
    assert {(item["repeat_index"], item["c3_member_identity"]) for item in schedule if item["deterministic"]} == {(repeat, member) for repeat in (1, 2, 3) for member in m39.MEMBERS}
    assert {(item["repeat_index"], item["c3_member_identity"]) for item in schedule if not item["deterministic"]} == {(0, member) for member in m39.MEMBERS} | {(1, member) for member in ("C3", "C3_SQUARED")}


def test_native_mode_component_band_layout_normalizes_to_band_mode_component():
    raw = np.zeros((m39.P, 2, m39.BANDS), dtype=np.complex128)
    canonical, layout = m39.normalize_raw(raw)
    assert canonical.shape == (4, m39.P, 2)
    assert layout["layout"] == "NATIVE_MODE_TRANSVERSE_COMPONENT_BAND"


def test_low_rank_projector_distance_does_not_allocate_ambient_projectors():
    rng = np.random.default_rng(39)
    source = rng.normal(size=(4, 12, 2)) + 1j * rng.normal(size=(4, 12, 2))
    target = source.copy()
    result = m39.low_rank_metrics(source, target)
    assert np.allclose(result["singular_values"], [1.0, 1.0])
    assert result["projector_distance"] == 0.0


def test_request_schedule_contains_four_bands_and_fresh_repeat_identity():
    member = {"coordinate": [0.1, 0.2, 0.0]}
    specs = [m39.request_spec(member, item, "d6a29ebb78c791f37931cefab644dacd770ad894") for item in m39.build_schedule()]
    assert all(item["num_bands"] == 4 and item["resolution"] == 128 and item["mesh_size"] == 3 for item in specs)
    assert len({item["request_key_sha256"] for item in specs}) == 15
    assert all("member" not in item and "c3_member_identity" in item for item in specs)


def test_capture_state_consumes_post_solve_using_canonical_member_key():
    class FakeMP:
        TE = object()

    class FakeSolver:
        all_freqs = np.asarray([[1.0, 2.0, 3.0, 4.0]])

        def run_parity(self, *_args):
            return None

        def get_eigenvectors(self, *_args):
            return np.zeros((m39.P, 2, m39.BANDS), dtype=np.complex128)

    class FakeCounter:
        def __init__(self):
            self.provider_count = 0
            self.solver_count = 0

        def consume_provider(self):
            self.provider_count += 1

        def consume_solver(self):
            self.solver_count += 1

    item = m39.build_recovery_schedule()[0]
    spec = m39.request_spec({"coordinate": [0.1, 0.2, 0.0]}, item, "source")
    counter = FakeCounter()
    record = m39.capture_state(FakeMP(), FakeSolver(), None, spec, counter, "source")
    assert record["c3_member_identity"] == item["c3_member_identity"]
    assert record["raw_layout"]["layout"] == "NATIVE_MODE_TRANSVERSE_COMPONENT_BAND"
    assert counter.provider_count == counter.solver_count == 1
    assert set(record["adjacent_gaps"]) >= {"band2_isolation_gap", "band3_isolation_gap", "minimum_external_rank2_gap"}


def test_causal_classifier_reaches_all_authorized_classes_without_fixed_threshold():
    common = {"combined_repeat_uncertainty": 0.05, "deterministic_repeat_spread": 0.01, "cross_c3_deficit": 0.25, "adjacent_pair_stable": True, "adjacent_pair_noncanonical": False, "deterministic_same_k_stable": True}
    assert m39.classify_causal(deterministic_minimum=0.95, nondeterministic_minimum=0.70, **common) == "RANDOM_INITIALIZATION"
    assert m39.classify_causal(deterministic_minimum=0.70, nondeterministic_minimum=0.70, **{**common, "adjacent_pair_noncanonical": True, "deterministic_same_k_stable": False}) == "BAND_ASSOCIATION_OR_NEAR_DEGENERACY"
    assert m39.classify_causal(deterministic_minimum=0.70, nondeterministic_minimum=0.71, **common) == "REMAINING_NUMERICAL_OR_PHYSICAL_C3_BREAKING"
    assert m39.classify_causal(deterministic_minimum=0.95, nondeterministic_minimum=0.70, **{**common, "adjacent_pair_noncanonical": True}) == "MULTIPLE_IDENTIFIED_CAUSES"
    assert m39.classify_causal(deterministic_minimum=0.50, nondeterministic_minimum=0.70, **{**common, "deterministic_same_k_stable": False}) == "UNRESOLVED_UNDER_BOUNDED_EXPERIMENT"


def test_source_forbids_symmetry_expansion_and_dense_projector_path():
    source = (ROOT / "audit/berry_c3_consistency/m39_g15_deterministic_repeat_band_association_worst_orbit_pilot.py").read_text(encoding="utf-8")
    assert "symmetry" not in source.lower()
    assert "32768, 32768" not in source
