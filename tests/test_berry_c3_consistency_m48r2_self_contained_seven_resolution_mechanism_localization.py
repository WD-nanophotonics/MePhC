from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "audit/berry_c3_consistency/m48r2_self_contained_seven_resolution_mechanism_localization.py"
SPEC = importlib.util.spec_from_file_location("m48r2", SOURCE)
assert SPEC and SPEC.loader
m48r2 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m48r2)


def _rows(resolution: int, count: int = 36):
    return [{"resolution": resolution, "configuration_id": f"R{resolution}_T1E9_M3", "geometry_id": "G15", "stencil": "C3_COVARIANT", "mesh_size": 3} for _ in range(count)]


def test_order_independent_lift_and_explicit_pi_ambiguity():
    a = m48r2._phase_lift([3.12, -3.12, 3.10]); b = m48r2._phase_lift([3.10, 3.12, -3.12])
    assert np.allclose(sorted(a["lifted_phases"]), sorted(b["lifted_phases"]))
    assert not a["ambiguous"] and m48r2._phase_lift([0.0, np.pi])["ambiguous"]


def test_density_uncertainty_is_not_branch_uncertainty():
    result = m48r2._scalar_stats([0.2, 0.4, 0.6], [1.0, 2.0, 4.0])
    assert result["uncertainty"] != result["phase_uncertainty"]


def test_authoritative_matrix_uses_partial_for_r128(monkeypatch):
    def read_dataset(_job, _root, dataset_id, _manifest, _schema, _count):
        if dataset_id == m48r2.m45r2.M41R3_DATASET_ID:
            return _rows(64) + _rows(96)
        if dataset_id == m48r2.m45r2.M44_DATASET_ID:
            return _rows(160) + _rows(192)
        if dataset_id == "6a0bd125fb2b4b640292ff8580d4812cbb1be8d4e1e383133060cf8139e2f533":
            return _rows(224)
        if dataset_id == m48r2.M47_DATASET_ID:
            return _rows(256)
        return []

    partial = _rows(128)
    monkeypatch.setattr(m48r2.m41r3, "_read_dataset", read_dataset)
    monkeypatch.setattr(m48r2.m41r3, "_read_partial", lambda _job, _root: partial)
    monkeypatch.setattr(m48r2.m41r3, "_centers", lambda _m18, _m39: {member: [float(index), float(index)] for index, member in enumerate(m48r2.MEMBERS)})
    matrix, _, _, _ = m48r2._read_matrix(object(), Path("."))
    assert {resolution: len(rows) for resolution, rows in matrix.items()} == {resolution: 36 for resolution in m48r2.RESOLUTIONS}
    assert sum(map(len, matrix.values())) == 252
    assert matrix[128] == partial


def test_transition_ledger_keeps_exact_withholding_reason():
    result = m48r2._transition({"x": {"fits": {"160-192-224": {"status": "NO_ASYMPTOTIC_MODEL", "reason": "ratio_at_or_below_p0_limit"}, "192-224-256": {"status": "VALID_POSITIVE_P"}}}})["x"]
    assert result["transition_class"] == "ENTERING_ASYMPTOTIC"
    assert result["withholding_reasons"]["160-192-224"] == "ratio_at_or_below_p0_limit"


def test_partition_is_all_w3_valid_not_majority():
    sequences = {"ok": {"fits": {"192-224-256": {"status": "VALID_POSITIVE_P"}}, "transition_class": "STABLE_LATE_ASYMPTOTIC"}, "bad": {"fits": {"192-224-256": {"status": "NO_ASYMPTOTIC_MODEL"}}, "transition_class": "PERSISTENT_NONASYMPTOTIC"}}
    result = m48r2._partition(sequences, list(sequences))
    assert result["all_w3_valid"] is False and result["failing_identities"] == ["bad"]


def test_localization_association_precedes_earliest_semantic_failure():
    good = {name: {"all_w3_valid": True} for name in ("frequency", "gap", "subspace", "berry")}
    assert m48r2._localize(good, {"unstable": True})[0] == "HIGH_RESOLUTION_ASSOCIATION_INSTABILITY"
    bad = dict(good); bad["gap"] = {"all_w3_valid": False}
    assert m48r2._localize(bad, {"unstable": False})[0] == "FREQUENCY_ASYMPTOTIC_GAP_NONASYMPTOTIC"


def test_result_contract_is_self_contained_and_solver_free():
    text = SOURCE.read_text(encoding="utf-8")
    assert m48r2.RESULT_SCHEMA == "mephc-berry-c3-consistency-m48r2-seven-resolution-mechanism-localization-v1"
    assert "m48_seven_resolution_mixed_family_mechanism_localization" not in text
    assert "m48r1_recover_seven_resolution_mechanism_localization" not in text
    assert "m42" not in text
    assert "R288" not in text
    assert json.dumps(m48r2._safe({"nan": float("nan")})).find("NAN") >= 0
