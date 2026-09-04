from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "audit/berry_c3_consistency/m42_m41r3_corrected_uncertainty_cheapest_control_adjudication.py"
SPEC = importlib.util.spec_from_file_location("m42", SOURCE)
assert SPEC and SPEC.loader
m42 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m42)


def _analysis(rank1="PASS", qualified="RANK1_QUALIFIED", stable=True, rank2_stable=True):
    members = {}
    for member in m42.MEMBERS:
        members[member] = {
            "rank1_phase_density": {"median": 1.0, "uncertainty": 0.01},
            "rank2_trace_phase_density": {"median": 2.0, "uncertainty": 0.01},
            "rank1_association": stable,
            "rank2_association": {edge: {"state": "CANONICAL_STABLE" if rank2_stable else "REPEAT_UNSTABLE"} for edge in range(4)},
            "rank1_qualification": {"status": qualified},
        }
    return {"configuration_id": "SYNTHETIC", "member_summary": members, "rank1_qualification": {"status": qualified, "stable_band2_association": stable}, "rank2_association_stable": rank2_stable, "rank1_c3_status": rank1, "rank2_c3_status": rank1}


def test_branch_safe_lifting_is_order_independent_and_marks_pi_ambiguity():
    first = m42._phase_lift([3.12, -3.12, 3.10])
    second = m42._phase_lift([3.10, 3.12, -3.12])
    assert first["ambiguous"] is False
    assert second["ambiguous"] is False
    assert max(first["lifted_phases"]) - min(first["lifted_phases"]) < 0.1
    assert m42._phase_lift([0.0, np.pi])["ambiguous"] is True


def test_phase_density_uncertainty_is_in_density_units_not_raw_phase_units():
    stats = m42._scalar_stats([0.2, 0.4, 0.6], [1.0, 2.0, 4.0])
    densities = stats["values"]
    expected = max(abs(value - np.median(densities)) for value in densities)
    assert stats["uncertainty"] == expected
    assert stats["uncertainty"] != max(abs(value - np.median([0.2, 0.4, 0.6])) for value in [0.2, 0.4, 0.6])


def test_association_states_preserve_canonical_noncanonical_and_unstable():
    assert m42._association_state([[2, 3], [2, 3], [2, 3]]) == "CANONICAL_STABLE"
    assert m42._association_state([[1, 4], [1, 4], [1, 4]]) == "NONCANONICAL_STABLE"
    assert m42._association_state([[2, 3], [1, 4], [2, 3]]) == "REPEAT_UNSTABLE"


def test_r96_r128_plateau_is_independent_of_r64():
    r64 = _analysis(rank1="FAIL")
    r96 = _analysis(rank1="PASS")
    r128 = _analysis(rank1="PASS")
    assert m42._plateau(r96, r128) is True
    assert m42._plateau(r64, r128) is False


def test_classification_routes_multiple_cause_and_association_cases():
    analyses = {name: _analysis() for name in ("R128_T1E7_M3", "R128_T1E9_M3", "R128_T1E9_M1", "R64_T1E9_M3", "R96_T1E9_M3")}
    comparisons = {key: m42._pair_table(analyses["R128_T1E7_M3"], analyses["R128_T1E9_M3"], key) for key in ("tolerance", "mesh", "R64_R128", "R96_R128")}
    flags, synthesis = m42._classify(analyses, comparisons)
    assert synthesis in {"NUMERICAL_SETTINGS_QUALIFIED_C3_RESTORED", "UNRESOLVED_UNDER_BOUNDED_EXPERIMENT"}
    assert flags["R96_R128_high_resolution_plateau"] is True
    analyses["R128_T1E9_M3"] = _analysis(stable=False, rank2_stable=False)
    flags, synthesis = m42._classify(analyses, comparisons)
    assert flags["association_problem"] is True
    assert synthesis in {"BAND_ASSOCIATION_OR_NEAR_DEGENERACY", "MULTIPLE_IDENTIFIED_CAUSES"}


def test_contract_is_zero_execution_and_result_only():
    source = SOURCE.read_text(encoding="utf-8")
    assert "native_invocation_count\": 0" in source
    assert "provider_execution_count\": 0" in source
    assert "solver_execution_count\": 0" in source
    assert "R96_R128_high_resolution_plateau" in source
    assert "selected_cheapest_qualified_measured_setting" in source
    assert "M41R3_MULTIPLE_IDENTIFIED_CAUSES" not in source

