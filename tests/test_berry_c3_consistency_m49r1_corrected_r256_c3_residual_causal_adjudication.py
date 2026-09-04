from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "audit/berry_c3_consistency/m49r1_corrected_r256_c3_residual_causal_adjudication.py"
SPEC = importlib.util.spec_from_file_location("m49r1_test_module", SOURCE)
assert SPEC and SPEC.loader
m49r1 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m49r1)


def _scalar_values(left=0.1, right=0.2, third=0.3, uncertainty=0.0):
    return {
        resolution: {
            member: {"median": value, "repeat_uncertainty": uncertainty}
            for member, value in zip(m49r1.MEMBERS, (left, right, third))
        }
        for resolution in m49r1.RESOLUTIONS
    }


def _berry_values(left=0.2, right=0.3, third=0.4):
    return {
        resolution: {
            member: {
                "phase_median_lifted": phase,
                "phase_repeat_uncertainty": 0.01,
                "density_values": [phase / 0.5],
                "density_median": phase / 0.5,
                "density_repeat_uncertainty": 0.01,
                "signed_area_median": 0.5,
                "branch_ambiguous": False,
            }
            for member, phase in zip(m49r1.MEMBERS, (left, right, third))
        }
        for resolution in m49r1.RESOLUTIONS
    }


def test_berry_stats_keeps_phase_and_density_units_separate():
    result = m49r1._berry_stats([0.2, 2 * 3.141592653589793 + 0.3], [0.5, 0.5])
    assert "phase_median_lifted" in result
    assert "density_median" in result
    assert result["density_median"] != result["phase_median_lifted"]
    assert result["signed_area_median"] == 0.5


def test_berry_residual_uses_resolution_member_axis_and_aligns_phase_only():
    result = m49r1._berry_residual("rank2", _berry_values(), "berry_rank2")
    pair = result["pairs"]["IDENTITY_vs_C3"]
    assert "aligned_phase224_left" in pair
    assert "resolution_uncertainty_left" in pair
    assert pair["resolution_uncertainty_left"] >= 0.0
    assert "density_median" not in pair["aligned_phase224_left"] if isinstance(pair["aligned_phase224_left"], dict) else True


def test_berry_exact_pi_inter_resolution_branch_is_not_silently_routed():
    values = _berry_values(left=0.0, right=0.5, third=0.8)
    for resolution in (224,):
        values[resolution]["IDENTITY"]["phase_median_lifted"] = 3.141592653589793
    values[256]["IDENTITY"]["phase_median_lifted"] = 0.0
    result = m49r1._berry_residual("rank2", values, "berry_rank2")
    assert result["branch_ambiguity"] is True
    assert result["pairs"]["IDENTITY_vs_C3"]["pass"] is False


def test_scalar_residual_requires_three_members_and_uses_overlap_intervals():
    result = m49r1._scalar_residual("frequency", _scalar_values(left=0.1, right=-0.1, third=0.2, uncertainty=0.2), "frequency")
    assert result["pass"] is True
    assert result["pairs"]["IDENTITY_vs_C3"]["opposite_significant"] is False
    assert result["uncertainty_components"]
    bad = _scalar_values()
    del bad[256][m49r1.MEMBERS[2]]
    try:
        m49r1._scalar_residual("bad", bad, "frequency")
    except ValueError as exc:
        assert "MEMBER_AXIS" in str(exc)
    else:
        raise AssertionError("missing canonical member was accepted")


def test_family_preserves_identity_resolution_member_axes():
    source = {"vertex0:band1": {resolution: {member: [0.1, 0.1, 0.1] for member in m49r1.MEMBERS} for resolution in m49r1.RESOLUTIONS}}
    family = m49r1._family(source, "frequency")
    residual = family["identities"]["vertex0:band1"]
    assert set(residual["per_resolution"]["256"]) == set(m49r1.MEMBERS)


