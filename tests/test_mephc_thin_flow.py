from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


def load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


flow = load("mephc_thin_flow_tests", "tools/mephc-flow/mephc_flow.py")
science = load("mephc_thin_science_tests", "tools/mephc-flow/scientific_job.py")


def paths(tmp_path: Path):
    return flow.Paths(control=tmp_path / "repo", state=tmp_path / "flow",
                      science_state=tmp_path / "science", outbox=tmp_path / "outbox",
                      legacy_state=tmp_path / "legacy", courier=tmp_path / "courier.cmd")


def contract(**overrides):
    value = {
        "schema": "mephc-science-work-order-v1", "kind": "SCIENCE",
        "work_order_id": "MEPHC-THIN-TEST-00000001", "source_commit": "a" * 40,
        "action": "acquire", "project": ".", "entrypoint": "audit/test_entry.py",
        "inputs": {"tests": ["tests/test_mephc_thin_flow.py"]},
        "budgets": {"native_invocations": 1, "provider_requests": 1, "solver_executions": 1},
        "required_capabilities": ["exact_checkout", "sandbox_publication", "native_execution"],
        "allowed_writes": ["audit/test_entry.py"],
        "expected_output": {"dataset_schema": "dataset-v1", "result_schema": "result-v1"},
        "acceptance_criteria": [], "forbidden": ["main_promotion"],
    }
    value.update(overrides)
    return science.validate_contract(value)


def test_public_cli_is_only_four_commands():
    parser = flow.parser()
    for command in ("status", "resume", "execute", "closeout"):
        assert parser.parse_args([command]).command == command
    for retired in ("science-preflight", "science-acquire", "run-native", "closeout-blocked",
                    "supervision-status", "courier-reconcile"):
        with pytest.raises(SystemExit):
            parser.parse_args([retired])

    selected = parser.parse_args([
        "closeout", "--task-difficulty", "challenge",
        "--instruction-level", "manual_book", "--report-policy", "milestone",
    ])
    assert (selected.task_difficulty, selected.instruction_level, selected.report_policy) == (
        "challenge", "manual_book", "milestone")


def test_contract_parser_repairs_only_one_missing_final_root_brace():
    raw = {"work_order_id": "MEPHC-THIN-TEST-BRACE", "inputs": {"goal_id": "GOAL"}}
    payload = json.dumps(raw, separators=(",", ":"))
    repaired = flow.contract_from_text("WORK_ORDER_CONTRACT_JSON=" + payload[:-1])
    assert repaired == raw
    with pytest.raises(flow.FlowError, match="WORK_ORDER_MACHINE_CONTRACT_REQUIRED"):
        flow.contract_from_text("WORK_ORDER_CONTRACT_JSON=" + payload[:-2])


def test_closeout_launcher_is_zero_argument_and_fixed():
    launcher = (ROOT / "mephc-closeout.cmd").read_text(encoding="utf-8").lower()
    assert 'if not "%~1"==""' in launcher
    assert 'mephc-flow.cmd" closeout' in launcher
    for forbidden in ("%*", "courier-reconcile", "message-file", "browser", "chrome"):
        assert forbidden not in launcher


def test_agents_protocol_prefers_self_repair_before_fixed_supervisor_escalation():
    policy = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    required = (
        "HARD_BLOCKED      -> bounded self-repair, then supervisor escalation",
        "01a04136-7e60-75c3-88cf-156581a3733e",
        "01a0480e-b79d-75c3-ac80-5db601b32d67",
        "send_message_to_thread",
        "ESCALATION_ID=MEPHC-ESCALATION:<work-order-id>:<failure-code>",
        "ACTUAL_COUNTS=<native/provider/solver/dataset>",
        "UNCERTAIN_SIDE_EFFECT=<true|false>",
        "Retry a definite task-message transport failure once",
        "make one convergent framework repair",
        "never create or fork another worker",
        "allowed_writes` is advisory",
        "Missing or ambiguous Native authorization means",
        "Never escalate while the flow reports",
        "missing contract-declared file",
        "side_effect_state=UNKNOWN",
        "LOCAL_SUPERVISOR_REQUIRED=true",
        "Do not close out again",
    )
    assert all(item in policy for item in required)


def test_agents_require_supervisor_handoff_before_every_idle_transition():
    policy = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "Before ending any Luna turn or becoming idle for any reason" in policy
    assert "MEPHC-IDLE-HANDOFF:<work-order-id-or-null>:<state>" in policy
    assert "The supervisor decides whether stopping is legitimate" in policy
    assert "`TERMINATED` is only valid after that approval" in policy
    for field in (
        "GOAL_OUTCOME", "COMPLETION_EVIDENCE", "ATTEMPTS_COMPLETED",
        "UNRESOLVED_QUESTIONS", "ALTERNATIVE_EXPLANATIONS",
        "CHEAPEST_NEXT_TEST", "COUNTEREVIDENCE_SEARCH",
        "WHY_STOP_IS_SUFFICIENT",
    ):
        assert field in policy
    assert "independently challenge the proposed termination" in policy
    assert "untested convention, representation, gauge, coordinate transform" in policy
    assert "Project -> Goal -> Milestone/Branch -> Work\nOrder -> Job/Run" in policy
    assert "HARD_BLOCKED / TERMINATION_REVIEW_REQUIRED" in policy
    assert "Goal closure never terminates the" in policy


def test_ready_without_job_authoritatively_means_not_started(monkeypatch, tmp_path: Path):
    scope = paths(tmp_path)
    monkeypatch.setattr(flow, "source", lambda _: {"head": "a" * 40, "dirty": False})
    monkeypatch.setattr(flow, "active_order", lambda _: {"work_order_id": "MEPHC-THIN-TEST-READY"})
    monkeypatch.setattr(flow, "request_for_work_order", lambda *_: None)
    monkeypatch.setattr(flow, "current_job", lambda *_: None)
    result = flow.state_view(scope)
    assert result["state"] == "READY"
    assert result["safe_next"] == "execute"
    assert result["side_effect_state"] == "NOT_STARTED"
    assert result["execute_reentry_safe"] is True
    assert result["dispatch_reached"] is False


