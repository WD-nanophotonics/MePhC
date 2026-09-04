from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "audit/berry_c3_consistency/m48_seven_resolution_mixed_family_mechanism_localization.py"
SPEC = importlib.util.spec_from_file_location("m48", SOURCE)
assert SPEC and SPEC.loader
m48 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m48)


def sequence(status_w2: str = "VALID_POSITIVE_P", status_w3: str = "VALID_POSITIVE_P"):
    return {"fits": {"160-192-224": {"status": status_w2}, "192-224-256": {"status": status_w3}}, "table": []}


def partition(all_w3_valid: bool, name: str):
    return {"sequence_count": 1, "all_w3_valid": all_w3_valid, "failing_identities": [] if all_w3_valid else [name], "transition_classes": {name: "STABLE_LATE_ASYMPTOTIC" if all_w3_valid else "PERSISTENT_NONASYMPTOTIC"}}


def test_order_independent_circular_lift_and_pi_ambiguity():
    first = m48._phase_lift([3.12, -3.12, 3.10])
    second = m48._phase_lift([3.10, 3.12, -3.12])
    assert first["ambiguous"] is False
    assert second["ambiguous"] is False
    assert np.allclose(sorted(first["lifted_phases"]), sorted(second["lifted_phases"]))
    assert m48._phase_lift([0.0, np.pi])["ambiguous"] is True


def test_phase_density_uncertainty_is_separate_from_wrapped_phase_uncertainty():
    result = m48._scalar_stats([0.2, 0.4, 0.6], [1.0, 2.0, 4.0])
    assert result["uncertainty"] == max(abs(value - np.median(result["values"])) for value in result["values"])
    assert result["phase_uncertainty"] > 0
    assert result["uncertainty"] != result["phase_uncertainty"]


def test_c3_pair_test_is_real_and_rank1_withheld_when_gate_fails():
    summary = {"rank1_qualification": {"status": "RANK1_WITHHELD"}, "member_summary": {member: {"rank1_phase_density": {"median": 1.0, "uncertainty": 0.01}, "rank2_trace_phase_density": {"median": 1.0, "uncertainty": 0.01}} for member in m48.MEMBERS}}
    assert m48._c3_pair_test(summary, "rank1_phase_density", True) == "RANK1_WITHHELD"
    summary["rank1_qualification"]["status"] = "RANK1_QUALIFIED"
    summary["member_summary"][m48.MEMBERS[1]]["rank1_phase_density"]["median"] = -1.0
    assert m48._c3_pair_test(summary, "rank1_phase_density", True) == "FAIL"


def test_transition_ledger_preserves_each_fit_reason():
    values = {"a": {"fits": {"160-192-224": {"status": "NO_ASYMPTOTIC_MODEL", "reason": "ratio_at_or_below_p0_limit"}, "192-224-256": {"status": "VALID_POSITIVE_P"}}}}
    result = m48._with_transitions(values)["a"]
    assert result["transition_class"] == "ENTERING_ASYMPTOTIC"
    assert result["withholding_reasons"]["160-192-224"] == "ratio_at_or_below_p0_limit"


def test_localization_uses_earliest_failing_layer_and_multiple_failures():
    stable = {"unstable": False}
    all_valid = {name: partition(True, name) for name in ("frequency", "gap", "subspace", "berry")}
    assert m48._localize(all_valid, stable) == ("ALL_LATEST_FAMILIES_ASYMPTOTIC_AFTER_CORRECTION", "R256_CONTINUUM_AND_FINITE_CONTROL_REQUALIFICATION")
    frequency_fail = dict(all_valid); frequency_fail["frequency"] = partition(False, "frequency")
    assert m48._localize(frequency_fail, stable)[0] == "FREQUENCY_DISCRETIZATION_NONASYMPTOTIC"
    multiple = dict(frequency_fail); multiple["berry"] = partition(False, "berry")
    assert m48._localize(multiple, stable)[0] == "MULTIPLE_STRUCTURED_MIXED_FAILURES"
    assert m48._localize(all_valid, {"unstable": True})[0] == "HIGH_RESOLUTION_ASSOCIATION_INSTABILITY"


def test_partition_requires_all_w3_sequences_not_a_majority():
    values = {"ok": {"transition_class": "STABLE_LATE_ASYMPTOTIC", "fits": {"192-224-256": {"status": "VALID_POSITIVE_P"}}}, "bad": {"transition_class": "PERSISTENT_NONASYMPTOTIC", "fits": {"192-224-256": {"status": "NO_ASYMPTOTIC_MODEL"}}}}
    result = m48._partition(values, ["ok", "bad"])
    assert result["all_w3_valid"] is False
    assert result["failing_identities"] == ["bad"]


def test_result_serialization_is_finite_and_source_stays_solver_free():
    encoded = json.dumps(m48._safe({"status": "PASS", "nan": float("nan"), "inf": float("inf")}), separators=(",", ":"))
    assert '"nan":"NAN"' in encoded and '"inf":"INF"' in encoded
    text = SOURCE.read_text(encoding="utf-8")
    assert "R288" not in text
    assert "native_invocation_count" in text
    assert "provider_execution_count" in text
    assert "solver_execution_count" in text
