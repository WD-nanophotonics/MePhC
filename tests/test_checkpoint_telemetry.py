import hashlib
import json

import pytest

from audit.infrastructure.campaign_runtime import (
    CampaignIdentity,
    CampaignRuntime,
    CheckpointValidationError,
    semantic_plan_fingerprint,
)


def _rows(ids):
    return [{"sample_id": sid, "sample_index": i, "grid_index": [i, 0], "public_q": [i / 10, 0.2]}
            for i, sid in enumerate(ids)]


def _runtime(tmp_path, ids):
    runner = tmp_path / "runner.py"
    contract = tmp_path / "contract.json"
    runner.write_text("runner\n", encoding="utf-8")
    contract.write_text("{}\n", encoding="utf-8")
    rows = _rows(ids)
    identity = CampaignIdentity(
        execution_git_sha="a" * 40,
        runner_sha256=hashlib.sha256(runner.read_bytes()).hexdigest(),
        scientific_contract_sha256=hashlib.sha256(contract.read_bytes()).hexdigest(),
        plan_semantic_id=semantic_plan_fingerprint(rows, estimator_id="T", semantic_domain_id="D", spacing_id="S"),
        expected_sample_ids=tuple(ids), expected_sample_indices=tuple(range(len(ids))),
        semantic_estimator_id="T", semantic_domain_id="D", semantic_spacing_id="S",
    )
    runtime = CampaignRuntime(tmp_path / "campaign", identity, runner_path=runner, contract_path=contract,
                              local_object_checker=lambda sha: True, remote_object_checker=lambda sha: True)
    runtime.preflight(current_execution_sha=identity.execution_git_sha, dirty=False,
                      current_plan_semantic_id=identity.plan_semantic_id)
    return runtime, rows, identity, runner, contract


@pytest.mark.parametrize("count", [0, 1, 3])
def test_checkpoint_completed_count_matches_completion_set(tmp_path, count):
    ids = tuple(f"s{i}" for i in range(count))
    runtime, rows, *_ = _runtime(tmp_path, ids)
    for row in rows:
        runtime.publish_worker_artifact(sample_id=row["sample_id"], sample_index=row["sample_index"], result={"value": row["sample_id"]})
    runtime.write_checkpoint(ids)
    payload = json.loads(runtime.checkpoint_path.read_text(encoding="utf-8"))
    assert payload["telemetry"]["completed_sample_count"] == count
    assert payload["telemetry"]["completed_sample_count"] == len(payload["completed_sample_ids"]) == len(payload["completed_artifacts"])


def test_checkpoint_completed_count_tamper_fails_closed(tmp_path):
    runtime, rows, *_ = _runtime(tmp_path, ("s0", "s1", "s2"))
    runtime.run(rows, lambda row: {"value": row["sample_id"]})
    payload = json.loads(runtime.checkpoint_path.read_text(encoding="utf-8"))
    payload["telemetry"]["completed_sample_count"] = 0
    runtime.checkpoint_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(CheckpointValidationError, match="CHECKPOINT_COMPLETED_COUNT_INCONSISTENT"):
        runtime.load_checkpoint()


def test_checkpoint_completed_count_survives_restart(tmp_path):
    runtime, rows, identity, runner, contract = _runtime(tmp_path, ("s0", "s1", "s2"))
    def stop_after_first(row):
        if row["sample_id"] != "s0":
            raise RuntimeError("stop")
        return {"value": row["sample_id"]}
    with pytest.raises(RuntimeError, match="stop"):
        runtime.run(rows, stop_after_first)
    resumed = CampaignRuntime(runtime.root, identity, runner_path=runner, contract_path=contract,
                              local_object_checker=lambda sha: True, remote_object_checker=lambda sha: True)
    resumed.preflight(current_execution_sha=identity.execution_git_sha, dirty=False,
                      current_plan_semantic_id=identity.plan_semantic_id)
    assert resumed.load_checkpoint() == {"s0"}
    assert resumed.telemetry["completed_sample_count"] == 1


def test_orphan_artifact_adoption_writes_correct_count(tmp_path):
    runtime, rows, identity, runner, contract = _runtime(tmp_path, ("s0", "s1", "s2"))
    runtime.publish_worker_artifact(sample_id="s0", sample_index=0, result={"value": "orphan"})
    resumed = CampaignRuntime(runtime.root, identity, runner_path=runner, contract_path=contract,
                              local_object_checker=lambda sha: True, remote_object_checker=lambda sha: True)
    resumed.preflight(current_execution_sha=identity.execution_git_sha, dirty=False,
                      current_plan_semantic_id=identity.plan_semantic_id)
    resumed.run(rows, lambda row: pytest.fail("adopted artifact must not be recomputed") if row["sample_id"] == "s0" else {"value": row["sample_id"]})
    payload = json.loads(resumed.checkpoint_path.read_text(encoding="utf-8"))
    assert payload["telemetry"]["completed_sample_count"] == 3
