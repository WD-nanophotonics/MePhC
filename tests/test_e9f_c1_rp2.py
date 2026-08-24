from __future__ import annotations
import subprocess, sys, tempfile
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from audit.e9f import run_e9f_c1_rp2 as rp2


def payload(row):
    level = {"status": "DIAGNOSTIC_REPORTED", "value": 1.0}
    return {"schema": "trilatt_e9f_c1_rp2_worker_v1", "work_order_id": rp2.WORK_ORDER, "phase": rp2.PHASE, "worker_id": row["sample_id"], "source_sample_id": row["source_sample_id"], "source_sample_index": row["source_sample_index"], "sample_index": row["sample_index"], "resolution": row["resolution"], "authoritative_coordinate": row["authoritative_coordinate"], "worker_coordinate": row["authoritative_coordinate"], "matrix_entry_count": 2, "diagnostic_only": True, "reducer_admissible": False, "policy_sample_ids_derived": True, "stencils": {s: {"stencil": s, "DIAGNOSTIC_ONLY": True, "REDUCER_ADMISSIBLE": False, "L0": level, "L1": {"2": level, "3": level}, "L2": level, "L3": level} for s in rp2.STENCILS}}


def test_policy_hash_binding_and_exact_matrix_are_derived_from_contract():
    rows = rp2.build_plan(ROOT)
    assert len(rows) == 12 and {row["resolution"] for row in rows} == {64, 96}
    assert len(rp2.matrix_entry_keys()) == 24
    execution = rp2.load_execution_contract(ROOT)
    assert execution["policy_contract"]["file_sha256"] == rp2.sha256_file(ROOT / rp2.POLICY_REL)


def test_wrong_worker_identity_and_missing_level_fail_closed():
    row = rp2.build_plan(ROOT)[0]
    with pytest.raises(rp2.CampaignRuntimeError, match="MISMATCH"):
        rp2.validate_worker_identity(row, worker_id=row["sample_id"], resolution=128, coordinate=row["authoritative_coordinate"])
    value = payload(row)
    del value["stencils"]["1/72"]["L3"]
    with pytest.raises(rp2.CampaignRuntimeError, match="COVERAGE"):
        rp2.validate_worker_payload(value, row)


def test_structured_unavailable_and_l3_formula():
    result = rp2._l3({"wilson_phase_wrapped": 0.4}, {"wilson_phase_wrapped": -0.2}, {"rank2_wilson_determinant_phase": 0.1})
    assert result["status"] == "DIAGNOSTIC_REPORTED" and result["metric_radians"] == pytest.approx(0.1)
    assert rp2._unavailable("ambiguous")["status"] == "NOT_AVAILABLE_WITH_REASON"


def test_parent_import_is_solver_free():
    code = "import sys; import audit.e9f.run_e9f_c1_rp2; assert not any(x == 'meep' or x.startswith('meep.') or x == 'mpb' or x.startswith('mpb.') for x in sys.modules)"
    subprocess.run([sys.executable, "-c", code], cwd=ROOT, check=True)


def test_reaped_fake_child_has_no_orphan_and_returns_json():
    value, measurement = rp2.run_reaped_child([sys.executable, "-c", "import json; print(json.dumps({'fake_worker': True}))"], "fake-worker", timeout_seconds=10)
    assert value == {"fake_worker": True} and measurement["direct_pid_gone"] and measurement["orphan_count"] == 0


def test_campaign_checkpoint_resume_binds_artifact_hashes():
    from audit.infrastructure.campaign_runtime import CampaignIdentity, CampaignRuntime, semantic_plan_fingerprint
    rows = rp2.build_plan(ROOT)[:2]
    runner_path = Path(__file__)
    contract_path = ROOT / rp2.CONTRACT_REL
    identity = CampaignIdentity("fake-execution", rp2.sha256_file(runner_path), rp2.sha256_file(contract_path), semantic_plan_fingerprint(rows, estimator_id="x", semantic_domain_id="y", spacing_id="z"), tuple(row["sample_id"] for row in rows), expected_sample_indices=tuple(row["sample_index"] for row in rows), semantic_estimator_id="x", semantic_domain_id="y", semantic_spacing_id="z")
    with tempfile.TemporaryDirectory() as value:
        runtime = CampaignRuntime(Path(value), identity, runner_path=runner_path, contract_path=contract_path, production_mode=False, local_object_checker=lambda _: True, remote_object_checker=lambda _: True)
        runtime.preflight(current_execution_sha="fake-execution", dirty=False, current_plan_semantic_id=identity.plan_semantic_id, plan_rows=rows)
        calls = []
        worker = lambda row: calls.append(row["sample_id"]) or {"value": row["sample_id"]}
        assert runtime.run(rows, worker)["status"] == "COMPLETE" and len(calls) == 2
        resumed = CampaignRuntime(Path(value), identity, runner_path=runner_path, contract_path=contract_path, production_mode=False, local_object_checker=lambda _: True, remote_object_checker=lambda _: True)
        resumed.preflight(current_execution_sha="fake-execution", dirty=False, current_plan_semantic_id=identity.plan_semantic_id, plan_rows=rows)
        calls.clear()
        assert resumed.run(rows, worker)["status"] == "COMPLETE" and calls == []