def test_tests_failed_is_local_ready_not_hard_blocked(monkeypatch, tmp_path: Path, capsys):
    scope = paths(tmp_path)
    monkeypatch.setattr(flow, "execute", lambda _: (_ for _ in ()).throw(
        flow.FlowError("TESTS_FAILED", "missing contract test")))
    monkeypatch.setattr(flow, "state_view", lambda _: {
        "schema": "mephc-thin-flow-status-v1", "state": "READY", "safe_next": "execute",
        "work_order_id": "MEPHC-THIN-TEST-READY", "job": None,
        "side_effect_state": "NOT_STARTED", "execute_reentry_safe": True,
    })
    assert flow.main(["execute"], scope) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["state"] == "READY"
    assert result["error_code"] == "TESTS_FAILED"
    assert result["failure_class"] == "LOCAL_IMPLEMENTATION_OR_TRANSIENT"
    assert result["native_started"] is False


@pytest.mark.parametrize(
    ("missing", "code"),
    [("entrypoint", "ENTRYPOINT_IMPLEMENTATION_REQUIRED"),
     ("test", "TEST_IMPLEMENTATION_REQUIRED")],
)
def test_missing_local_implementation_stays_ready_before_publish(monkeypatch, tmp_path: Path,
                                                                 missing: str, code: str):
    scope = paths(tmp_path)
    scope.control.mkdir(parents=True)
    value = contract()
    if missing != "entrypoint":
        entrypoint = scope.control / value["entrypoint"]
        entrypoint.parent.mkdir(parents=True)
        entrypoint.write_text("pass\n", encoding="utf-8")
    if missing != "test":
        test = scope.control / value["inputs"]["tests"][0]
        test.parent.mkdir(parents=True, exist_ok=True)
        test.write_text("def test_ok(): assert True\n", encoding="utf-8")
    monkeypatch.setattr(flow, "state_view", lambda _: {"state": "READY"})
    monkeypatch.setattr(flow, "active_contract", lambda _: ({"work_order_id": value["work_order_id"]}, value))
    monkeypatch.setattr(flow, "publish", lambda *_: pytest.fail("must fail before publication"))
    with pytest.raises(flow.FlowError, match=code):
        flow.execute(scope)


def test_infrastructure_requires_declared_artifacts_and_runs_declared_test(monkeypatch, tmp_path: Path):
    scope = paths(tmp_path)
    scope.control.mkdir(parents=True)
    value = contract(
        kind="INFRASTRUCTURE", action="infrastructure", entrypoint=None,
        budgets={"native_invocations": 0, "provider_requests": 0, "solver_executions": 0},
        inputs={},
        allowed_writes=["audit/result.json", "tests/test_declared_result.py"],
        expected_output={"dataset_schema": None, "result_schema": "infra-result-v1"},
    )
    assert flow.test_paths(value) == ["tests/test_declared_result.py"]
    with pytest.raises(flow.FlowError, match="TEST_IMPLEMENTATION_REQUIRED"):
        flow.require_local_implementation(scope, value)
    test = scope.control / "tests/test_declared_result.py"
    test.parent.mkdir(parents=True)
    test.write_text("def test_ok(): assert True\n", encoding="utf-8")
    with pytest.raises(flow.FlowError, match="ARTIFACT_IMPLEMENTATION_REQUIRED: audit/result.json"):
        flow.require_local_implementation(scope, value)
    artifact = scope.control / "audit/result.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("{}\n", encoding="utf-8")
    flow.require_local_implementation(scope, value)


def test_oversized_terminal_result_is_reconciled_without_execution(monkeypatch, tmp_path: Path):
    scope = paths(tmp_path)
    scope.control.mkdir(parents=True)
    helper_source = ROOT / "tools" / "mephc-flow" / "wsl_native_exec.py"
    helper_target = scope.control / "tools" / "mephc-flow" / "wsl_native_exec.py"
    helper_target.parent.mkdir(parents=True)
    helper_target.write_bytes(helper_source.read_bytes())
    job_id = "MEPHC-SCIENCE-" + "a" * 24
    run_id = "MEPHC-NATIVE-" + "b" * 24
    job = {"job_id": job_id, "native_run_id": run_id, "state": "failed",
           "failure_code": "RESULT_SUMMARY_OVERSIZED", "actual_native_invocation_count": 1}
    run_root = scope.state / "native-runs"
    run_root.mkdir(parents=True)
    (run_root / f"{run_id}.json").write_text(json.dumps({
        "run_id": run_id, "state": "failed", "result_error": "RESULT_SUMMARY_OVERSIZED",
        "expected_output": {"result_schema": "thin-result-v1"},
        "actual_native_invocation_count": 1,
    }), encoding="utf-8")
    result_path = scope.science_state / "results" / f"{job_id}.json"
    result_path.parent.mkdir(parents=True)
    result_path.write_text(json.dumps({
        "schema": "thin-result-v1", "status": "PASS", "values": list(range(20000)),
    }), encoding="utf-8")
    repaired = flow.reconcile_oversized_result(scope, job)
    assert repaired["state"] == "succeeded"
    assert repaired["reconciled_without_execution"] is True
    assert repaired["actual_native_invocation_count"] == 1
    assert repaired["result_summary"]["status"] == "PASS"
    assert repaired["result_artifact"]["sha256"]


def test_main_identity_failure_remains_hard_blocked(monkeypatch, tmp_path: Path, capsys):
    scope = paths(tmp_path)
    monkeypatch.setattr(flow, "execute", lambda _: (_ for _ in ()).throw(
        flow.FlowError("ORIGIN_MAIN_MOVED")))
    assert flow.main(["execute"], scope) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["state"] == "HARD_BLOCKED"
    assert result["side_effect_state"] == "UNKNOWN"


@pytest.mark.parametrize(
    "chat_error",
    [
        "Connection interrupted. Waiting for the complete answer",
        "This content can’t be shown\nWe’re especially careful with cybersecurity requests.",
    ],
)
def test_chat_error_response_reenters_same_request_capture(tmp_path: Path, chat_error: str):
    directory = tmp_path / "MEPHC-FLOW-test"
    directory.mkdir()
    (directory / "request.json").write_text(
        json.dumps({"request_id": directory.name}), encoding="utf-8"
    )
    (directory / "receipt.json").write_text(
        json.dumps({"state": "response_received"}), encoding="utf-8"
    )
    (directory / "events.jsonl").write_text(
        '{"event":"request_submitted"}\n', encoding="utf-8"
    )
    (directory / "response.txt").write_text(chat_error, encoding="utf-8")
    summary = flow.request_summary(directory)
    assert summary["submission_count"] == 1
    assert summary["response_received"] is False
    assert summary["invalid_response_capture"] is True
    assert summary["recovery_action"] == "read"


