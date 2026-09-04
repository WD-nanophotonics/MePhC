from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "audit/berry_c3_consistency/m49_r256_c3_residual_uncertainty_causal_adjudication.py"
SPEC = importlib.util.spec_from_file_location("m49_test_module", SOURCE)
assert SPEC and SPEC.loader
m49 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m49)


def _values(left: float = 0.1, right: float = 0.2, uncertainty: float = 0.0):
    return {
        resolution: {
            member: {"median": value, "repeat_uncertainty": uncertainty}
            for member, value in ((m49.MEMBERS[0], left), (m49.MEMBERS[1], right), (m49.MEMBERS[2], left + right))
        }
        for resolution in m49.RESOLUTIONS
    }


def test_phase_lift_is_order_independent_and_marks_pi_ambiguity():
    forward = m49._phase_lift([0.2, 2 * 3.141592653589793 + 0.3])
    reverse = m49._phase_lift([2 * 3.141592653589793 + 0.3, 0.2])
    assert sorted(round(value, 12) for value in forward["lifted_phases"]) == sorted(round(value, 12) for value in reverse["lifted_phases"])
    assert m49._phase_lift([0.0, 3.141592653589793])["ambiguous"] is True


def test_residual_uses_intervals_for_opposite_signs_and_adjacent_uncertainty():
    values = _values(left=0.1, right=-0.1, uncertainty=0.2)
    result = m49._residual("synthetic", values, "frequency")
    assert result["pass"] is True
    pair = result["pairs"][f"{m49.MEMBERS[0]}_vs_{m49.MEMBERS[1]}"]
    assert pair["opposite_significant"] is False
    assert pair["sign_rule_pass"] is True
    assert "absolute_fit_context" in result

    separated = _values(left=0.5, right=-0.5, uncertainty=0.0)
    failed = m49._residual("synthetic", separated, "frequency")
    assert failed["pairs"][f"{m49.MEMBERS[0]}_vs_{m49.MEMBERS[1]}"]["opposite_significant"] is True
    assert failed["pass"] is False


def test_berry_residual_includes_r224_to_r256_area_aware_uncertainty():
    values = {
        resolution: {
            member: {"median": 0.01 * resolution, "repeat_uncertainty": 0.001, "area": 0.5}
            for member in m49.MEMBERS
        }
        for resolution in m49.RESOLUTIONS
    }
    result = m49._residual("berry", values, "berry_rank2", berry=True)
    pair = result["pairs"][f"{m49.MEMBERS[0]}_vs_{m49.MEMBERS[1]}"]
    assert pair["resolution_uncertainty_left"] > 0.0
    assert result["uncertainty_rule"] == "repeat_plus_R224_to_R256_adjacent_resolution"


def test_sequence_retains_three_window_fit_statuses():
    values = {resolution: [float(resolution) ** -0.5, float(resolution) ** -0.5] for resolution in m49.RESOLUTIONS}
    sequence = m49._sequence(values, "synthetic")
    assert [row["resolution"] for row in sequence["table"]] == list(m49.RESOLUTIONS)
    assert set(sequence["fits"]) == {"128-160-192", "160-192-224", "192-224-256"}
    assert sequence["repeat_uncertainty_separate"] is True


def test_association_and_localization_prioritize_repeated_instability():
    assert m49._association_state([[2, 3], [2, 3]]) == "CANONICAL_STABLE"
    assert m49._association_state([[2, 3], [1, 4]]) == "REPEAT_UNSTABLE"
    families = {name: {"all_pass": True} for name in ("frequency", "gap", "subspace", "berry_rank2")}
    classification, decision, layers = m49._localize(
        families,
        True,
        {"eligible": True, "c3_pass": True, "blockers": {"isolation_or_association": False}},
        {"unstable": True},
    )
    assert classification == "R256_HIGH_RESOLUTION_ASSOCIATION_INSTABILITY"
    assert decision.startswith("ADAPTIVE_VALIDATED")
    assert layers == ["association"]


def test_rank1_branch_ambiguity_is_read_from_corrected_detail():
    analysis = {"member_summary": {}}
    for member in m49.MEMBERS:
        analysis["member_summary"][member] = {
            "rank1_phase_density": {"branch_ambiguous": member == m49.MEMBERS[0]},
            "rank1_qualification": {"stable_band2_association": True, "gap_ratio": 20.0, "link_ratio": 20.0, "branch_ratio": 10.0},
        }
    blockers = m49._rank1_blockers(analysis)
    assert "branch_ambiguity" in blockers["per_member"][m49.MEMBERS[0]]["branch_only_blockers"]
    assert blockers["branch_only"] is True


def test_matrix_binds_exactly_252_records_and_uses_r128_partial(monkeypatch):
    def rows(resolution):
        return [
            {"resolution": resolution, "configuration_id": f"R{resolution}_T1E9_M3", "geometry_id": "G15", "stencil": "C3_COVARIANT", "mesh_size": 3}
            for _ in range(36)
        ]

    m41 = rows(64) + rows(96)
    m44 = rows(160) + rows(192)
    m46 = rows(224)
    m47 = rows(256)

    def read_dataset(_job, _root, _dataset_id, _manifest, _schema, expected):
        if expected == 108:
            return m41
        if expected == 72:
            return m44
        if expected == 36:
            return m46 if _dataset_id.startswith("6a0bd") else m47
        return [{"marker": expected}] * expected

    partial = rows(128)
    monkeypatch.setattr(m49.m41r3, "_read_dataset", read_dataset)
    monkeypatch.setattr(m49.m41r3, "_read_partial", lambda _job, _root: partial)
    monkeypatch.setattr(m49.m41r3, "_centers", lambda *_args: {})
    monkeypatch.setattr(m49.m41r3, "_load", lambda *_args: object())
    matrix, _centers, _m38, _m39 = m49._matrix(object(), Path("."))
    assert {resolution: len(records) for resolution, records in matrix.items()} == {resolution: 36 for resolution in m49.RESOLUTIONS}
    assert sum(len(records) for records in matrix.values()) == 252
    assert all(row["resolution"] == 128 for row in matrix[128])


def test_entrypoint_is_result_only_and_does_not_extend_resolution():
    text = SOURCE.read_text(encoding="utf-8")
    assert m49.RESULT_SCHEMA in text
    assert "R288" not in text
    assert "m48r2.main" not in text
    assert "m48r1" not in text
    assert '"native_invocation_count": 0' in text
    assert '"provider_execution_count": 0' in text
    assert '"solver_execution_count": 0' in text
