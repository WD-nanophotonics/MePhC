import json
from pathlib import Path

import pytest

from audit.infrastructure.campaign_runtime import (
    ArtifactValidationError,
    CampaignRuntimeError,
    CampaignIdentity,
    CampaignPreflightError,
    CampaignRuntime,
    CheckpointValidationError,
    ProcessReviewSchemaError,
    resolve_sibling_repo,
    run_worker_command,
    semantic_plan_fingerprint,
    validate_process_review,
)


def make_runtime(tmp_path, ids=("s0", "s1")):
    tmp_path.mkdir(parents=True, exist_ok=True)
    runner = tmp_path / "runner.py"
    contract = tmp_path / "contract.json"
    runner.write_text("runner-v1\n", encoding="utf-8")
    contract.write_text("{}\n", encoding="utf-8")
    identity = CampaignIdentity(
        execution_git_sha="a" * 40,
        runner_sha256=__import__("hashlib").sha256(runner.read_bytes()).hexdigest(),
        scientific_contract_sha256=__import__("hashlib").sha256(contract.read_bytes()).hexdigest(),
        plan_semantic_id=semantic_plan_fingerprint(
            rows(ids),
            estimator_id="TEST",
            semantic_domain_id="D",
            spacing_id="1/36",
        ),
        expected_sample_ids=tuple(ids),
        expected_sample_indices=tuple(range(len(ids))),
        semantic_estimator_id="TEST",
        semantic_domain_id="D",
        semantic_spacing_id="1/36",
    )
    runtime = CampaignRuntime(
        tmp_path / "campaign",
        identity,
        runner_path=runner,
        contract_path=contract,
        local_object_checker=lambda sha: sha == identity.execution_git_sha,
        remote_object_checker=lambda sha: sha == identity.execution_git_sha,
    )
    runtime.preflight(
        current_execution_sha=identity.execution_git_sha,
        dirty=False,
        current_plan_semantic_id=identity.plan_semantic_id,
    )
    return runtime, identity, runner, contract


def rows(ids=("s0", "s1")):
    return [
        {
            "sample_id": sample_id,
            "sample_index": index,
            "grid_index": [index, 0],
            "public_q": [index / 10, 0.2],
        }
        for index, sample_id in enumerate(ids)
    ]


def test_exact_identity_preflight_and_remote_gate(tmp_path):
    runtime, identity, runner, contract = make_runtime(tmp_path)
    assert runtime._preflight_report["status"] == "TEST_VERIFIER_ACCEPTED"
    assert runtime._preflight_report["worker_launch_authorized"]


@pytest.mark.parametrize("kwargs,code", [
    ({"current_execution_sha": "b" * 40}, "EXECUTION_GIT_SHA_MISMATCH"),
    ({"dirty": True}, "EXECUTION_SOURCE_DIRTY"),
    ({"current_plan_semantic_id": "wrong"}, "PLAN_SEMANTIC_ID_MISMATCH"),
])
def test_preflight_rejects_identity_and_delivery_mismatch(tmp_path, kwargs, code):
    runtime, identity, runner, contract = make_runtime(tmp_path)
    args = {
        "current_execution_sha": identity.execution_git_sha,
        "dirty": False,
        "current_plan_semantic_id": identity.plan_semantic_id,
    }
    args.update(kwargs)
    with pytest.raises(CampaignPreflightError, match=code):
        runtime.preflight(**args)


def test_preflight_rejects_runner_and_contract_hash_mismatch(tmp_path):
    runtime, identity, runner, contract = make_runtime(tmp_path)
    runner.write_text("changed\n", encoding="utf-8")
    with pytest.raises(CampaignPreflightError, match="RUNNER_SHA256_MISMATCH"):
        runtime.preflight(current_execution_sha=identity.execution_git_sha, dirty=False, current_plan_semantic_id=identity.plan_semantic_id)

    runtime, identity, runner, contract = make_runtime(tmp_path / "contract")
    contract.write_text("{changed}\n", encoding="utf-8")
    with pytest.raises(CampaignPreflightError, match="SCIENTIFIC_CONTRACT_SHA256_MISMATCH"):
        runtime.preflight(current_execution_sha=identity.execution_git_sha, dirty=False, current_plan_semantic_id=identity.plan_semantic_id)