def test_valid_successor_response_is_accepted(tmp_path: Path):
    directory = tmp_path / "MEPHC-FLOW-test"
    directory.mkdir()
    (directory / "request.json").write_text(
        json.dumps({"request_id": directory.name}), encoding="utf-8"
    )
    (directory / "receipt.json").write_text(
        json.dumps({"state": "response_received"}), encoding="utf-8"
    )
    (directory / "events.jsonl").write_text(
        '{"event":"request_submitted"}\n', encoding="utf-8"
    )
    (directory / "response.txt").write_text(
        "NEXT_WORK_ORDER_ID=MEPHC-THIN-NEXT-00000001\n"
        "WORK_ORDER_CONTRACT_JSON={}\n",
        encoding="utf-8",
    )
    summary = flow.request_summary(directory)
    assert summary["response_received"] is True
    assert summary["invalid_response_capture"] is False
    assert summary["recovery_action"] == "none"


def test_successor_id_can_be_inferred_from_machine_contract_without_directive():
    successor = "MEPHC-THIN-NEXT-00000009"
    body = "WORK_ORDER_CONTRACT_JSON=" + json.dumps({
        "work_order_id": successor, "source_commit": "a" * 40,
    })
    assert flow.successor_from_text(body, "MEPHC-THIN-PRIOR-00000008") == successor


def test_request_summary_counts_retries_per_registered_target_generation(tmp_path: Path):
    directory = tmp_path / "MEPHC-FLOW-test"
    directory.mkdir()
    (directory / "request.json").write_text(
        json.dumps({"request_id": directory.name}), encoding="utf-8"
    )
    (directory / "events.jsonl").write_text(
        '{"event":"request_submitted"}\n'
        '{"event":"request_submitted"}\n'
        '{"event":"target_rollover_authorized"}\n'
        '{"event":"request_submitted"}\n',
        encoding="utf-8",
    )
    summary = flow.request_summary(directory)
    assert summary["submission_count"] == 1
    assert summary["total_submission_count"] == 3
    assert summary["recovery_action"] == "read"


def test_awaiting_and_terminated_are_distinct(monkeypatch, tmp_path: Path):
    scope = paths(tmp_path)
    monkeypatch.setattr(flow, "source", lambda _: {"branch": "sandbox", "head": "a" * 40,
                                                     "origin_main": flow.EXPECTED_MAIN,
                                                     "origin_sandbox": "a" * 40, "dirty": False})
    monkeypatch.setattr(flow, "ledger", lambda _: {})
    assert flow.state_view(scope)["state"] == "AWAITING_WORK_ORDER"
    monkeypatch.setattr(flow, "ledger", lambda _: {"workflow_state": "terminated"})
    assert flow.state_view(scope)["state"] == "TERMINATED"


def test_production_coordinator_has_no_historical_special_cases():
    source = (ROOT / "tools/mephc-flow/mephc_flow.py").read_text(encoding="utf-8").lower()
    assert len(source.splitlines()) <= 1200
    for token in ("d9r1", "reconcile_r8", "supervision_batch_review_required", "closeout_blocked"):
        assert token not in source


@pytest.mark.parametrize("difficulty", ["normal", "hard", "challenge"])
@pytest.mark.parametrize("detail", ["normal", "detailed", "manual_book"])
def test_query_preference_explicit_matrix_overrides_contract(difficulty: str, detail: str):
    value = contract(query_preferences={
        "task_difficulty": "normal", "instruction_level": "normal",
        "report_policy": "final-only",
    })
    selected = flow.adaptive_query_preferences(value, {
        "work_order_id": value["work_order_id"], "action": "acquire", "state": "succeeded",
    }, {
        "task_difficulty": difficulty, "instruction_level": detail,
        "report_policy": "milestone",
    })
    assert selected == {
        "task_difficulty": difficulty, "instruction_level": detail,
        "report_policy": "milestone",
    }


def test_query_preference_precedence_and_adaptive_modes():
    ordinary = {"work_order_id": "MEPHC-SCIENCE-P1", "action": "acquire", "state": "succeeded"}
    assert flow.adaptive_query_preferences(None, ordinary, {}) == {
        "task_difficulty": "hard", "instruction_level": "detailed",
        "report_policy": "milestone",
    }
    corrective = {"work_order_id": "MEPHC-P2-RECERTIFICATION", "action": "corrective",
                  "state": "succeeded"}
    assert flow.adaptive_query_preferences(None, corrective, {}) == {
        "task_difficulty": "challenge", "instruction_level": "manual_book",
        "report_policy": "milestone",
    }
    ambiguous = {"work_order_id": "MEPHC-SCIENCE-P3", "action": "acquire", "state": "blocked",
                 "actual_native_invocation_count": 0}
    assert flow.adaptive_query_preferences(None, ambiguous, {})["instruction_level"] == "manual_book"
    declared = contract(query_preferences={
        "task_difficulty": "normal", "instruction_level": "normal",
        "report_policy": "per-work-order",
    })
    assert flow.adaptive_query_preferences(declared, ordinary, {}) == declared["query_preferences"]
    selected = flow.adaptive_query_preferences(declared, ordinary, {
        "task_difficulty": "adaptive", "instruction_level": "detailed",
        "report_policy": "final-only",
    })
    assert selected == {"task_difficulty": "normal", "instruction_level": "detailed",
                        "report_policy": "final-only"}


def test_query_preferences_do_not_change_fixed_request_or_report_body(monkeypatch, tmp_path: Path):
    scope = paths(tmp_path)
    order = {"work_order_id": "MEPHC-THIN-PREFERENCE-0001"}
    job = {"work_order_id": order["work_order_id"], "action": "acquire", "state": "succeeded",
           "source_commit": "a" * 40, "job_id": "MEPHC-SCIENCE-PREFERENCE",
           "changed_files": ["audit/result.json"], "tests": ["tests/test_result.py"]}
    monkeypatch.setattr(flow, "tracked_artifact_sha256", lambda *_: "b" * 64)
    first = flow.canonical_report(scope, order, job, {
        "task_difficulty": "normal", "instruction_level": "normal",
        "report_policy": "per-work-order",
    })
    second = flow.canonical_report(scope, order, job, {
        "task_difficulty": "challenge", "instruction_level": "manual_book",
        "report_policy": "milestone",
    })
    assert first["request_id"] == second["request_id"]
    assert first["message_sha256"] == second["message_sha256"]
    text = first["message"].decode()
    assert "CHANGED_FILES=audit/result.json" in text
    assert f"ARTIFACT_SHA256=audit/result.json:{'b' * 64}" in text
    assert "TESTS=tests/test_result.py" in text
    assert "TEST_RETURN_CODE=0" in text


