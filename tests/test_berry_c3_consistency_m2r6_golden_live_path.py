"""M2R6 equivalence checks against the proven E8B live MPB path."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / "audit" / "berry_c3_consistency" / "m2_live_c3_acquisition_and_reduction.py"
GOLDEN = ROOT / "audit" / "e8b" / "run_e8b.py"
GOLDEN_RESULT = ROOT / "audit" / "e8b" / "result.json"
SPEC = importlib.util.spec_from_file_location("berry_c3_m2r6", ENTRYPOINT)
assert SPEC and SPEC.loader
M2 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M2)


def test_selected_golden_path_has_historical_nonzero_live_evidence():
    source = GOLDEN.read_text(encoding="utf-8")
    result = json.loads(GOLDEN_RESULT.read_text(encoding="utf-8"))
    assert M2.GOLDEN_LIVE_ENTRYPOINT == "audit/e8b/run_e8b.py"
    assert M2.GOLDEN_PROVIDER_SYMBOL == M2.PRODUCTION_PROVIDER_SYMBOL
    assert "MPBLiveEnergySpectralProvider" in source
    assert "provider.solve(tuple(float(x) for x in q))" in source
    assert result["telemetry"]["raw_solver_requests"] > 0
    assert result["telemetry"]["solver_failures"] == 0


def test_one_m2_constituent_reaches_golden_provider_boundary(monkeypatch):
    from mephc.mpb_energy_spectral_provider import MPBLiveEnergySpectralProvider

    observed = []

    def golden_backend(self, *args, **kwargs):
        observed.append((args, kwargs))
        assert len(args) == 1 and kwargs == {}
        return object()

    monkeypatch.setattr(MPBLiveEnergySpectralProvider, "solve", golden_backend)
    provider = MPBLiveEnergySpectralProvider(geometry=(), geometry_lattice=object(), resolution=128, num_bands=4)
    item = M2.derive_plan(M2.verify_m1_bundle())["live_requests"][0]
    constituent = M2.build_production_request(item, M2.expand_constituent_requests(item)[0])
    assert M2.invoke_production_request(provider, constituent) is not None
    assert observed == [(((tuple(constituent["coordinate"])),), {})]


def test_full_m2_plan_reaches_same_boundary_288_times(monkeypatch):
    from mephc.mpb_energy_spectral_provider import MPBLiveEnergySpectralProvider

    observed = []

    def golden_backend(self, *args, **kwargs):
        assert len(args) == 1 and kwargs == {}
        point = args[0]
        assert isinstance(point, tuple) and len(point) == 2
        observed.append(point)
        return object()

    monkeypatch.setattr(MPBLiveEnergySpectralProvider, "solve", golden_backend)
    provider = MPBLiveEnergySpectralProvider(geometry=(), geometry_lattice=object(), resolution=128, num_bands=4)
    plan = M2.derive_plan(M2.verify_m1_bundle())

    def golden_dispatch(item):
        for constituent in M2.expand_constituent_requests(item):
            M2.invoke_production_request(provider, M2.build_production_request(item, constituent))
        semantic = item["semantic_identity"]
        return {
            "record_id": f"m2r6-{item['request_key_sha256']}-{item['repeat_index']}",
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

    execution = M2.execute_injected_plan(plan, golden_dispatch)
    assert execution["failures"] == []
    assert len(execution["results"]) == 72
    assert len(observed) == 288