def test_semantic_fingerprint_ignores_benign_float_serialization_but_not_topology():
    base = [{"sample_id": "s0", "grid_index": [1, 2], "fragment_index": 0, "triangle_index": 1, "public_q": [0.1, 0.2]}]
    benign = [{"sample_id": "s0", "grid_index": [1, 2], "fragment_index": 0, "triangle_index": 1, "public_q": [0.10000000000000001, 0.20000000000000001]}]
    changed = [{"sample_id": "s0", "grid_index": [2, 2], "fragment_index": 0, "triangle_index": 1, "public_q": [0.1, 0.2]}]
    assert semantic_plan_fingerprint(base, estimator_id="SOURCE", semantic_domain_id="D", spacing_id="1/36") == semantic_plan_fingerprint(benign, estimator_id="SOURCE", semantic_domain_id="D", spacing_id="1/36")
    assert semantic_plan_fingerprint(base, estimator_id="SOURCE", semantic_domain_id="D", spacing_id="1/36") != semantic_plan_fingerprint(changed, estimator_id="SOURCE", semantic_domain_id="D", spacing_id="1/36")


def test_successful_worker_atomic_publication_and_checkpoint(tmp_path):
    runtime, identity, runner, contract = make_runtime(tmp_path)
    result = runtime.run(rows(), lambda row: {"value": row["sample_id"]})
    assert result["status"] == "COMPLETE"
    assert len(list((runtime.root / "workers").glob("*.json"))) == 2
    checkpoint = json.loads(runtime.checkpoint_path.read_text(encoding="utf-8"))
    assert checkpoint["completed_sample_ids"] == ["s0", "s1"]
    assert checkpoint["generation"] == 2


def test_killed_worker_before_publication_does_not_count(tmp_path):
    runtime, identity, runner, contract = make_runtime(tmp_path, ids=("s0",))
    def killed(row):
        (runtime.root / "workers").mkdir(parents=True, exist_ok=True)
        (runtime.root / "workers" / "partial.tmp").write_text("{", encoding="utf-8")
        raise RuntimeError("simulated kill before publication")
    with pytest.raises(RuntimeError):
        runtime.run(rows(("s0",)), killed)
    assert not list((runtime.root / "workers").glob("*.json"))
    assert not runtime.checkpoint_path.exists()


def test_corrupt_and_stale_worker_artifacts_fail_closed(tmp_path):
    runtime, identity, runner, contract = make_runtime(tmp_path, ids=("s0",))
    runtime.workers.mkdir(parents=True, exist_ok=True)
    (runtime.workers / "stale.json").write_text(json.dumps({"sample_id": "old"}), encoding="utf-8")
    assert runtime.load_completed_artifacts(rows(("s0",))) == set()
    assert runtime.telemetry["rejected_stale_artifact_count"] == 1
    runtime._artifact_path("s0").write_text("{", encoding="utf-8")
    with pytest.raises(ArtifactValidationError, match="CORRUPT_WORKER_ARTIFACT"):
        runtime.load_completed_artifacts(rows(("s0",)))


def test_wrong_sample_and_duplicate_artifacts_fail_closed(tmp_path):
    runtime, identity, runner, contract = make_runtime(tmp_path, ids=("s0", "s1"))
    runtime.publish_worker_artifact(sample_id="s0", sample_index=0, result={"value": 1})
    with pytest.raises(ArtifactValidationError, match="DUPLICATE_SAMPLE"):
        runtime.publish_worker_artifact(sample_id="s0", sample_index=0, result={"value": 2})
    wrong = runtime._artifact_path("s1")
    wrong.write_text(json.dumps({
        "schema": runtime.ARTIFACT_SCHEMA,
        "execution_git_sha": identity.execution_git_sha,
        "runner_sha256": identity.runner_sha256,
        "scientific_contract_sha256": identity.scientific_contract_sha256,
        "plan_semantic_id": identity.plan_semantic_id,
        "sample_id": "s1",
        "sample_index": 0,
        "completion_status": "COMPLETE",
    }), encoding="utf-8")
    with pytest.raises(ArtifactValidationError, match="sample_index_MISMATCH"):
        runtime.load_completed_artifacts(rows())