def test_report_names_project_goal_work_order_and_job_scopes(monkeypatch, tmp_path: Path):
    scope = paths(tmp_path)
    order = {"work_order_id": "MEPHC-THIN-SCOPE-0001"}
    job = {"state": "succeeded", "source_commit": "a" * 40, "job_id": "MEPHC-JOB-SCOPE",
           "result_summary": {"goal_completion_status": "ACTIVE",
                              "next_science_decision": "STOP_ONE_CAUSAL_BRANCH"}}
    report = flow.canonical_report(scope, order, job, {
        "task_difficulty": "hard", "instruction_level": "detailed",
        "report_policy": "milestone",
    }, contract(inputs={"goal_id": "MEPHC-BERRY-C3-CONSISTENCY-V1"}))
    text = report["message"].decode()
    assert "WORKFLOW_SCOPE=PROJECT" in text
    assert "ACTIVE_GOAL_ID=MEPHC-BERRY-C3-CONSISTENCY-V1" in text
    assert "WORK_ORDER_OUTCOME=COMPLETED" in text
    assert "GOAL_OUTCOME_CLAIM=ACTIVE" in text
    assert "RESULT_NEXT_SCIENCE_DECISION=STOP_ONE_CAUSAL_BRANCH" in text


def test_finish_native_maps_scientific_fail_closed_to_blocked_report(monkeypatch, tmp_path: Path):
    scope = paths(tmp_path)
    job = {
        "schema": "mephc-thin-job-v1", "job_id": "MEPHC-SCIENCE-FAIL-CLOSED",
        "work_order_id": "MEPHC-THIN-FAIL-CLOSED-0001", "source_commit": "a" * 40,
        "state": "running", "native_run_id": "MEPHC-NATIVE-FAIL-CLOSED",
    }
    run = {
        "state": "succeeded", "actual_native_invocation_count": 1,
        "actual_provider_execution_count": 0, "actual_solver_execution_count": 0,
        "actual_dataset_record_count": 0,
        "result_summary": {"status": "FAIL_CLOSED", "failure_code": "TypeError"},
    }
    monkeypatch.setattr(flow, "wsl", lambda *a, **k: subprocess.CompletedProcess(a, 0, "", ""))
    result = flow.finish_native(scope, job, run)
    assert result["execution"]["terminal_state"] == "failed"
    assert result["execution"]["failure_code"] == "TypeError"
    stored = json.loads((scope.state / "science-jobs" / f"{job['job_id']}.json").read_text())
    report = flow.canonical_report(
        scope, {"work_order_id": job["work_order_id"]}, stored,
        {"task_difficulty": "hard", "instruction_level": "detailed", "report_policy": "milestone"},
    )
    text = report["message"].decode()
    assert "REPORT_KIND=blocked" in text
    assert "TERMINAL_STATE=failed" in text


def test_scoped_commit_records_advisory_scope_warning_instead_of_blocking(monkeypatch, tmp_path: Path):
    scope = paths(tmp_path)
    calls = []
    dirty = iter([["tools/mephc-flow/local_fix.py"], []])
    monkeypatch.setattr(flow, "dirty_paths", lambda _: next(dirty))
    def fake_git(_paths, *args, **kwargs):
        calls.append(args)
        stdout = "tools/mephc-flow/local_fix.py\n" if args[:3] == ("diff", "--cached", "--name-only") else "b" * 40 + "\n"
        return subprocess.CompletedProcess(args, 0, stdout, "")
    monkeypatch.setattr(flow, "git", fake_git)
    result = flow.scoped_commit(scope, {"work_order_id": "MEPHC-THIN-TEST-00000010",
                                        "allowed_writes": ["audit/declared.py"]})
    assert result["scope_warnings"] == ["outside_declared_scope:tools/mephc-flow/local_fix.py"]
    assert any(call and call[0] == "commit" for call in calls)


def test_dataset_record_resolves_by_index_not_rebuilt_namespace(tmp_path: Path):
    namespace = {"source": "old", "entrypoint": "historical.py", "arbitrary": [1, 2, 3]}
    store = science.ImmutableDatasetStore(tmp_path, namespace)
    key = b"fixed-record"
    payload = b"immutable-payload"
    metadata = store.put(key, payload, {"role": "test"})
    manifest = store.finalize(1, {"source": "historical"})
    result = science.resolve_dataset_record(
        tmp_path, manifest["dataset_id"], manifest["manifest_sha256"], metadata["key_sha256"])
    assert result["payload"] == payload
    assert result["identity"] == {"role": "test"}
    with pytest.raises(science.ScientificJobError, match="DATASET_MANIFEST_BINDING_MISMATCH"):
        science.resolve_dataset_record(tmp_path, manifest["dataset_id"], "f" * 64, metadata["key_sha256"])


def test_legacy_dataset_reference_is_rejected_before_execution():
    value = contract()
    value["inputs"] = {"old_dataset_id": "a" * 64, "old_manifest_sha256": "b" * 64}
    with pytest.raises(flow.FlowError, match="DATASET_BINDINGS_V2_REQUIRED"):
        flow.dataset_bindings(value)


def test_named_read_only_dataset_catalog_is_verified_before_dispatch(monkeypatch, tmp_path: Path):
    scope = paths(tmp_path)
    monkeypatch.setattr(flow, "science_module", lambda _: science)
    parent = science.ImmutableDatasetStore(scope.state, {"record_schema": "parent-v1"})
    parent.put(b"parent-key", b"parent", {})
    parent_manifest = parent.finalize(1, {})
    control = science.ImmutableDatasetStore(scope.state, {"record_schema": "control-v1"})
    control.put(b"control-key", b"control", {})
    control_manifest = control.finalize(1, {})
    value = contract(inputs={"datasets": {
        "parent": {"access": "READ_ONLY_BY_NAMESPACE", "namespace_sha256": parent.namespace_sha256,
                   "dataset_schema": "parent-v1", "record_count": 1},
        "control": {"access": "READ_ONLY", "dataset_id": control_manifest["dataset_id"],
                    "manifest_sha256": control_manifest["manifest_sha256"],
                    "dataset_schema": "control-v1", "record_count": 1},
    }})
    resolved = flow.validate_input_bindings(scope, value)
    assert [item["name"] for item in resolved] == ["parent", "control"]
    assert all(len(item["record_key_sha256"]) == 1 for item in resolved)


