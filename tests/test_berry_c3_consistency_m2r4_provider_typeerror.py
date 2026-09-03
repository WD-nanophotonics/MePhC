"""M2R4 tests for the exact production-provider call boundary."""
from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / "audit" / "berry_c3_consistency" / "m2_live_c3_acquisition_and_reduction.py"
SPEC = importlib.util.spec_from_file_location("berry_c3_m2r4", ENTRYPOINT)
assert SPEC and SPEC.loader
M2 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M2)


def _provider_type():
    from mephc.mpb_energy_spectral_provider import MPBLiveEnergySpectralProvider

    return MPBLiveEnergySpectralProvider


def test_contract_records_exact_old_typeerror_and_supported_signature():
    provider_type = _provider_type()
    signature = inspect.signature(provider_type.solve)
    assert str(signature) == "(self, k_point: 'Sequence[float]') -> 'MPBHEnvelopeSnapshot'"
    provider = provider_type(geometry=(), geometry_lattice=object(), resolution=128, num_bands=4)
    with pytest.raises(TypeError) as error:
        provider.solve(request={"coordinate": [0.0, 0.0]})
    assert str(error.value) == M2.PREVIOUS_TYPEERROR_MESSAGE
    assert M2.PREVIOUS_TYPEERROR_CALLSITE.endswith("provider.solve(request=production_request)")
    assert "positional k_point" in M2.PREVIOUS_TYPEERROR_ARGUMENT_MISMATCH


def test_corrected_call_uses_real_constructor_and_public_method(monkeypatch):
    provider_type = _provider_type()
    calls = []

    def mocked_solver_boundary(self, k_point):
        calls.append(tuple(k_point))
        return "solver-boundary-reached"

    monkeypatch.setattr(provider_type, "solve", mocked_solver_boundary)
    provider = provider_type(geometry=(), geometry_lattice=object(), resolution=128, num_bands=4)
    result = M2.invoke_production_request(
        provider,
        {
            "provider_symbol": M2.PRODUCTION_PROVIDER_SYMBOL,
            "coordinate": [0.125, -0.25],
            "record_request_key_sha256": "r" * 64,
            "constituent_request_key_sha256": "c" * 64,
        },
    )
    assert result == "solver-boundary-reached"
    assert calls == [(0.125, -0.25)]


def test_all_72_semantic_records_expand_to_288_unique_provider_calls():
    plan = M2.derive_plan(M2.verify_m1_bundle())
    calls = []
    for item in plan["live_requests"]:
        for constituent in M2.expand_constituent_requests(item):
            production = M2.build_production_request(item, constituent)
            assert production["provider_symbol"] == M2.PRODUCTION_PROVIDER_SYMBOL
            assert isinstance(production["coordinate"], list)
            calls.append(production["constituent_request_key_sha256"])
    assert len(calls) == len(set(calls)) == 288


def test_result_exposes_bounded_typeerror_forensics():
    plan = M2.derive_plan(M2.verify_m1_bundle())
    fake = M2._BootstrapFakeBoundary()
    execution = M2.execute_injected_plan(plan, fake)
    result = M2.compact_success(plan, execution, M2.reduce_evidence(execution))
    assert result["previous_typeerror_message"] == M2.PREVIOUS_TYPEERROR_MESSAGE
    assert result["previous_typeerror_callsite"] == M2.PREVIOUS_TYPEERROR_CALLSITE
    assert result["previous_typeerror_argument_mismatch"] == M2.PREVIOUS_TYPEERROR_ARGUMENT_MISMATCH
    assert result["production_provider_public_call_signature"] == M2.PRODUCTION_PROVIDER_PUBLIC_CALL_SIGNATURE
