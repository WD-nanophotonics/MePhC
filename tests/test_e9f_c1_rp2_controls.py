from __future__ import annotations
from pathlib import Path
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from audit.e9f import run_e9f_c1_rp2 as rp2


def test_exact_six_ids_and_two_resolutions_are_policy_derived():
    policy = rp2.load_execution_contract(ROOT)
    rows = rp2.build_plan(ROOT)
    expected = {
        "fr=0;grid_i=-34;grid_j=-17;estimator=SOURCE_GRID",
        "fr=0;grid_i=-34;grid_j=-16;estimator=SOURCE_GRID",
        "fr=0;grid_i=-34;grid_j=16;estimator=SOURCE_GRID",
        "fr=0;grid_i=-34;grid_j=17;estimator=SOURCE_GRID",
        "fr=0;grid_i=-5;grid_j=0;estimator=SOURCE_GRID",
        "fr=0;grid_i=-4;grid_j=0;estimator=SOURCE_GRID",
    }
    assert policy["matrix"]["source_sample_count"] == 6
    assert {row["source_sample_id"] for row in rows} == expected
    assert {row["resolution"] for row in rows} == {64, 96}
    assert {row["resolution"] for row in rows} <= set(rp2.RESOLUTIONS)


def test_wrong_sample_and_stencil_are_rejected():
    row = rp2.build_plan(ROOT)[0]
    with pytest.raises(rp2.CampaignRuntimeError):
        rp2.validate_worker_identity({**row, "sample_id": "wrong"}, worker_id=row["sample_id"], resolution=row["resolution"], coordinate=row["authoritative_coordinate"])
    from audit.e9f.run_e9f_c1_rp2 import validate_worker_payload
    level = {"status": "DIAGNOSTIC_REPORTED"}
    value = {"schema": "trilatt_e9f_c1_rp2_worker_v1", "work_order_id": rp2.WORK_ORDER, "phase": rp2.PHASE, "worker_id": row["sample_id"], "source_sample_id": row["source_sample_id"], "source_sample_index": row["source_sample_index"], "sample_index": row["sample_index"], "resolution": row["resolution"], "authoritative_coordinate": row["authoritative_coordinate"], "worker_coordinate": row["authoritative_coordinate"], "matrix_entry_count": 2, "diagnostic_only": True, "reducer_admissible": False, "policy_sample_ids_derived": True, "stencils": {s: {"stencil": "wrong" if s == "1/72" else s, "DIAGNOSTIC_ONLY": True, "REDUCER_ADMISSIBLE": False, "L0": level, "L1": {"2": level, "3": level}, "L2": level, "L3": level} for s in rp2.STENCILS}}
    with pytest.raises(rp2.CampaignRuntimeError, match="ENTRY_SCHEMA"):
        validate_worker_payload(value, row)


def test_l0_schema_does_not_emit_a_qualification_decision():
    result = rp2._impl._l0(type("Snapshot", (), {"frequencies": (1.0, 2.0, 2.1, 3.0)})())
    assert result["status"] == "DIAGNOSTIC_REPORTED"
    assert result["qualification_decision"] is False
    assert result["internal_gap_sign"] == "POSITIVE"