def test_named_dataset_catalog_rejects_wrong_manifest_before_dispatch(monkeypatch, tmp_path: Path):
    scope = paths(tmp_path)
    monkeypatch.setattr(flow, "science_module", lambda _: science)
    store = science.ImmutableDatasetStore(scope.state, {"record_schema": "control-v1"})
    store.put(b"key", b"payload", {})
    manifest = store.finalize(1, {})
    value = contract(inputs={"datasets": {"control": {
        "access": "READ_ONLY", "dataset_id": manifest["dataset_id"],
        "manifest_sha256": "f" * 64, "dataset_schema": "control-v1", "record_count": 1}}})
    with pytest.raises(flow.FlowError, match="DATASET_MANIFEST_BINDING_MISMATCH"):
        flow.validate_input_bindings(scope, value)


def test_missing_dataset_blocks_before_native(monkeypatch, tmp_path: Path):
    scope = paths(tmp_path)
    value = contract(inputs={
        "tests": ["tests/test_mephc_thin_flow.py"],
        "datasets": [{"dataset_id": "a" * 64, "manifest_sha256": "b" * 64,
                      "record_key_sha256": "c" * 64}],
    })
    monkeypatch.setattr(flow, "state_view", lambda _: {"state": "READY"})
    monkeypatch.setattr(flow, "require_local_implementation", lambda *_: None)
    monkeypatch.setattr(flow, "active_contract", lambda _: ({"work_order_id": value["work_order_id"]}, value))
    monkeypatch.setattr(flow, "publish", lambda *_: {"source_commit": "d" * 40,
                                                      "checkout": "/home/icy/checkout", "tests": []})
    monkeypatch.setattr(flow, "science_module", lambda _: science)
    monkeypatch.setattr(flow, "source", lambda _: {
        "branch": "sandbox", "head": "d" * 40, "origin_main": flow.EXPECTED_MAIN,
        "origin_sandbox": "d" * 40, "dirty": False,
    })
    called = {"wsl": 0}
    monkeypatch.setattr(flow, "wsl", lambda *a, **k: called.__setitem__("wsl", called["wsl"] + 1))
    result = flow.execute(scope)
    assert result["state"] == "READY_TO_CLOSE"
    assert result["execution"]["terminal_state"] == "blocked"
    assert result["execution"]["failure_code"] == "DATASET_NOT_FOUND"
    assert result["execution"]["actual_native_invocation_count"] == 0
    assert result["execution"]["actual_provider_execution_count"] == 0
    assert result["execution"]["actual_solver_execution_count"] == 0
    assert called["wsl"] == 0


def test_resume_rejects_legacy_dataset_before_edit_publish_or_native(monkeypatch, tmp_path: Path):
    scope = paths(tmp_path)
    value = contract(inputs={"tests": ["tests/test_mephc_thin_flow.py"],
                             "p11_trace_dataset_id": "a" * 64})
    monkeypatch.setattr(flow, "state_view", lambda _: {"state": "READY"})
    monkeypatch.setattr(flow, "active_contract", lambda _: ({"work_order_id": value["work_order_id"]}, value))
    monkeypatch.setattr(flow, "source", lambda _: {
        "branch": "sandbox", "head": "d" * 40, "origin_main": flow.EXPECTED_MAIN,
        "origin_sandbox": "d" * 40, "dirty": False,
    })
    published = {"called": False}
    monkeypatch.setattr(flow, "publish", lambda *_: published.__setitem__("called", True))
    result = flow.resume(scope)
    assert result["state"] == "READY_TO_CLOSE"
    assert result["execution"]["failure_code"] == "DATASET_BINDINGS_V2_REQUIRED"
    assert result["execution"]["actual_native_invocation_count"] == 0
    assert published["called"] is False


def test_closeout_reuses_one_request_and_resends_at_most_once(monkeypatch, tmp_path: Path):
    scope = paths(tmp_path)
    work_order = "MEPHC-THIN-TEST-00000002"
    request_id, _ = flow.fixed_request_id(work_order)
    directory = scope.outbox / request_id
    directory.mkdir(parents=True)
    (directory / "request.json").write_text(json.dumps({
        "project_id": "MEPHC", "request_id": request_id, "work_order_id": work_order,
        "fingerprint": "fixed",
    }), encoding="utf-8")
    (directory / "receipt.json").write_text(json.dumps({"state": "response_timeout"}), encoding="utf-8")
    (directory / "events.jsonl").write_text('{"event":"request_submitted"}\n', encoding="utf-8")
    monkeypatch.setattr(flow, "active_order", lambda _: {"work_order_id": work_order, "text": ""})
    calls = []
    def bounded_courier(_p, operation, target):
        calls.append(operation)
        if operation == "courier_resend_once":
            with (target / "events.jsonl").open("a", encoding="utf-8") as handle:
                handle.write('{"event":"request_submitted"}\n')
        return subprocess.CompletedProcess([], 2, "", "")
    monkeypatch.setattr(flow, "courier", bounded_courier)
    first = flow.closeout(scope)
    second = flow.closeout(scope)
    assert first["state"] == second["state"] == "HARD_BLOCKED"
    assert first["submission_count"] == second["submission_count"] == 2
    assert calls == ["courier_recover", "courier_capture_latest", "courier_resend_once",
                     "courier_capture_latest", "courier_recover", "courier_capture_latest"]
    assert len(list(scope.outbox.iterdir())) == 1