def test_interrupted_resume_preserves_completed_samples(tmp_path):
    runtime, identity, runner, contract = make_runtime(tmp_path)
    calls = []
    def interrupted(row):
        calls.append(row["sample_id"])
        if row["sample_id"] == "s1":
            raise RuntimeError("interrupt")
        return {"value": row["sample_id"]}
    with pytest.raises(RuntimeError):
        runtime.run(rows(), interrupted)
    assert calls == ["s0", "s1"]
    runtime2 = CampaignRuntime(
        runtime.root,
        identity,
        runner_path=runner,
        contract_path=contract,
        local_object_checker=lambda sha: True,
        remote_object_checker=lambda sha: True,
    )
    runtime2.preflight(current_execution_sha=identity.execution_git_sha, dirty=False, current_plan_semantic_id=identity.plan_semantic_id)
    calls2 = []
    result = runtime2.run(rows(), lambda row: calls2.append(row["sample_id"]) or {"value": row["sample_id"]})
    assert calls2 == ["s1"]
    assert result["status"] == "COMPLETE"


def test_checkpoint_corruption_and_identity_mismatch_fail_closed(tmp_path):
    runtime, identity, runner, contract = make_runtime(tmp_path)
    runtime.write_checkpoint([])
    runtime.checkpoint_path.write_text("{", encoding="utf-8")
    with pytest.raises(CheckpointValidationError, match="CORRUPT_CHECKPOINT"):
        runtime.load_checkpoint()
    runtime.write_checkpoint([])
    payload = json.loads(runtime.checkpoint_path.read_text(encoding="utf-8"))
    payload["identity"]["execution_git_sha"] = "b" * 40
    runtime.checkpoint_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(CheckpointValidationError, match="CHECKPOINT_IDENTITY_MISMATCH"):
        runtime.load_checkpoint()


def test_path_resolution_never_creates_tmp_symlinks(tmp_path):
    repo = tmp_path / "MePhC"
    sibling = tmp_path / "SqrLatt"
    repo.mkdir()
    sibling.mkdir()
    assert resolve_sibling_repo(repo, "SqrLatt") == sibling
    configured = tmp_path / "configured"
    (configured / "SqrLatt").mkdir(parents=True)
    assert resolve_sibling_repo(repo, "SqrLatt", configured_root=configured) == configured / "SqrLatt"