def test_main_equivalent_berry_builder_returns_resolution_major_structure():
    matrix = {resolution: [] for resolution in m49r1.RESOLUTIONS}
    analyses = {}
    for resolution in m49r1.RESOLUTIONS:
        plaquettes = []
        for index, member in enumerate(m49r1.MEMBERS):
            plaquettes.append({"member": member, "signed_area": 0.5, "rank2_trace_phase": 0.1 + index * 0.01, "rank1_phase": 0.2 + index * 0.01})
        analyses[resolution] = {"plaquettes": plaquettes}
    rank2, rank1 = m49r1._build_berry(matrix, analyses)
    assert list(rank2) == list(m49r1.RESOLUTIONS)
    assert set(rank2[256]) == set(m49r1.MEMBERS)
    assert "phase_median_lifted" in rank2[256]["IDENTITY"]


def test_localization_maps_multiple_failure_to_concrete_earliest_intervention():
    families = {name: {"all_pass": name not in {"frequency", "subspace"}} for name in ("frequency", "gap", "subspace", "berry_rank2")}
    outcome, decision, layers = m49r1._localize(families, False, False, {"eligible": True, "c3_pass": False, "blockers": {}}, {"unstable": False})
    assert outcome == "R256_MULTIPLE_C3_BREAKING_LAYERS"
    assert decision == "BOUND_R256_MESH_DISCRETIZATION_CONTROL"
    assert layers == ["frequency", "subspace"]


def test_localization_distinguishes_rank1_isolation_branch_and_unresolved():
    families = {name: {"all_pass": True} for name in ("frequency", "gap", "subspace", "berry_rank2")}
    for expected, blockers in (
        ("R256_RANK2_C3_PASS_RANK1_WITHHELD_ISOLATION_OR_ASSOCIATION", {"isolation_or_association": True, "branch_only": False, "unresolved": False}),
        ("R256_RANK2_C3_PASS_RANK1_WITHHELD_BRANCH", {"isolation_or_association": False, "branch_only": True, "unresolved": False}),
        ("R256_RANK2_C3_PASS_RANK1_WITHHELD_UNRESOLVED", {"isolation_or_association": False, "branch_only": False, "unresolved": True}),
    ):
        outcome, _decision, _layers = m49r1._localize(families, True, False, {"eligible": False, "blockers": blockers}, {"unstable": False})
        assert outcome == expected


def test_matrix_uses_partial_namespace_and_exact_252_records(monkeypatch):
    def rows(resolution):
        return [{"resolution": resolution, "configuration_id": f"R{resolution}_T1E9_M3", "geometry_id": "G15", "stencil": "C3_COVARIANT", "mesh_size": 3} for _ in range(36)]

    m41 = rows(64) + rows(96); m44 = rows(160) + rows(192); m46 = rows(224); m47 = rows(256); partial = rows(128)
    def read_dataset(_job, _root, dataset_id, _manifest, _schema, expected):
        if expected == 108: return m41
        if expected == 72: return m44
        if expected == 36: return m46 if dataset_id.startswith("6a0bd") else m47
        return [{"marker": expected}] * expected
    monkeypatch.setattr(m49r1.m41r3, "_read_dataset", read_dataset)
    monkeypatch.setattr(m49r1.m41r3, "_read_partial", lambda _job, _root: partial)
    monkeypatch.setattr(m49r1.m41r3, "_centers", lambda *_args: {})
    monkeypatch.setattr(m49r1.m41r3, "_load", lambda *_args: object())
    matrix, _centers, _m38, _m39 = m49r1._read_matrix(object(), Path("."))
    assert sum(len(records) for records in matrix.values()) == 252
    assert len(matrix[128]) == 36


def test_entrypoint_is_zero_execution_and_does_not_delegate_to_prior_analysis():
    text = SOURCE.read_text(encoding="utf-8")
    assert m49r1.RESULT_SCHEMA in text
    assert "R288" not in text
    assert "m49_r256" not in text
    assert "m49r1_job" in text
    assert '"native_invocation_count": 0' in text
    assert '"provider_execution_count": 0' in text
    assert '"solver_execution_count": 0' in text