def test_closeout_consumes_post_submission_capture_despite_wrong_envelope(monkeypatch, tmp_path: Path):
    scope = paths(tmp_path)
    work_order = "MEPHC-THIN-TEST-00000005"
    successor = "MEPHC-THIN-TEST-00000006"
    request_id, _ = flow.fixed_request_id(work_order)
    directory = scope.outbox / request_id
    directory.mkdir(parents=True)
    request = {"project_id": "MEPHC", "request_id": request_id,
               "work_order_id": work_order, "fingerprint": "fixed"}
    (directory / "request.json").write_text(json.dumps(request), encoding="utf-8")
    (directory / "receipt.json").write_text(json.dumps({"state": "response_protocol_error"}), encoding="utf-8")
    (directory / "events.jsonl").write_text('{"event":"request_submitted"}\n', encoding="utf-8")
    body = ("CHAT_COURIER_REPLY/1\nPROJECT_ID=MEPHC\nREQUEST_ID=WRONG\nBEGIN_RESPONSE\n"
            f"NEXT_WORK_ORDER_ID={successor}\n"
            "WORK_ORDER_CONTRACT_JSON={}\nEND_RESPONSE\n")
    raw = body.encode()
    (directory / "latest-response.raw.txt").write_bytes(raw)
    (directory / "latest-response-capture.json").write_text(json.dumps({
        "project_id": "MEPHC", "request_id": request_id, "fingerprint": "fixed",
        "raw_path": "latest-response.raw.txt", "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "latest_user_turn_found": True, "post_submission_reply_found": True,
    }), encoding="utf-8")
    monkeypatch.setattr(flow, "active_order", lambda _: {"work_order_id": work_order, "text": ""})
    monkeypatch.setattr(flow, "courier", lambda *_: subprocess.CompletedProcess([], 1, "", ""))
    result = flow.closeout(scope)
    assert result["state"] == "READY"
    assert result["work_order_id"] == successor
    assert not (directory / "response.txt").exists()
    evidence = json.loads((directory / "thin-captured-reply.json").read_text())
    assert evidence["envelope_mismatch_tolerated"] is True


def test_remote_reviewer_deferral_is_persistent_hard_block_without_resend(monkeypatch, tmp_path: Path):
    scope = paths(tmp_path)
    work_order = "MEPHC-THIN-TEST-00000021"
    request_id, _ = flow.fixed_request_id(work_order)
    directory = scope.outbox / request_id
    directory.mkdir(parents=True)
    (directory / "request.json").write_text(json.dumps({
        "project_id": "MEPHC", "request_id": request_id,
        "work_order_id": work_order, "fingerprint": "fixed",
    }), encoding="utf-8")
    (directory / "receipt.json").write_text(
        json.dumps({"state": "response_received"}), encoding="utf-8")
    (directory / "events.jsonl").write_text(
        '{"event":"request_submitted"}\n', encoding="utf-8")
    (directory / "response.txt").write_text(
        "LOCAL_SUPERVISOR_REQUIRED=true\n"
        "LOCAL_SUPERVISOR_REASON=LOCAL_FRAMEWORK_STATE\n"
        "MISSING_REMOTE_EVIDENCE=uncommitted runner state\n", encoding="utf-8")
    monkeypatch.setattr(flow, "active_order", lambda _: {"work_order_id": work_order, "text": ""})
    monkeypatch.setattr(flow, "source", lambda _: {"head": "a" * 40, "dirty": False})
    called = {"courier": 0}
    monkeypatch.setattr(flow, "courier", lambda *_: called.__setitem__("courier", called["courier"] + 1))

    consumed = flow.closeout(scope)
    assert consumed["state"] == "HARD_BLOCKED"
    assert consumed["error_code"] == "LOCAL_SUPERVISOR_REQUIRED"
    assert consumed["local_supervisor_requirement"]["reason"] == "LOCAL_FRAMEWORK_STATE"
    assert called["courier"] == 0
    persisted = json.loads((directory / flow.local_supervisor.FILENAME).read_text())
    assert persisted["missing_remote_evidence"] == "uncommitted runner state"

    restarted = flow.state_view(scope)
    assert restarted["state"] == "HARD_BLOCKED"
    assert restarted["safe_next"] is None
    assert restarted["error_code"] == "LOCAL_SUPERVISOR_REQUIRED"
    assert flow.closeout(scope)["error_code"] == "LOCAL_SUPERVISOR_REQUIRED"
    assert called["courier"] == 0


def test_legacy_chat_termination_is_a_supervisor_proposal_not_a_state_transition(tmp_path: Path):
    scope = paths(tmp_path)
    work_order = "MEPHC-THIN-TERMINATION-REVIEW-0001"
    request_id, _ = flow.fixed_request_id(work_order)
    directory = scope.outbox / request_id
    directory.mkdir(parents=True)
    (directory / "request.json").write_text(json.dumps({
        "project_id": "MEPHC", "request_id": request_id, "work_order_id": work_order,
    }), encoding="utf-8")
    (directory / "receipt.json").write_text(json.dumps({"state": "response_received"}), encoding="utf-8")
    (directory / "response.txt").write_text(
        "WORKFLOW_TERMINATED=true\nGOAL_OUTCOME=CONTRADICTED\n"
        "COMPLETION_EVIDENCE=one branch rejected\nCHEAPEST_NEXT_TEST=deterministic pilot\n",
        encoding="utf-8")
    result = flow.consume_response(scope, directory)
    assert result["state"] == "HARD_BLOCKED"
    assert result["error_code"] == "TERMINATION_REVIEW_REQUIRED"
    assert not (scope.legacy_state / "runner" / "workflow-ledger.json").exists()
    evidence = json.loads((directory / flow.local_supervisor.FILENAME).read_text())
    assert evidence["reason"] == "PROJECT_TERMINATION_REVIEW"
    assert evidence["goal_outcome"] == "CONTRADICTED"


def test_explicit_project_termination_review_uses_the_same_supervisor_gate(tmp_path: Path):
    parsed = flow.local_supervisor.parse(
        "LOCAL_SUPERVISOR_REQUIRED=true\n"
        "LOCAL_SUPERVISOR_REASON=PROJECT_TERMINATION_REVIEW\n"
        "MISSING_REMOTE_EVIDENCE=no useful successor identified\n")
    assert parsed is not None
    assert parsed["error_code"] == "TERMINATION_REVIEW_REQUIRED"


def test_only_complete_fixed_supervisor_review_can_approve_project_termination(tmp_path: Path):
    scope = paths(tmp_path)
    directory = scope.outbox / "MEPHC-FLOW-TERMINATION"
    directory.mkdir(parents=True)
    (directory / flow.local_supervisor.FILENAME).write_text(json.dumps({
        "error_code": "TERMINATION_REVIEW_REQUIRED", "reason": "PROJECT_TERMINATION_REVIEW",
    }), encoding="utf-8")
    review = {name: "checked" for name in (
        "completion_evidence", "attempts_completed", "unresolved_questions",
        "alternative_explanations", "cheapest_next_test", "counterevidence_search",
        "why_stop_is_sufficient")}
    with pytest.raises(ValueError, match="TERMINATION_REVIEW_INCOMPLETE"):
        flow.local_supervisor.approve_termination(
            directory, scope.legacy_state / "runner" / "workflow-ledger.json",
            "wrong-task", flow.SUPERVISOR_TASK_ID, review)
    decision = flow.local_supervisor.approve_termination(
        directory, scope.legacy_state / "runner" / "workflow-ledger.json",
        flow.SUPERVISOR_TASK_ID, flow.SUPERVISOR_TASK_ID, review)
    assert decision["reviewer_task_id"] == flow.SUPERVISOR_TASK_ID
    ledger = json.loads((scope.legacy_state / "runner" / "workflow-ledger.json").read_text())
    assert ledger["workflow_state"] == "terminated"
    assert (directory / "supervisor-termination-approval.json").is_file()