def test_parent_runtime_has_no_mpb_import_or_cache():
    import ast
    import audit.infrastructure.campaign_runtime as runtime_module
    source = Path(runtime_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = [node.names[0].name for node in ast.walk(tree) if isinstance(node, ast.Import) and node.names]
    imported += [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not any("mpb" in name.lower() or "meep" in name.lower() for name in imported)
    assert not hasattr(runtime_module, "solver_cache")


def test_process_review_priority_schema_rejects_invalid_token():
    review = {"incidents": [{
        "incident_id": "REL-001", "phase": "x", "symptom": "x", "root_cause": "x", "occurrence_count": 1,
        "first_detected_when": "x", "recovery_or_workaround": "x", "code_or_workflow_change_required": True,
        "scientific_result_impact": "x", "provenance_impact": "x", "could_have_been_detected_earlier": True,
        "should_have_been_reported_earlier": True, "recurrence_risk": "high", "permanent_corrective": "x",
        "priority": "Require semantic/topology preflight", "pipeline_defect_candidate": True,
        "CORRECTIVE_STATUS": "OPEN", "CLOSURE_EVIDENCE": "none",
    }], "pipeline_health": "PIPELINE_REQUIRES_CORRECTIVE", "p0_items": [], "p1_items": ["REL-001"], "p2_items": []}
    with pytest.raises(ProcessReviewSchemaError, match="invalid priority"):
        validate_process_review(review)


def test_local_execution_object_missing_rejects_before_worker(tmp_path):
    runtime, identity, runner, contract = make_runtime(tmp_path)
    runtime.local_object_checker = lambda sha: False
    with pytest.raises(CampaignPreflightError, match="LOCAL_EXECUTION_OBJECT_MISSING"):
        runtime.preflight(current_execution_sha=identity.execution_git_sha, dirty=False, current_plan_semantic_id=identity.plan_semantic_id)


def test_worker_identity_mismatch_is_not_overwritten(tmp_path):
    runtime, identity, runner, contract = make_runtime(tmp_path, ids=("s0",))
    with pytest.raises(ArtifactValidationError, match="execution_git_sha_MISMATCH"):
        runtime.publish_worker_artifact(sample_id="s0", sample_index=0, result={"execution_git_sha": "b" * 40})


def test_bounded_injected_worker_command_requires_valid_json(tmp_path):
    value = run_worker_command(["/home/icy/miniconda3/envs/mp/bin/python", "-c", "import json; print(json.dumps({\"ok\": True}))"])
    assert value == {"ok": True}
    with pytest.raises(Exception, match="WORKER_COMMAND_FAILED"):
        run_worker_command(["/home/icy/miniconda3/envs/mp/bin/python", "-c", "raise SystemExit(3)"])



def test_coordinate_only_semantic_mutation_fails_before_worker(tmp_path):
    runtime, identity, runner, contract = make_runtime(tmp_path, ids=("s0",))
    changed = rows(("s0",))
    changed[0]["public_q"] = [0.3, 0.2]
    with pytest.raises(CampaignRuntimeError, match="PLAN_SEMANTIC_ID_MISMATCH"):
        runtime.run(changed, lambda row: pytest.fail("worker must not launch"))


def test_worker_coordinate_disagreement_fails_before_worker(tmp_path):
    runtime, identity, runner, contract = make_runtime(tmp_path, ids=("s0",))
    bad = rows(("s0",))
    bad[0]["worker_coordinate"] = [0.3, 0.2]
    with pytest.raises(CampaignRuntimeError, match="WORKER_COORDINATE_SEMANTIC_MISMATCH"):
        runtime.run(bad, lambda row: pytest.fail("worker must not launch"))


def test_duplicate_plan_id_and_index_fail_closed(tmp_path):
    runtime, identity, runner, contract = make_runtime(tmp_path)
    duplicate_id = rows()
    duplicate_id[1]["sample_id"] = duplicate_id[0]["sample_id"]
    with pytest.raises(CampaignRuntimeError, match="DUPLICATE_SAMPLE_ID"):
        runtime.run(duplicate_id, lambda row: {})
    duplicate_index = rows()
    duplicate_index[1]["sample_index"] = duplicate_index[0]["sample_index"]
    with pytest.raises(CampaignRuntimeError, match="DUPLICATE_SAMPLE_INDEX"):
        runtime.run(duplicate_index, lambda row: {})


def test_remote_caller_true_cannot_bypass_checker(tmp_path):
    runtime, identity, runner, contract = make_runtime(tmp_path)
    runtime.remote_object_checker = lambda sha: False
    with pytest.raises(CampaignPreflightError, match="REMOTE_EXECUTION_OBJECT_MISSING"):
        runtime.preflight(
            current_execution_sha=identity.execution_git_sha,
            dirty=False,
            current_plan_semantic_id=identity.plan_semantic_id,
            remote_execution_object_verified=True,
        )


def test_checkpoint_generation_is_consistent_across_reload_and_resume(tmp_path):
    runtime, identity, runner, contract = make_runtime(tmp_path, ids=("s0",))
    runtime.write_checkpoint([])
    payload = json.loads(runtime.checkpoint_path.read_text(encoding="utf-8"))
    assert payload["generation"] == 1
    assert payload["telemetry"]["checkpoint_generation_count"] == 1
    runtime2 = CampaignRuntime(
        runtime.root,
        identity,
        runner_path=runner,
        contract_path=contract,
        local_object_checker=lambda sha: True,
        remote_object_checker=lambda sha: True,
    )
    runtime2.preflight(
        current_execution_sha=identity.execution_git_sha,
        dirty=False,
        current_plan_semantic_id=identity.plan_semantic_id,
    )
    assert runtime2.load_checkpoint() == set()
    runtime2.write_checkpoint([])
    payload = json.loads(runtime2.checkpoint_path.read_text(encoding="utf-8"))
    assert payload["generation"] == 2
    assert payload["telemetry"]["checkpoint_generation_count"] == 2


def test_checkpoint_generation_disagreement_fails_closed(tmp_path):
    runtime, identity, runner, contract = make_runtime(tmp_path, ids=("s0",))
    runtime.write_checkpoint([])
    payload = json.loads(runtime.checkpoint_path.read_text(encoding="utf-8"))
    payload["telemetry"]["checkpoint_generation_count"] = 0
    runtime.checkpoint_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(CheckpointValidationError, match="CHECKPOINT_GENERATION_INCONSISTENT"):
        runtime.load_checkpoint()


def test_production_mode_requires_repository_path():
    with pytest.raises(CampaignRuntimeError, match="PRODUCTION_REPOSITORY_REQUIRED"):
        CampaignRuntime(
            Path("."),
            CampaignIdentity("a" * 40, "b" * 64, "c" * 64, "plan", ("s0",)),
            runner_path=Path("runner"),
            contract_path=Path("contract"),
            production_mode=True,
        )
