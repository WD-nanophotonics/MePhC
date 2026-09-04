from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "audit/berry_c3_consistency/m48_seven_resolution_mixed_family_mechanism_localization.py"
SPEC = importlib.util.spec_from_file_location("m48r1_impl", SOURCE)
assert SPEC and SPEC.loader
m48 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m48)


def seq(w2="VALID_POSITIVE_P", w3="VALID_POSITIVE_P"):
    return {"fits": {"160-192-224": {"status": w2}, "192-224-256": {"status": w3}}, "table": []}


def part(ok, key):
    return {"sequence_count": 1, "all_w3_valid": ok, "failing_identities": [] if ok else [key], "transition_classes": {key: "STABLE_LATE_ASYMPTOTIC" if ok else "PERSISTENT_NONASYMPTOTIC"}}


def test_order_independent_lift_and_ambiguous_pi():
    a = m48._phase_lift([3.12, -3.12, 3.10]); b = m48._phase_lift([3.10, 3.12, -3.12])
    assert np.allclose(sorted(a["lifted_phases"]), sorted(b["lifted_phases"]))
    assert not a["ambiguous"] and m48._phase_lift([0.0, np.pi])["ambiguous"]


def test_density_and_branch_uncertainty_are_distinct():
    value = m48._scalar_stats([0.2, 0.4, 0.6], [1.0, 2.0, 4.0])
    assert value["uncertainty"] != value["phase_uncertainty"]


def test_transition_ledger_preserves_withholding_reason():
    value = m48._with_transitions({"x": {"fits": {"160-192-224": {"status": "NO_ASYMPTOTIC_MODEL", "reason": "ratio_at_or_below_p0_limit"}, "192-224-256": {"status": "VALID_POSITIVE_P"}}}})["x"]
    assert value["transition_class"] == "ENTERING_ASYMPTOTIC"
    assert value["withholding_reasons"]["160-192-224"] == "ratio_at_or_below_p0_limit"


def test_earliest_layer_priority_and_multiple_failure_routing():
    stable = {"unstable": False}; good = {name: part(True, name) for name in ("frequency", "gap", "subspace", "berry")}
    assert m48._localize(good, stable)[0] == "ALL_LATEST_FAMILIES_ASYMPTOTIC_AFTER_CORRECTION"
    bad = dict(good); bad["frequency"] = part(False, "frequency")
    assert m48._localize(bad, stable)[0] == "FREQUENCY_DISCRETIZATION_NONASYMPTOTIC"
    bad["berry"] = part(False, "berry")
    assert m48._localize(bad, stable)[0] == "MULTIPLE_STRUCTURED_MIXED_FAILURES"


def test_association_precedes_scalar_localization():
    good = {name: part(True, name) for name in ("frequency", "gap", "subspace", "berry")}
    assert m48._localize(good, {"unstable": True})[0] == "HIGH_RESOLUTION_ASSOCIATION_INSTABILITY"


def test_c3_pairwise_test_does_not_use_hardcoded_status():
    summary = {"rank1_qualification": {"status": "RANK1_QUALIFIED"}, "member_summary": {member: {"rank1_phase_density": {"median": 1.0, "uncertainty": 0.01}, "rank2_trace_phase_density": {"median": 1.0, "uncertainty": 0.01}} for member in m48.MEMBERS}}
    summary["member_summary"][m48.MEMBERS[-1]]["rank2_trace_phase_density"]["median"] = -1.0
    assert m48._c3_pair_test(summary, "rank2_trace_phase_density", False) == "FAIL"


def test_final_result_serialization_and_no_resolution_extension():
    encoded = json.dumps(m48._safe({"nan": float("nan"), "inf": float("inf")}))
    assert '"nan": "NAN"' in encoded and '"inf": "INF"' in encoded
    assert "R288" not in SOURCE.read_text(encoding="utf-8")