def test_captured_remote_reviewer_deferral_is_consumed_without_successor(monkeypatch, tmp_path: Path):
    scope = paths(tmp_path)
    work_order = "MEPHC-THIN-TEST-00000022"
    request_id, _ = flow.fixed_request_id(work_order)
    directory = scope.outbox / request_id
    directory.mkdir(parents=True)
    request = {"project_id": "MEPHC", "request_id": request_id,
               "work_order_id": work_order, "fingerprint": "fixed"}
    (directory / "request.json").write_text(json.dumps(request), encoding="utf-8")
    (directory / "receipt.json").write_text(
        json.dumps({"state": "response_protocol_error"}), encoding="utf-8")
    raw = ("LOCAL_SUPERVISOR_REQUIRED=true\n"
           "LOCAL_SUPERVISOR_REASON=CROSS_REPOSITORY_STATE\n"
           "MISSING_REMOTE_EVIDENCE=local dependency binding\n").encode()
    (directory / "latest-response.raw.txt").write_bytes(raw)
    (directory / "latest-response-capture.json").write_text(json.dumps({
        "raw_path": "latest-response.raw.txt", "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "post_submission_reply_found": True,
    }), encoding="utf-8")
    monkeypatch.setattr(flow, "active_order", lambda _: {"work_order_id": work_order, "text": ""})
    monkeypatch.setattr(flow, "courier", lambda *_: subprocess.CompletedProcess([], 1, "", ""))
    result = flow.closeout(scope)
    assert result["state"] == "HARD_BLOCKED"
    assert result["error_code"] == "LOCAL_SUPERVISOR_REQUIRED"
    assert result["request"]["submission_count"] == 0
    assert (directory / flow.local_supervisor.FILENAME).is_file()
    assert json.loads((directory / "thin-captured-reply.json").read_text())["local_supervisor_required"] is True


def test_capture_binding_accepts_courier_fingerprint_when_request_schema_omits_it(tmp_path: Path):
    scope = paths(tmp_path)
    request_id = "MEPHC-FLOW-236ef7bc1fe8b37773c1c728"
    directory = scope.outbox / request_id
    directory.mkdir(parents=True)
    (directory / "request.json").write_text(json.dumps({
        "project_id": "MEPHC", "request_id": request_id,
        "work_order_id": "MEPHC-THIN-TEST-00000007",
    }), encoding="utf-8")
    raw = b"This content can't be shown"
    (directory / "latest-response.raw.txt").write_bytes(raw)
    (directory / "latest-response-capture.json").write_text(json.dumps({
        "project_id": "MEPHC", "request_id": request_id,
        "fingerprint": "courier-computed-fingerprint",
        "raw_path": "latest-response.raw.txt",
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "latest_user_turn_found": True, "post_submission_reply_found": True,
    }), encoding="utf-8")
    captured = flow.captured_response(scope, directory)
    assert captured is not None
    assert captured[1] == "This content can't be shown"


def test_terminal_job_maps_to_one_closeout_action(monkeypatch, tmp_path: Path):
    scope = paths(tmp_path)
    work_order = "MEPHC-THIN-TEST-00000003"
    monkeypatch.setattr(flow, "source", lambda _: {"branch": "sandbox", "head": "a" * 40,
                                                   "origin_main": flow.EXPECTED_MAIN,
                                                   "origin_sandbox": "a" * 40, "dirty": False})
    monkeypatch.setattr(flow, "active_order", lambda _: {"work_order_id": work_order, "text": ""})
    monkeypatch.setattr(flow, "request_for_work_order", lambda *_: None)
    monkeypatch.setattr(flow, "current_job", lambda *_: {"state": "failed", "job_id": "J"})
    result = flow.state_view(scope)
    assert result["state"] == "READY_TO_CLOSE"
    assert result["safe_next"] == "closeout"


def test_legacy_started_native_count_is_projected_without_recovery():
    summary = flow.job_summary({
        "job_id": "legacy", "state": "failed", "result": {
            "process_started": True, "actual_provider_execution_count": 0,
            "actual_solver_execution_count": 0, "actual_dataset_record_count": 0,
        },
    })
    assert summary["actual_native_invocation_count"] == 1
    assert summary["actual_provider_execution_count"] == 0


def test_interrupted_execute_reconciles_same_terminal_run(monkeypatch, tmp_path: Path):
    scope = paths(tmp_path)
    work_order = "MEPHC-THIN-TEST-00000004"
    run_id = "MEPHC-NATIVE-" + "a" * 24
    job = {"schema": "mephc-thin-job-v1", "job_id": "MEPHC-SCIENCE-" + "b" * 24,
           "work_order_id": work_order, "source_commit": "c" * 40, "action": "acquire",
           "native_run_id": run_id, "state": "running"}
    run_root = scope.state / "native-runs"
    run_root.mkdir(parents=True)
    (run_root / f"{run_id}.json").write_text(json.dumps({
        "run_id": run_id, "state": "failed", "result_error": "CHILD_RETURN_CODE_NONZERO",
        "actual_native_invocation_count": 1, "actual_provider_execution_count": 1,
        "actual_solver_execution_count": 1, "actual_dataset_record_count": 0,
    }), encoding="utf-8")
    monkeypatch.setattr(flow, "state_view", lambda _: {"state": "RUNNING", "work_order_id": work_order})
    monkeypatch.setattr(flow, "current_job", lambda *_: job)
    monkeypatch.setattr(flow, "wsl", lambda *a, **k: subprocess.CompletedProcess([], 0, "", ""))
    result = flow.execute(scope)
    assert result["state"] == "READY_TO_CLOSE"
    assert result["execution"]["native_run_id"] == run_id
    assert result["execution"]["actual_native_invocation_count"] == 1
    assert result["execution"]["failure_code"] == "CHILD_RETURN_CODE_NONZERO"


