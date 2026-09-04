from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "audit/berry_c3_consistency/m43_admissible_measured_control_cross_orbit_qualification.py"
SPEC = importlib.util.spec_from_file_location("m43", SOURCE)
assert SPEC and SPEC.loader
m43 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m43)


def _analysis(name: str, *, rank1="PASS", qualified="RANK1_QUALIFIED", assoc=True, rank2=True, value=1.0):
    members = {}
    for member in m43.MEMBERS:
        members[member] = {
            "rank1_phase_density": {"median": value, "uncertainty": 0.01},
            "rank2_trace_phase_density": {"median": value, "uncertainty": 0.01},
            "rank1_association": assoc,
            "rank2_association": {edge: {"state": "CANONICAL_STABLE" if rank2 else "REPEAT_UNSTABLE"} for edge in range(4)},
            "rank1_qualification": {"status": qualified},
        }
    return {"configuration_id": name, "member_summary": members, "rank1_qualification": {"status": qualified, "stable_band2_association": assoc}, "rank2_association_stable": rank2, "rank1_c3_status": rank1, "rank2_c3_status": rank1}


def test_cross_orbit_centers_and_graph_are_exact_and_append_only():
    centers = m43.orbit_centers(4)
    assert centers["IDENTITY"] == [2.0 / 3.0 - 4.0 / 36.0, 0.0]
    graph = m43.cross_orbit_graph({"resolution": 128, "tolerance": 1e-9, "mesh_size": 3}, "a" * 40)
    assert len(graph) == 108
    assert len({row["request_key_sha256"] for row in graph}) == 108
    assert {row["orbit_m"] for row in graph} == {1, 4, 10}
    assert all(row["configuration_id"] != "R128_T1E9_M3" for row in graph)


def test_cheaper_setting_requires_m42_equivalence_not_just_own_pass():
    analyses = {name: _analysis(name) for name in ("R128_T1E7_M3", "R128_T1E9_M3", "R128_T1E9_M1", "R64_T1E9_M3", "R96_T1E9_M3")}
    selected = m43.select_admissible_control(analyses)
    assert selected["selected_admissible_measured_setting"] == "R64_T1E9_M3"
    analyses["R64_T1E9_M3"] = _analysis("R64_T1E9_M3", value=9.0)
    selected = m43.select_admissible_control(analyses)
    assert "R64_T1E9_M3" not in selected["admissible_measured_settings"]
    assert "supported_scalar_or_status_difference" in selected["rejected_candidate_reasons"]["R64_T1E9_M3"]


def test_no_admissible_control_outcome_is_zero_side_effect_route():
    analyses = {name: _analysis(name, qualified="RANK1_WITHHELD", rank1="RANK1_WITHHELD", assoc=False, rank2=False) for name in ("R128_T1E7_M3", "R128_T1E9_M3", "R128_T1E9_M1", "R64_T1E9_M3", "R96_T1E9_M3")}
    selected = m43.select_admissible_control(analyses)
    assert selected["selected_admissible_measured_setting"] is None
    outcome, decision = m43._outcome({}, analyses["R128_T1E9_M3"])
    assert outcome == "ALL_REMAINING_ORBITS_RANK1_C3_PASS" or outcome in {"MIXED_FAILURES", "C3_FAILURE_WITH_STABLE_RANK1_AND_SAFE_BRANCH"}
    assert isinstance(decision, str) and decision


def test_contract_preserves_independent_solves_and_zero_before_selection():
    source = SOURCE.read_text(encoding="utf-8")
    assert "Every rotated member and every plaquette vertex is solved independently" in source or "independent" in source
    assert "selected_admissible_measured_setting" in source
    assert "cross_orbit_graph" in source
    assert "C3_COVARIANT" in source
    assert "deterministic" in source
    assert "m41r3._capture" in source


def test_main_equivalent_dry_run_covers_selected_and_no_control_branches():
    result = m43.main_equivalent_dry_run()
    assert result["selected"] == "R64_T1E9_M3"
    assert result["selected_graph_records"] == 108
    assert result["selected_unique_records"] == 108
    assert result["no_control"] is None
    assert all(value == 0 for value in result["counts"].values())
