"""Focused M4 target-selection, budget-boundary, and gauge-invariance tests."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / "audit" / "berry_c3_consistency" / "m4_rank2_targeted_acquisition_and_analysis.py"
SPEC = importlib.util.spec_from_file_location("berry_c3_m4", ENTRYPOINT)
assert SPEC and SPEC.loader
M4 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M4)


def _targets():
    targets = []
    for geometry in ("G15", "G16"):
        for deterministic in (False, True):
            for stencil in ("lab_fixed", "c3_covariant"):
                for member in range(3):
                    key = f"key-{geometry}-{deterministic}-{stencil}-{member}"
                    targets.append({
                        "request_key_sha256": key, "repeat_index": 1,
                        "semantic_identity": {
                            "geometry_id": geometry, "orbit_id": "M7", "member_index": member,
                            "public_coordinate": [0.1 + member * 0.01, 0.2], "domain_id": "raw_hbz",
                            "solver_configuration": {"deterministic": deterministic, "stencil": stencil},
                        },
                    })
    return targets


class _Counter:
    def __init__(self):
        self.provider_count = 0
        self.solver_count = 0

    def consume_provider(self):
        self.provider_count += 1

    def consume_solver(self):
        self.solver_count += 1


def _snapshot(seed=0):
    rng = np.random.default_rng(seed)
    vectors = []
    for _ in range(4):
        vector = rng.normal(size=8) + 1j * rng.normal(size=8)
        vectors.append(vector / np.linalg.norm(vector))
    return SimpleNamespace(frequencies=np.asarray([1.0, 2.0, 2.5, 4.0]), normalized_vectors=vectors)


def test_fixed_selector_has_exactly_eight_triplets_and_repeat_one():
    targets = _targets()
    records = [{"request_key_sha256": item["request_key_sha256"], "repeat_index": 1} for item in targets]
    selected = M4.select_fixed_targets(records, {"live_requests": targets})
    assert len(selected) == 24
    assert {item["repeat_index"] for item in selected} == {1}
    cells = {(item["semantic_identity"]["geometry_id"], item["semantic_identity"]["solver_configuration"]["deterministic"], item["semantic_identity"]["solver_configuration"]["stencil"]) for item in selected}
    assert len(cells) == 8
    assert {item["semantic_identity"]["member_index"] for item in selected} == {0, 1, 2}


def test_targeted_path_dispatches_exactly_24_calls_and_requests_rank2_payload():
    targets = _targets()
    counter = _Counter()
    calls = []

    def provider_getter(_semantic):
        return object()

    def solve(_provider, request):
        calls.append(request)
        return _snapshot(len(calls))

    records, failure = M4.acquire_targets(targets, provider_getter, solve, counter)
    assert failure is None
    assert len(records) == counter.provider_count == counter.solver_count == 24
    assert all(request["provider_symbol"] == M4.PRODUCTION_PROVIDER_SYMBOL for request in calls)
    assert all(request["band_target"]["vector_bands_zero_based"] == [1, 2] for request in calls)
    assert all(request["band_target"]["band_indices_zero_based"] == [0, 1, 2, 3] for request in calls)


def test_rank2_metrics_are_invariant_under_u2_basis_change():
    left, _ = np.linalg.qr(np.eye(4, 2))
    unitary, _ = np.linalg.qr(np.asarray([[1, 2j], [2, 1j]], dtype=complex))
    right = left @ unitary
    first = M4.rank2_metrics(left, right)
    second = M4.rank2_metrics(left @ unitary, right)
    assert np.allclose(first["overlap_singular_values"], [1.0, 1.0])
    assert np.allclose(first["overlap_singular_values"], second["overlap_singular_values"])
    assert np.isclose(first["projector_distance"], second["projector_distance"], atol=1e-7)
    assert np.isclose(first["projector_distance"], 0.0, atol=1e-7)


def test_entrypoint_does_not_modify_production_modules_or_claim_nonabelian_observable():
    source = ENTRYPOINT.read_text(encoding="utf-8")
    assert "m2_live_c3_acquisition_and_reduction.py" in source
    assert "Chern" not in source
    assert "curvature" not in source
    assert "TARGET_COUNT = 24" in source


def test_m4_request_is_accepted_by_the_production_adapter_contract():
    m2 = M4.load_m2()
    request = M4.single_point_request(_targets()[0])
    assert request["provider_symbol"] == m2.PRODUCTION_PROVIDER_SYMBOL