def test_job_written_before_run_is_safe_pre_dispatch_recovery(monkeypatch, tmp_path: Path):
    scope = paths(tmp_path)
    work_order = "MEPHC-THIN-TEST-PREDISPATCH"
    value = contract(work_order_id=work_order, source_commit="c" * 40)
    identifier = flow.job_id(value, value["source_commit"])
    run_id = "MEPHC-NATIVE-" + flow.digest({"job_id": identifier})[:24]
    job = {
        "schema": "mephc-thin-job-v1", "job_id": identifier,
        "work_order_id": work_order, "contract_sha256": value["contract_sha256"],
        "source_commit": value["source_commit"], "action": "acquire",
        "native_run_id": run_id, "state": "running",
        "actual_native_invocation_count": 0, "actual_provider_execution_count": 0,
        "actual_solver_execution_count": 0, "actual_dataset_record_count": 0,
    }
    monkeypatch.setattr(flow, "active_contract", lambda _: ({"work_order_id": work_order}, value))
    monkeypatch.setattr(flow, "require_source", lambda *_a, **_k: {"head": value["source_commit"]})
    monkeypatch.setattr(flow, "ensure_checkout", lambda *_: "/checkout")
    monkeypatch.setattr(flow, "prepare_inputs", lambda *_: (tmp_path / "bundle", "/bundle.json"))
    launches = []
    monkeypatch.setattr(flow, "wsl", lambda argv, **_kwargs: (
        launches.append(argv) or subprocess.CompletedProcess(argv, 0, "", "")))

    evidence = flow.side_effect_evidence(scope, job)
    assert evidence == {
        "side_effect_state": "DISPATCHING", "execute_reentry_safe": True,
        "dispatch_reached": False, "process_started": False,
    }
    result = flow.reconcile_running(scope, job)
    stored = json.loads((scope.state / "native-runs" / f"{run_id}.json").read_text())
    assert stored["run_id"] == run_id
    assert stored["process_started"] is False
    assert result["state"] == "RUNNING"
    assert len(launches) == 1


def test_dispatching_record_is_never_launched_twice(monkeypatch, tmp_path: Path):
    scope = paths(tmp_path)
    run_id = "MEPHC-NATIVE-" + "d" * 24
    job = {"job_id": "MEPHC-SCIENCE-" + "e" * 24, "work_order_id": "MEPHC-THIN-TEST-DISPATCH",
           "source_commit": "c" * 40, "action": "acquire", "native_run_id": run_id,
           "state": "running"}
    run_root = scope.state / "native-runs"
    run_root.mkdir(parents=True)
    (run_root / f"{run_id}.json").write_text(json.dumps({
        "run_id": run_id, "state": "dispatching", "process_started": False,
    }), encoding="utf-8")
    monkeypatch.setattr(flow, "launch_native", lambda *_: pytest.fail("must not relaunch"))
    result = flow.reconcile_running(scope, job)
    assert result["state"] == "RUNNING"
    evidence = flow.side_effect_evidence(scope, job)
    assert evidence["side_effect_state"] == "DISPATCHING"
    assert evidence["dispatch_reached"] is True


def test_hundred_cycle_identity_soak_has_no_duplicate_requests():
    identifiers = [flow.fixed_request_id(f"MEPHC-THIN-SOAK-{index:08d}")[0] for index in range(100)]
    assert len(set(identifiers)) == 100
    assert identifiers == [flow.fixed_request_id(f"MEPHC-THIN-SOAK-{index:08d}")[0]
                           for index in range(100)]


def test_hundred_complete_fake_provider_and_courier_cycles(monkeypatch, tmp_path: Path):
    scope = paths(tmp_path)
    current = {"index": 0, "contract": None}

    def order(_):
        work_order = f"MEPHC-THIN-SOAK-{current['index']:08d}"
        return {"work_order_id": work_order, "text": ""}

    def validated_contract(_):
        value = contract(
            work_order_id=order(None)["work_order_id"],
            source_commit=f"{current['index'] + 1:040x}",
            expected_output={"dataset_schema": "dataset-v1", "result_schema": "result-v1"},
        )
        current["contract"] = value
        return order(None), value

    monkeypatch.setattr(flow, "state_view", lambda _: {"state": "READY"})
    monkeypatch.setattr(flow, "require_local_implementation", lambda *_: None)
    monkeypatch.setattr(flow, "active_order", order)
    monkeypatch.setattr(flow, "active_contract", validated_contract)
    monkeypatch.setattr(flow, "publish", lambda _p, value: {
        "source_commit": value["source_commit"], "checkout": f"/checkout/{value['source_commit']}",
        "tests": ["tests/test_mephc_thin_flow.py"],
    })
    monkeypatch.setattr(flow, "prepare_inputs", lambda *_: (tmp_path / "bundle", "/bundle.json"))

    def fake_wsl(argv, **_kwargs):
        if "wsl_native_exec.py" in " ".join(argv):
            run_file = next(path for path in (scope.state / "native-runs").glob("*.json")
                            if json.loads(path.read_text())["state"] == "dispatching")
            value = json.loads(run_file.read_text())
            value.update({
                "state": "succeeded", "process_started": True,
                "actual_native_invocation_count": 1, "actual_provider_execution_count": 1,
                "actual_solver_execution_count": 1, "actual_dataset_record_count": 1,
                "result_summary": {"schema": "result-v1", "status": "PASS"},
            })
            run_file.write_text(json.dumps(value), encoding="utf-8")
        return subprocess.CompletedProcess([], 0, "", "")

    def fake_courier(_paths, operation, directory, **_kwargs):
        if operation in {"courier_dispatch", "courier_recover"}:
            events = directory / "events.jsonl"
            if not events.exists():
                events.write_text('{"event":"request_submitted"}\n', encoding="utf-8")
            (directory / "receipt.json").write_text(
                json.dumps({"state": "response_received"}), encoding="utf-8")
            successor = f"MEPHC-THIN-SOAK-NEXT-{current['index']:08d}"
            (directory / "response.txt").write_text(
                f"NEXT_WORK_ORDER_ID={successor}\n", encoding="utf-8")
        return subprocess.CompletedProcess([], 0, "", "")

    monkeypatch.setattr(flow, "wsl", fake_wsl)
    monkeypatch.setattr(flow, "courier", fake_courier)
    for index in range(100):
        current["index"] = index
        executed = flow.execute(scope)
        assert executed["state"] == "READY_TO_CLOSE"
        closed = flow.closeout(scope)
        assert closed["state"] == "READY"
    requests = list(scope.outbox.glob("MEPHC-FLOW-*"))
    assert len(requests) == 100
    assert all(flow.request_summary(path)["submission_count"] == 1 for path in requests)
