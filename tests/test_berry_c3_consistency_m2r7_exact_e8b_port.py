"""M2R7 zero-side-effect publication checks for the E8B live path port."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / "audit" / "berry_c3_consistency" / "m2_live_c3_acquisition_and_reduction.py"
GOLDEN = ROOT / "audit" / "e8b" / "run_e8b.py"
MACHINE = ROOT / "audit" / "berry_c3_consistency" / "m2_machine_execution_contract.json"
SPEC = importlib.util.spec_from_file_location("berry_c3_m2r7p", ENTRYPOINT)
assert SPEC and SPEC.loader
M2 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M2)


def test_machine_contract_binds_the_final_zero_side_effect_package():
    contract = json.loads(MACHINE.read_text(encoding="utf-8"))
    assert contract["live_entrypoint"] == str(ENTRYPOINT.relative_to(ROOT)).replace("\\", "/")
    assert contract["m1_request_graph_sha256"] == M2.EXPECTED_GRAPH_SHA256
    assert contract["future_native_budget"] == 1
    assert contract["future_provider_budget"] == 288
    assert contract["future_solver_budget"] == 288
    assert contract["expected_dataset_records"] == 72
    assert contract["future_runtime_mutates_tracked_files"] is False
    assert contract["machine_contract_ready"] is True


def test_representative_request_uses_e8b_equivalent_provider_boundary(monkeypatch):
    from mephc.mpb_energy_spectral_provider import MPBLiveEnergySpectralProvider

    observed = []

    def mocked_backend(self, *args, **kwargs):
        observed.append((args, kwargs))
        assert len(args) == 1 and kwargs == {}
        return object()

    monkeypatch.setattr(MPBLiveEnergySpectralProvider, "solve", mocked_backend)
    provider = MPBLiveEnergySpectralProvider(geometry=(), geometry_lattice=object(), resolution=128, num_bands=4)
    item = M2.derive_plan(M2.verify_m1_bundle())["live_requests"][0]
    production = M2.build_production_request(item, M2.expand_constituent_requests(item)[0])
    assert M2.invoke_production_request(provider, production) is not None
    assert observed and len(observed[0][0]) == 1 and observed[0][1] == {}
    assert M2.GOLDEN_SOLVE_PATTERN in GOLDEN.read_text(encoding="utf-8")


def test_full_fake_pilot_reaches_mocked_backend_288_times_without_aliasing(monkeypatch):
    from mephc.mpb_energy_spectral_provider import MPBLiveEnergySpectralProvider

    observed = []

    def mocked_backend(self, *args, **kwargs):
        assert len(args) == 1 and kwargs == {}
        point = args[0]
        assert isinstance(point, tuple) and len(point) == 2
        observed.append(point)
        return object()

    monkeypatch.setattr(MPBLiveEnergySpectralProvider, "solve", mocked_backend)
    provider = MPBLiveEnergySpectralProvider(geometry=(), geometry_lattice=object(), resolution=128, num_bands=4)
    plan = M2.derive_plan(M2.verify_m1_bundle())

    def dispatch(item):
        for constituent in M2.expand_constituent_requests(item):
            M2.invoke_production_request(provider, M2.build_production_request(item, constituent))
        semantic = item["semantic_identity"]
        return {
            "record_id": f"m2r7p-{item['request_key_sha256']}-{item['repeat_index']}",
            "orbit_id": semantic["orbit_id"], "member_index": semantic["member_index"],
            "coordinate": semantic["public_coordinate"], "geometry_id": semantic["geometry_id"],
            "domain_id": semantic["domain_id"], "band_identity": "band-2-of-4",
            "subspace_identity": "rank1-and-composite-diagnostics",
            "qualification_status": "PENDING_REPEAT_QUALIFICATION", "observable": 1.0,
        }

    execution = M2.execute_injected_plan(plan, dispatch)
    assert execution["failures"] == []
    assert len(execution["results"]) == 72
    assert len(observed) == 288
