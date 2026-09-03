"""M2R5 proof that the live adapter dispatches positional k-points only."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / "audit" / "berry_c3_consistency" / "m2_live_c3_acquisition_and_reduction.py"
SPEC = importlib.util.spec_from_file_location("berry_c3_m2r5", ENTRYPOINT)
assert SPEC and SPEC.loader
M2 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M2)


def test_live_entrypoint_has_no_reachable_legacy_request_keyword_call():
    source = ENTRYPOINT.read_text(encoding="utf-8")
    assert "provider.solve(request=" not in source
    assert "provider.solve(production_request)" not in source
    assert "invoke_production_request(provider, request)" in source
    assert M2.PRODUCTION_PROVIDER_CALL_FORM == "provider.solve(k_point)"


def test_real_provider_class_receives_one_positional_kpoint(monkeypatch):
    from mephc.mpb_energy_spectral_provider import MPBLiveEnergySpectralProvider

    calls = []

    def instrumented_solve(self, *args, **kwargs):
        calls.append((args, kwargs))
        assert len(args) == 1
        assert kwargs == {}
        assert isinstance(args[0], tuple)
        assert len(args[0]) == 2
        return "solver-boundary"

    monkeypatch.setattr(MPBLiveEnergySpectralProvider, "solve", instrumented_solve)
    provider = MPBLiveEnergySpectralProvider(geometry=(), geometry_lattice=object(), resolution=128, num_bands=4)
    result = M2.invoke_production_request(
        provider,
        {"provider_symbol": M2.PRODUCTION_PROVIDER_SYMBOL, "coordinate": [0.1, 0.2]},
    )
    assert result == "solver-boundary"
    assert calls == [(((0.1, 0.2),), {})]


def test_legacy_request_keyword_is_rejected_by_real_provider_api():
    from mephc.mpb_energy_spectral_provider import MPBLiveEnergySpectralProvider

    provider = MPBLiveEnergySpectralProvider(geometry=(), geometry_lattice=object(), resolution=128, num_bands=4)
    with pytest.raises(TypeError, match="unexpected keyword argument 'request'"):
        provider.solve(request={"coordinate": [0.1, 0.2]})


def test_exact_fake_child_dispatch_proves_72_records_and_288_positional_calls(monkeypatch):
    from mephc.mpb_energy_spectral_provider import MPBLiveEnergySpectralProvider

    calls = []

    def instrumented_solve(self, *args, **kwargs):
        assert len(args) == 1 and kwargs == {}
        point = args[0]
        assert isinstance(point, tuple) and len(point) == 2
        calls.append(point)
        return object()

    monkeypatch.setattr(MPBLiveEnergySpectralProvider, "solve", instrumented_solve)
    provider = MPBLiveEnergySpectralProvider(geometry=(), geometry_lattice=object(), resolution=128, num_bands=4)
    plan = M2.derive_plan(M2.verify_m1_bundle())

    def child_live_dispatch(item):
        for constituent in M2.expand_constituent_requests(item):
            M2.invoke_production_request(provider, M2.build_production_request(item, constituent))
        semantic = item["semantic_identity"]
        return {
            "record_id": f"m2r5-{item['request_key_sha256']}-{item['repeat_index']}",
            "orbit_id": semantic["orbit_id"],
            "member_index": semantic["member_index"],
            "coordinate": semantic["public_coordinate"],
            "geometry_id": semantic["geometry_id"],
            "domain_id": semantic["domain_id"],
            "band_identity": "band-2-of-4",
            "subspace_identity": "rank1-and-composite-diagnostics",
            "qualification_status": "PENDING_REPEAT_QUALIFICATION",
            "observable": 1.0,
        }

    execution = M2.execute_injected_plan(plan, child_live_dispatch)
    assert execution["failures"] == []
    assert len(execution["results"]) == 72
    assert len(calls) == 288
    assert len({(point[0], point[1]) for point in calls}) > 1
