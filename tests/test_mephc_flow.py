from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "mephc-flow" / "mephc_flow.py"
SPEC = importlib.util.spec_from_file_location("mephc_flow", MODULE_PATH)
flow = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = flow
SPEC.loader.exec_module(flow)


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def paths(tmp_path: Path) -> flow.Paths:
    return flow.Paths(
        control=tmp_path / "control", state=tmp_path / "legacy" / "flow",
        outbox=tmp_path / "legacy" / "outbox", courier=tmp_path / "courier.cmd",
        legacy_state=tmp_path / "legacy", outbox_wsl=flow.OUTBOX_WSL,
        science_state=tmp_path / "science", science_state_wsl=flow.SCIENCE_STATE_WSL,
    )


def install_active_order(scope: flow.Paths, text: str, work_order_id: str = "MEPHC-TEST-WORK-ORDER-0001") -> None:
    directory = scope.outbox / "MEPHC-OLD-REQUEST"
    directory.mkdir(parents=True)
    response = directory / "response.txt"
    response.write_text(text, encoding="utf-8")
    write_json(directory / "request.json", {"project_id": "MEPHC", "request_id": directory.name})
    write_json(directory / "receipt.json", {"state": "response_received", "request_id": directory.name})
    write_json(scope.legacy_state / "runner" / "workflow-ledger.json", {
        "active_work_order_id": work_order_id,
        "active_response_path": f"{flow.LEGACY_STATE_WSL}/outbox/{directory.name}/response.txt",
        "active_response_sha256": flow.sha256_file(response),
    })


def test_policy_precedence_and_native_cap(tmp_path: Path) -> None:
    scope = paths(tmp_path)
    install_active_order(scope, "NEXT_WORK_ORDER_ID=MEPHC-TEST-WORK-ORDER-0001\n"
                         "REPORT_POLICY=milestone\nNATIVE_SOLVES_AUTHORIZED=true\nNATIVE_SOLVE_BUDGET=7\n")
    result = flow.start(scope, "final-only", 3)
    assert result["report_policy"] == "final-only"
    assert result["chat_native_budget"] == 7
    assert result["effective_native_budget"] == 3


@pytest.mark.parametrize(
    ("policy", "kind", "allowed"),
    [
        ("adaptive", "blocked", True), ("per-work-order", "milestone", True),
        ("milestone", "complete", True), ("final-only", "complete", True),
        ("final-only", "milestone", False), ("final-only", "blocked", False),
    ],
)
def test_report_policy_modes(policy: str, kind: str, allowed: bool) -> None:
    assert flow.report_allowed(policy, kind) is allowed


def test_resume_requires_receipt_bound_hash(tmp_path: Path) -> None:
    scope = paths(tmp_path)
    install_active_order(scope, "NEXT_WORK_ORDER_ID=MEPHC-TEST-WORK-ORDER-0001\n")
    assert flow.resume(scope)["work_order_id"] == "MEPHC-TEST-WORK-ORDER-0001"
    response = scope.outbox / "MEPHC-OLD-REQUEST" / "response.txt"
    response.write_text("drift", encoding="utf-8")
    with pytest.raises(flow.FlowError, match="ACTIVE_RESPONSE_SHA_MISMATCH"):
        flow.resume(scope)


@pytest.mark.parametrize("value", ["audit/x.py", "tests/../x.py", "/tests/x.py", "python -m pytest"])
def test_publish_test_paths_fail_closed(value: str) -> None:
    with pytest.raises(flow.FlowError, match="TEST_PATH_INVALID"):
        flow.validate_test_path(value)


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"dirty": True}, "CONTROL_ROOT_DIRTY"),
        ({"origin_main": "f" * 40}, "ORIGIN_MAIN_MOVED"),
        ({"branch": "main"}, "CONTROL_BRANCH_NOT_SANDBOX"),
        ({"head": "b" * 40, "origin_sandbox": "a" * 40}, "SOURCE_NOT_PUBLISHED"),
    ],
)
def test_source_guards_fail_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, changes: dict, code: str) -> None:
    value = {"branch": "sandbox", "head": "a" * 40, "origin_main": flow.EXPECTED_MAIN,
             "origin_sandbox": "a" * 40, "dirty": False}
    value.update(changes)
    monkeypatch.setattr(flow, "source_state", lambda _paths: value)
    with pytest.raises(flow.FlowError, match=code):
        flow.require_source(paths(tmp_path), published=True)


def test_publish_has_no_certificate_or_activation_gate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    scope = paths(tmp_path)
    head = "a" * 40
    monkeypatch.setattr(flow, "require_source", lambda *_args, **_kwargs: {
        "head": head, "origin_sandbox": "b" * 40, "origin_main": flow.EXPECTED_MAIN,
        "branch": "sandbox", "dirty": False,
    })
    monkeypatch.setattr(flow, "remote_refs", lambda _paths: (flow.EXPECTED_MAIN, "b" * 40))
    monkeypatch.setattr(flow, "ensure_checkout", lambda _paths, _head: f"/home/icy/checkouts/{_head}")
    calls = []

    def fake_git(_paths, *args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, "", "")

    refs = iter([(flow.EXPECTED_MAIN, "b" * 40), (flow.EXPECTED_MAIN, "b" * 40),
                 (flow.EXPECTED_MAIN, head)])
    monkeypatch.setattr(flow, "remote_refs", lambda _paths: next(refs))
    monkeypatch.setattr(flow, "git", fake_git)
    monkeypatch.setattr(flow, "wsl", lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, "1 passed", ""))
    result = flow.publish(scope, ["tests/test_mephc_flow.py"])
    assert result["state"] == "published"
    flattened = " ".join(" ".join(call) for call in calls)
    assert "certificate" not in flattened
    assert "prelive" not in flattened
    assert "activate" not in flattened


def test_native_requires_chat_authorization_before_dispatch(tmp_path: Path) -> None:
    scope = paths(tmp_path)
    install_active_order(scope, "NEXT_WORK_ORDER_ID=MEPHC-TEST-WORK-ORDER-0001\nNATIVE_SOLVES_AUTHORIZED=false\n")
    with pytest.raises(flow.FlowError, match="NATIVE_NOT_AUTHORIZED"):
        flow.run_native(scope, "MEPHC-TEST-WORK-ORDER-0001", 1, "/home/icy/TriLatt", ["python", "x.py"])
    assert not (scope.state / "native-runs").exists()


def test_native_project_scope_rejected_before_host_probe() -> None:
    with pytest.raises(flow.FlowError, match="PROJECT_PATH_OUT_OF_SCOPE"):
        flow.normalize_project("C:/Users/icywo", "/home/icy/checkouts/a", [])
    with pytest.raises(flow.FlowError, match="PROJECT_PATH_NOT_WORK_ORDER_BOUND"):
        flow.normalize_project("/home/icy/UnmentionedProject", "/home/icy/checkouts/a", [])


def test_non_arbitrary_native_is_one_tracked_python_entrypoint(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def fake_wsl(argv, **_kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "audit/e9f/run.py\n", "")

    monkeypatch.setattr(flow, "wsl", fake_wsl)
    policy = {"arbitrary_native_command_authorized": False, "native_entrypoint": None, "native_arguments": []}
    flow.validate_native_argv(policy, "/home/icy/checkouts/a", ["python", "audit/e9f/run.py"])
    assert calls[0][-2:] == ["--error-unmatch", "audit/e9f/run.py"]
    with pytest.raises(flow.FlowError, match="NATIVE_COMMAND_NOT_FIXED_TRACKED_PYTHON_ENTRYPOINT"):
        flow.validate_native_argv(policy, "/home/icy/checkouts/a", ["python", "-c", "print(1)"])


def test_existing_report_is_never_resent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    scope = paths(tmp_path)
    install_active_order(scope, "NEXT_WORK_ORDER_ID=MEPHC-TEST-WORK-ORDER-0001\n")
    message = tmp_path / "message.txt"
    message.write_text("done", encoding="utf-8")
    message_hash = flow.sha256_bytes(message.read_bytes())
    request_hash = flow.sha256_bytes(flow.canonical_json({
        "work_order_id": "MEPHC-TEST-WORK-ORDER-0001", "kind": "complete", "message_sha256": message_hash,
    }))
    request_id = "MEPHC-FLOW-" + request_hash[:24]
    directory = scope.outbox / request_id
    directory.mkdir(parents=True)
    write_json(directory / "request.json", {
        "request_id": request_id, "work_order_id": "MEPHC-TEST-WORK-ORDER-0001",
        "report_kind": "complete", "message_sha256": message_hash,
    })
    called = False

    def forbidden(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("Courier must not run")

    monkeypatch.setattr(flow, "courier_command", forbidden)
    result = flow.report(scope, "MEPHC-TEST-WORK-ORDER-0001", "complete", message)
    assert result["state"] == "existing_request"
    assert result["safe_next"].startswith("courier-reconcile")
    assert called is False


def closeout_prepared() -> dict:
    message = b"SCHEMA=mephc-fixed-closeout-v1\nWORK_ORDER_ID=MEPHC-TEST-WORK-ORDER-0001\nTERMINAL=COMPLETE\n"
    message_hash = flow.sha256_bytes(message)
    request_hash = flow.sha256_bytes(flow.canonical_json({
        "work_order_id": "MEPHC-TEST-WORK-ORDER-0001", "kind": "complete",
        "message_sha256": message_hash,
    }))
    return {
        "work_order_id": "MEPHC-TEST-WORK-ORDER-0001", "work_order_class": "SCIENCE",
        "kind": "complete", "source_commit": "a" * 40, "job_id": "MEPHC-SCIENCE-test",
        "artifacts": [], "message": message, "message_sha256": message_hash,
        "request_hash": request_hash, "request_id": "MEPHC-FLOW-" + request_hash[:24],
    }


def test_closeout_validation_failure_creates_no_request(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    scope = paths(tmp_path)
    prepared = closeout_prepared()
    monkeypatch.setattr(flow, "courier_command", lambda *_args, **_kwargs:
                        subprocess.CompletedProcess([], 2, "", "invalid"))
    with pytest.raises(flow.FlowError, match="COURIER_VALIDATION_FAILED"):
        flow.finish_closeout(scope, prepared)
    assert not (scope.outbox / prepared["request_id"]).exists()


def test_closeout_repeated_call_has_one_submission(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    scope = paths(tmp_path)
    prepared = closeout_prepared()
    operations: list[tuple[str, bool]] = []

    def fake_courier(_paths, operation, directory, *, recovery=False):
        operations.append((operation, recovery))
        if operation == "run" and not recovery:
            (directory / "events.jsonl").write_text('{"event":"request_submitted"}\n', encoding="utf-8")
            write_json(directory / "receipt.json", {"state": "response_timeout", "request_id": directory.name})
        return subprocess.CompletedProcess([], 0, "", "")

    monkeypatch.setattr(flow, "courier_command", fake_courier)
    first = flow.finish_closeout(scope, prepared)
    second = flow.finish_closeout(scope, prepared)
    assert first["submission_count"] == 1
    assert second["submission_count"] == 1
    assert operations.count(("run", False)) == 1
    assert operations.count(("run", True)) == 1


def test_closeout_after_response_only_consumes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    scope = paths(tmp_path)
    prepared = closeout_prepared()
    directory = scope.outbox / prepared["request_id"]
    directory.mkdir(parents=True)
    (directory / "message.txt").write_bytes(prepared["message"])
    write_json(directory / "request.json", flow.report_manifest(prepared))
    write_json(directory / "receipt.json", {"state": "response_received", "request_id": directory.name})
    (directory / "events.jsonl").write_text('{"event":"request_submitted"}\n', encoding="utf-8")
    (directory / "response.txt").write_text("NEXT_WORK_ORDER_ID=MEPHC-NEXT-WORK-ORDER-0002\n", encoding="utf-8")
    monkeypatch.setattr(flow, "courier_command", lambda *_args, **_kwargs: pytest.fail("Courier must not run"))
    result = flow.finish_closeout(scope, prepared)
    assert result["safe_next"] == "resume"
    assert result["next_work_order_id"] == "MEPHC-NEXT-WORK-ORDER-0002"
    assert result["submission_count"] == 1


def test_status_exposes_exact_pending_blocked_closeout_next_step(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    scope = paths(tmp_path)
    work_order_id = "MEPHC-TEST-WORK-ORDER-0001"
    install_active_order(scope, f"NEXT_WORK_ORDER_ID={work_order_id}\n", work_order_id)
    prepared = closeout_prepared()
    prepared["kind"] = "blocked"
    prepared["message"] = prepared["message"].replace(
        b"TERMINAL=COMPLETE", b"BLOCKED_CODE=RESULT_SUMMARY_UNSAFE\nTERMINAL=BLOCKED")
    prepared["message_sha256"] = flow.sha256_bytes(prepared["message"])
    prepared["request_hash"] = flow.sha256_bytes(flow.canonical_json({
        "work_order_id": work_order_id, "kind": "blocked",
        "message_sha256": prepared["message_sha256"],
    }))
    prepared["request_id"] = "MEPHC-FLOW-" + prepared["request_hash"][:24]
    directory = scope.outbox / prepared["request_id"]
    directory.mkdir()
    (directory / "message.txt").write_bytes(prepared["message"])
    write_json(directory / "request.json", flow.report_manifest(prepared))
    write_json(directory / "receipt.json", {"state": "waiting_for_response"})
    (directory / "events.jsonl").write_text('{"event":"request_submitted"}\n', encoding="utf-8")
    monkeypatch.setattr(flow, "source_state", lambda _paths: {
        "branch": "sandbox", "head": "a" * 40, "origin_main": flow.EXPECTED_MAIN,
        "origin_sandbox": "a" * 40, "dirty": False,
    })
    value = flow.status(scope)
    assert value["closeout_state"]["state"] == "waiting_for_response"
    assert value["safe_next"] == "closeout-blocked --code RESULT_SUMMARY_UNSAFE"

    (directory / "response.txt").write_text("NEXT_WORK_ORDER_ID=MEPHC-NEXT-WORK-ORDER-0002\n", encoding="utf-8")
    write_json(directory / "receipt.json", {"state": "response_received"})
    value = flow.status(scope)
    assert value["closeout_state"]["state"] == "response_ready_to_consume"
    assert value["safe_next"] == f"courier-reconcile --request-id {directory.name}"


def test_canonical_closeout_is_bounded_and_path_free(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    scope = paths(tmp_path)
    head = "a" * 40
    work_order_id = "MEPHC-TEST-WORK-ORDER-0001"
    order_text = ("NEXT_WORK_ORDER_ID=" + work_order_id + "\nWORK_ORDER_CLASS=SCIENCE\n"
                  'WORK_ORDER_CONTRACT_JSON={"kind":"SCIENCE","allowed_writes":[]}\n')
    monkeypatch.setattr(flow, "require_source", lambda *_args, **_kwargs: {
        "branch": "sandbox", "head": head, "origin_main": flow.EXPECTED_MAIN,
        "origin_sandbox": head, "dirty": False,
    })
    monkeypatch.setattr(flow, "active_work_order", lambda _paths: {"work_order_id": work_order_id, "text": order_text})
    write_json(scope.state / "publish" / f"{head}.json", {
        "return_code": 0, "published_sandbox": head, "tests": ["tests/test_safe.py"],
    })
    write_json(scope.state / "science-jobs" / "MEPHC-SCIENCE-safe.json", {
        "job_id": "MEPHC-SCIENCE-safe", "work_order_id": work_order_id, "source_commit": head,
        "state": "succeeded", "action": "analyze", "return_code": 0,
        "result_summary": {"decision": "PASS", "count": 4, "H": [1, 2],
                           "private_path": "/home/icy/secret"},
    })
    prepared = flow.canonical_closeout_report(scope)
    text = prepared["message"].decode("utf-8")
    assert "RESULT_DECISION=\"PASS\"" in text
    assert "RESULT_COUNT=4" in text
    assert "[1,2]" not in text
    assert "/home/" not in text
    assert "attachments" not in text.lower()


def acquire_job_for_projection(**native_updates: object) -> dict:
    native = {
        "run_id": "MEPHC-NATIVE-test",
        "state": "succeeded",
        "process_started": True,
        "return_code": 0,
        "launcher_return_code": 0,
        "cost": 1,
        "work_order_id": "MEPHC-TEST-WORK-ORDER-0001",
        "source_commit": "a" * 40,
        "result_summary": {
            "schema": "mephc-r8-c5-r224-acquisition-v1",
            "provider_request_count": 35,
            "native_solves": 35,
        },
    }
    native.update(native_updates)
    return {
        "action": "acquire",
        "work_order_id": "MEPHC-TEST-WORK-ORDER-0001",
        "source_commit": "a" * 40,
        "native_run_id": "MEPHC-NATIVE-test",
        "result": native,
    }


def test_closeout_result_projection_uses_nested_acquire_native_result() -> None:
    projection = flow.closeout_result_projection(acquire_job_for_projection())
    assert projection["return_code"] == 0
    assert projection["native_invocation_count"] == 1
    assert projection["provider_executions"] == 35
    assert projection["solver_executions"] == 35
    assert projection["result_summary"]["schema"] == "mephc-r8-c5-r224-acquisition-v1"


@pytest.mark.parametrize(
    ("updates", "code"),
    [
        ({"native_run_id": None}, "CLOSEOUT_ACQUIRE_NATIVE_RUN_ID_MISSING"),
        ({"process_started": False}, "CLOSEOUT_ACQUIRE_NATIVE_PROCESS_NOT_STARTED"),
        ({"return_code": 1}, "CLOSEOUT_ACQUIRE_NATIVE_RETURN_CODE_INVALID"),
        ({"state": "failed"}, "CLOSEOUT_ACQUIRE_NATIVE_RESULT_NOT_SUCCEEDED"),
        ({"result_summary": None}, "CLOSEOUT_ACQUIRE_RESULT_SUMMARY_MISSING"),
    ],
)
def test_closeout_result_projection_rejects_non_authoritative_acquire_state(
        updates: dict[str, object], code: str) -> None:
    job = acquire_job_for_projection()
    if "native_run_id" in updates:
        job["native_run_id"] = updates["native_run_id"]
    else:
        job["result"].update(updates)
    with pytest.raises(flow.FlowError, match=code):
        flow.closeout_result_projection(job)


def test_closeout_result_projection_preserves_analyze_top_level_result() -> None:
    job = {
        "action": "analyze",
        "return_code": 0,
        "result_summary": {"decision": "PASS", "provider_request_count": 0, "native_solves": 0},
    }
    projection = flow.closeout_result_projection(job)
    assert projection["return_code"] == 0
    assert projection["result_summary"]["decision"] == "PASS"


def test_canonical_closeout_reports_nested_acquire_metrics(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    scope = paths(tmp_path)
    head = "a" * 40
    work_order_id = "MEPHC-TEST-WORK-ORDER-0001"
    order_text = ("NEXT_WORK_ORDER_ID=" + work_order_id + "\nWORK_ORDER_CLASS=SCIENCE\n"
                  'WORK_ORDER_CONTRACT_JSON={"kind":"SCIENCE","allowed_writes":[]}\n')
    monkeypatch.setattr(flow, "require_source", lambda *_args, **_kwargs: {
        "branch": "sandbox", "head": head, "origin_main": flow.EXPECTED_MAIN,
        "origin_sandbox": head, "dirty": False,
    })
    monkeypatch.setattr(flow, "active_work_order", lambda _paths: {
        "work_order_id": work_order_id, "text": order_text,
    })
    write_json(scope.state / "publish" / f"{head}.json", {
        "return_code": 0, "published_sandbox": head, "tests": ["tests/test_mephc_flow.py"],
    })
    job = acquire_job_for_projection()
    job.update({"job_id": "MEPHC-SCIENCE-test", "state": "succeeded"})
    write_json(scope.state / "science-jobs" / "MEPHC-SCIENCE-test.json", job)
    text = flow.canonical_closeout_report(scope)["message"].decode("utf-8")
    assert "SCIENCE_RETURN_CODE=0" in text
    assert "NATIVE_INVOCATION_COUNT=1" in text
    assert "PROVIDER_EXECUTION_COUNT=35" in text
    assert "SOLVER_EXECUTION_COUNT=35" in text


def test_infrastructure_closeout_uses_publish_evidence_without_science_job(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    scope = paths(tmp_path)
    head = "b" * 40
    work_order_id = "MEPHC-INFRA-WORK-ORDER-0001"
    monkeypatch.setattr(flow, "require_source", lambda *_args, **_kwargs: {
        "branch": "sandbox", "head": head, "origin_main": flow.EXPECTED_MAIN,
        "origin_sandbox": head, "dirty": False,
    })
    monkeypatch.setattr(flow, "active_work_order", lambda _paths: {
        "work_order_id": work_order_id,
        "text": f"NEXT_WORK_ORDER_ID={work_order_id}\nWORK_ORDER_CLASS=INFRASTRUCTURE\n",
    })
    write_json(scope.state / "publish" / f"{head}.json", {
        "return_code": 0, "published_sandbox": head, "tests": ["tests/test_mephc_flow.py"],
    })
    prepared = flow.canonical_closeout_report(scope)
    assert prepared["work_order_class"] == "INFRASTRUCTURE"
    assert prepared["job_id"] is None
    assert b"REPORT_KIND=complete" in prepared["message"]


def test_closeout_job_may_cross_only_fixed_flow_infrastructure(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_git(_paths, *args, **_kwargs):
        if args[:2] == ("merge-base", "--is-ancestor"):
            return subprocess.CompletedProcess(args, 0, "", "")
        return subprocess.CompletedProcess(args, 0, "tools/mephc-flow/mephc_flow.py\nAGENTS.md\n", "")

    monkeypatch.setattr(flow, "git", fake_git)
    assert flow.closeout_job_source_compatible(paths(Path("unused")), "a" * 40, "b" * 40) is True

    def reconciliation_diff(_paths, *args, **_kwargs):
        if args[:2] == ("merge-base", "--is-ancestor"):
            return subprocess.CompletedProcess(args, 0, "", "")
        return subprocess.CompletedProcess(
            args, 0, "audit/e9f/qp_b_c2_c3_r8_c5_r224_state_reconciliation.json\n", ""
        )

    monkeypatch.setattr(flow, "git", reconciliation_diff)
    assert flow.closeout_job_source_compatible(paths(Path("unused")), "a" * 40, "b" * 40) is True

    def scientific_diff(_paths, *args, **_kwargs):
        if args[:2] == ("merge-base", "--is-ancestor"):
            return subprocess.CompletedProcess(args, 0, "", "")
        return subprocess.CompletedProcess(args, 0, "audit/e9f/scientific_result.json\n", "")

    monkeypatch.setattr(flow, "git", scientific_diff)
    assert flow.closeout_job_source_compatible(paths(Path("unused")), "a" * 40, "b" * 40) is False


def _acquire_binding_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[flow.Paths, dict, dict]:
    scope = paths(tmp_path)
    work_order_id = "MEPHC-E9F-C2-QP-B-C2-C3-R8-C7-A1-20260828-315"
    job_source, published_source = "a" * 40, "b" * 40
    binding_path = "audit/e9f/qp_b_c2_c3_r8_c7_r256_acquisition_binding.json"
    order_text = ('WORK_ORDER_CONTRACT_JSON=' + json.dumps({
        "kind": "SCIENCE", "action": "acquire", "work_order_id": work_order_id,
        "allowed_writes": [binding_path],
    }) + "\n")
    monkeypatch.setattr(flow, "active_work_order", lambda _paths: {
        "work_order_id": work_order_id, "text": order_text,
    })
    summary = {
        "R256_dataset_id": "1" * 64, "R256_dataset_manifest_sha256": "2" * 64,
        "R256_entrypoint_sha256": "3" * 64, "R256_request_graph_sha256": "4" * 64,
        "science_runtime_sha256": "5" * 64, "logical_provider_demand_count": 36,
        "unique_provider_request_count": 35, "duplicate_logical_demand_count": 1,
        "completed_key_count": 35, "failed_key_count": 0, "provider_failure_count": 0,
        "fresh_provider_execution_count": 35, "cache_reuse_count": 0, "mpb_execution": True,
    }
    binding = {
        "work_order_id": work_order_id, "acquisition_source_commit": job_source,
        "acquisition_dataset_id": summary["R256_dataset_id"],
        "dataset_manifest_sha256": summary["R256_dataset_manifest_sha256"],
        "entrypoint_sha256": summary["R256_entrypoint_sha256"],
        "graph_sha256": summary["R256_request_graph_sha256"],
        "science_runtime_sha256": summary["science_runtime_sha256"],
        "logical_provider_demand_count": 36, "unique_provider_request_count": 35,
        "duplicate_logical_demand_count": 1, "completed_key_count": 35,
        "failed_key_count": 0, "provider_failure_count": 0,
        "fresh_provider_execution_count": 35, "cache_reuse_count": 0,
        "mpb_execution": True, "completion_state": "COMPLETE",
    }
    job = {
        "job_id": "MEPHC-SCIENCE-" + "c" * 24, "work_order_id": work_order_id,
        "source_commit": job_source, "action": "acquire", "state": "succeeded",
        "native_run_id": "MEPHC-NATIVE-" + "d" * 24,
        "result": {
            "run_id": "MEPHC-NATIVE-" + "d" * 24, "state": "succeeded",
            "process_started": True, "return_code": 0, "launcher_return_code": 0,
            "result_summary": summary,
        },
    }
    write_json(scope.state / "science-jobs" / f"{job['job_id']}.json", job)

    def fake_git(_paths, *args, **kwargs):
        if args[:2] == ("merge-base", "--is-ancestor"):
            return subprocess.CompletedProcess(args, 0, "", "")
        if args[:2] == ("diff", "--name-only"):
            return subprocess.CompletedProcess(args, 0, binding_path + "\n", "")
        if args[:2] == ("ls-tree", "--name-only"):
            return subprocess.CompletedProcess(args, 0, "", "")
        if args[:1] == ("show",):
            return subprocess.CompletedProcess(args, 0, json.dumps(binding), "")
        raise AssertionError(args)
    monkeypatch.setattr(flow, "git", fake_git)
    return scope, binding, {"job_source": job_source, "published_source": published_source, "binding_path": binding_path}


def test_closeout_job_accepts_exact_post_execution_acquisition_binding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    scope, _binding, refs = _acquire_binding_fixture(tmp_path, monkeypatch)
    assert flow.closeout_job_source_compatible(scope, refs["job_source"], refs["published_source"]) is True


def _d9_missing_provider_failure_fixture(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> tuple[flow.Paths, dict, dict]:
    scope, binding, refs = _acquire_binding_fixture(tmp_path, monkeypatch)
    work_order_id = "MEPHC-E9F-D9-FR04-RESIDUAL-COMPOSITE-CONVERGENCE-ACQ-20260829-337"
    binding_path = refs["binding_path"]
    monkeypatch.setattr(flow, "active_work_order", lambda _paths: {
        "work_order_id": work_order_id,
        "text": "WORK_ORDER_CONTRACT_JSON=" + json.dumps({
            "kind": "SCIENCE", "action": "acquire", "work_order_id": work_order_id,
            "allowed_writes": [binding_path],
        }) + "\n",
    })
    job_path = next((scope.state / "science-jobs").glob("MEPHC-SCIENCE-*.json"))
    job = json.loads(job_path.read_text(encoding="utf-8"))
    job["work_order_id"] = work_order_id
    summary = job["result"]["result_summary"]
    summary.clear()
    summary.update({
        "schema": "mephc-e9f-d9-fr04-residual-composite-convergence-acquisition-v1",
        "d9_dataset_id": "1" * 64, "d9_dataset_manifest_sha256": "2" * 64,
        "d9_entrypoint_sha256": "3" * 64, "d9_request_graph_sha256": "4" * 64,
        "science_runtime_sha256": "5" * 64, "logical_provider_demand_count": 420,
        "unique_provider_request_count": 420, "completed_key_count": 420,
        "failed_key_count": 0, "fresh_provider_execution_count": 420,
        "cache_reuse_count": 0, "mpb_execution": True, "provider_request_count": 420,
        "solver_executions": 420, "native_solves": 420, "native_retry_count": 0,
    })
    write_json(job_path, job)
    binding.clear()
    binding.update({
        "schema": "mephc-e9f-d9-fr04-residual-composite-acquisition-binding-v1",
        "work_order_id": work_order_id, "acquisition_source_commit": refs["job_source"],
        "acquisition_dataset_id": summary["d9_dataset_id"],
        "dataset_manifest_sha256": summary["d9_dataset_manifest_sha256"],
        "entrypoint_sha256": summary["d9_entrypoint_sha256"],
        "graph_sha256": summary["d9_request_graph_sha256"],
        "science_runtime_sha256": summary["science_runtime_sha256"],
        "logical_provider_demand_count": 420, "unique_provider_request_count": 420,
        "duplicate_logical_demand_count": 0, "completed_key_count": 420,
        "failed_key_count": 0, "provider_failure_count": 0,
        "fresh_provider_execution_count": 420, "cache_reuse_count": 0,
        "mpb_execution": True, "completion_state": "COMPLETE",
    })
    write_json(scope.control / "audit/e9f/d9r1_fr04_residual_composite_dataset_reconciliation.json", {
        "schema": "mephc-e9f-d9r1-fr04-residual-composite-dataset-reconciliation-v1",
        "d9_dataset_id": summary["d9_dataset_id"],
        "d9_dataset_manifest_sha256": summary["d9_dataset_manifest_sha256"],
        "d9_dataset_record_count": 420, "full_d9_record_integrity_pass_count": 420,
        "d9_existing_dataset_status": "COMPLETE_NATIVE_RESULT_AND_DATASET_VERIFIED",
        "d9_provider_failure_count_reconciliation_status": "PASS_DERIVED_ZERO_FROM_COMPLETE_EXACT_ACCOUNTING",
        "strict_d9_missing_provider_failure_count_compatibility_status": "PASS",
    })
    return scope, binding, refs


def test_closeout_job_accepts_strict_d9_missing_provider_failure_count_reconciliation(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope, _binding, refs = _d9_missing_provider_failure_fixture(tmp_path, monkeypatch)
    assert flow.closeout_job_source_compatible(scope, refs["job_source"], refs["published_source"]) is True


@pytest.mark.parametrize("mutation", [
    "failed", "completed", "provider_requests", "fresh_provider", "solver", "native_solves",
    "cache_reuse", "native_retry", "mpb", "binding_missing", "binding_nonzero", "binding_incomplete",
    "evidence_incomplete",
])
def test_closeout_job_rejects_d9_missing_provider_failure_count_without_exact_reconciliation(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str,
) -> None:
    scope, binding, refs = _d9_missing_provider_failure_fixture(tmp_path, monkeypatch)
    job_path = next((scope.state / "science-jobs").glob("MEPHC-SCIENCE-*.json"))
    job = json.loads(job_path.read_text(encoding="utf-8"))
    summary = job["result"]["result_summary"]
    if mutation == "failed":
        summary["failed_key_count"] = 1
    elif mutation == "completed":
        summary["completed_key_count"] = 419
    elif mutation == "provider_requests":
        summary["provider_request_count"] = 419
    elif mutation == "fresh_provider":
        summary["fresh_provider_execution_count"] = 419
    elif mutation == "solver":
        summary["solver_executions"] = 419
    elif mutation == "native_solves":
        summary["native_solves"] = 419
    elif mutation == "cache_reuse":
        summary["cache_reuse_count"] = 1
    elif mutation == "native_retry":
        summary["native_retry_count"] = 1
    elif mutation == "mpb":
        summary["mpb_execution"] = False
    elif mutation == "binding_missing":
        binding.pop("provider_failure_count")
    elif mutation == "binding_nonzero":
        binding["provider_failure_count"] = 1
    elif mutation == "binding_incomplete":
        binding["completion_state"] = "PARTIAL"
    elif mutation == "evidence_incomplete":
        evidence = scope.control / "audit/e9f/d9r1_fr04_residual_composite_dataset_reconciliation.json"
        value = json.loads(evidence.read_text(encoding="utf-8"))
        value["full_d9_record_integrity_pass_count"] = 419
        write_json(evidence, value)
    write_json(job_path, job)
    assert flow.closeout_job_source_compatible(scope, refs["job_source"], refs["published_source"]) is False


def _d6r2_binding_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[flow.Paths, dict, dict]:
    scope = paths(tmp_path)
    work_order_id = "MEPHC-E9F-D6R2-FR04-R64-CORRECTED-SHARED-ACQUISITION-20260829-333"
    job_source, published_source = "a" * 40, "b" * 40
    binding_path = "audit/e9f/d6_fr04_r64_corrected_acquisition_binding.json"
    order_text = "WORK_ORDER_CONTRACT_JSON=" + json.dumps({
        "kind": "SCIENCE", "action": "acquire", "work_order_id": work_order_id,
        "allowed_writes": [binding_path],
    }) + "\n"
    monkeypatch.setattr(flow, "active_work_order", lambda _paths: {
        "work_order_id": work_order_id, "text": order_text,
    })
    prefix = "fr04_corrected_r64"
    summary = {
        f"{prefix}_dataset_id": "1" * 64,
        f"{prefix}_dataset_manifest_sha256": "2" * 64,
        f"{prefix}_dataset_record_count": 3205,
        f"{prefix}_entrypoint_sha256": "3" * 64,
        f"{prefix}_request_graph_sha256": "4" * 64,
        f"{prefix}_domain_list_sha256": "5" * 64,
        f"{prefix}_geometry_boundary_digest": "6" * 64,
        f"{prefix}_source_model_identity": "E9E_FR04_ROUNDED_TRIANGLE_V1",
        f"{prefix}_arc_segments_per_corner": 96,
        "science_runtime_sha256": "7" * 64,
        "fr": 0.4, "resolution": "R64", "logical_provider_demand_count": 3205,
        "unique_provider_request_count": 3205, "completed_key_count": 3205,
        "failed_key_count": 0, "provider_failure_count": 0,
        "fresh_provider_execution_count": 3205, "provider_request_count": 3205,
        "solver_executions": 3205, "native_solves": 3205, "cache_reuse_count": 0,
        "mpb_execution": True, "native_retry_count": 0,
        "immutable_dataset_completion_state": "COMPLETE",
    }
    binding = {
        "schema": "mephc-e9f-d6-fr04-r64-corrected-acquisition-binding-v1",
        "work_order_id": work_order_id, "acquisition_source_commit": job_source,
        "acquisition_dataset_id": summary[f"{prefix}_dataset_id"],
        "dataset_manifest_sha256": summary[f"{prefix}_dataset_manifest_sha256"],
        "entrypoint_sha256": summary[f"{prefix}_entrypoint_sha256"],
        "corrected_graph_sha256": summary[f"{prefix}_request_graph_sha256"],
        "science_runtime_sha256": summary["science_runtime_sha256"],
        "dataset_record_count": 3205, "domain_list_sha256": summary[f"{prefix}_domain_list_sha256"],
        "geometry_boundary_digest": summary[f"{prefix}_geometry_boundary_digest"],
        "source_model_identity": summary[f"{prefix}_source_model_identity"],
        "arc_segments_per_corner": 96, "resolution": "R64", "fr": 0.4,
        "logical_provider_demand_count": 3205, "unique_provider_request_count": 3205,
        "duplicate_logical_demand_count": 0, "completed_key_count": 3205,
        "failed_key_count": 0, "provider_failure_count": 0,
        "fresh_provider_execution_count": 3205, "provider_request_count": 3205,
        "solver_executions": 3205, "native_solves": 3205, "cache_reuse_count": 0,
        "mpb_execution": True, "native_retry_count": 0, "completion_state": "COMPLETE",
    }
    job = {
        "job_id": "MEPHC-SCIENCE-" + "c" * 24, "work_order_id": work_order_id,
        "source_commit": job_source, "action": "acquire", "state": "succeeded",
        "native_run_id": "MEPHC-NATIVE-" + "d" * 24,
        "result": {
            "run_id": "MEPHC-NATIVE-" + "d" * 24, "state": "succeeded",
            "process_started": True, "return_code": 0, "launcher_return_code": 0,
            "result_summary": summary,
        },
    }
    write_json(scope.state / "science-jobs" / f"{job['job_id']}.json", job)

    def fake_git(_paths, *args, **kwargs):
        if args[:2] == ("merge-base", "--is-ancestor"):
            return subprocess.CompletedProcess(args, 0, "", "")
        if args[:2] == ("diff", "--name-only"):
            return subprocess.CompletedProcess(args, 0, binding_path + "\n", "")
        if args[:2] == ("ls-tree", "--name-only"):
            return subprocess.CompletedProcess(args, 0, "", "")
        if args[:1] == ("show",):
            return subprocess.CompletedProcess(args, 0, json.dumps(binding), "")
        raise AssertionError(args)
    monkeypatch.setattr(flow, "git", fake_git)
    return scope, binding, {"job_source": job_source, "published_source": published_source, "binding_path": binding_path}


def test_closeout_job_accepts_namespaced_d6r2_acquisition_binding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    scope, _binding, refs = _d6r2_binding_fixture(tmp_path, monkeypatch)
    assert flow.closeout_job_source_compatible(scope, refs["job_source"], refs["published_source"]) is True


@pytest.mark.parametrize("mutation", [
    "multiple_dataset_ids", "missing_manifest", "missing_entrypoint", "missing_graph",
    "wrong_corrected_graph", "wrong_domain", "wrong_geometry", "wrong_source_model",
    "wrong_dataset", "wrong_manifest", "wrong_source_commit", "wrong_record_count",
    "incomplete",
])
def test_closeout_job_rejects_invalid_namespaced_d6r2_binding(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str,
) -> None:
    scope, binding, refs = _d6r2_binding_fixture(tmp_path, monkeypatch)
    job_path = next((scope.state / "science-jobs").glob("MEPHC-SCIENCE-*.json"))
    job = json.loads(job_path.read_text(encoding="utf-8"))
    summary = job["result"]["result_summary"]
    prefix = "fr04_corrected_r64"
    if mutation == "multiple_dataset_ids":
        summary["R64_dataset_id"] = "8" * 64
    elif mutation == "missing_manifest":
        summary.pop(f"{prefix}_dataset_manifest_sha256")
    elif mutation == "missing_entrypoint":
        summary.pop(f"{prefix}_entrypoint_sha256")
    elif mutation == "missing_graph":
        summary.pop(f"{prefix}_request_graph_sha256")
    elif mutation == "wrong_corrected_graph":
        binding["corrected_graph_sha256"] = "f" * 64
    elif mutation == "wrong_domain":
        binding["domain_list_sha256"] = "f" * 64
    elif mutation == "wrong_geometry":
        binding["geometry_boundary_digest"] = "f" * 64
    elif mutation == "wrong_source_model":
        binding["source_model_identity"] = "WRONG"
    elif mutation == "wrong_dataset":
        binding["acquisition_dataset_id"] = "f" * 64
    elif mutation == "wrong_manifest":
        binding["dataset_manifest_sha256"] = "f" * 64
    elif mutation == "wrong_source_commit":
        binding["acquisition_source_commit"] = "f" * 40
    elif mutation == "wrong_record_count":
        binding["dataset_record_count"] = 3204
    elif mutation == "incomplete":
        binding["completion_state"] = "PARTIAL"
    write_json(job_path, job)
    monkeypatch.setattr(flow, "git", lambda _paths, *args, **kwargs: (
        subprocess.CompletedProcess(args, 0, "", "") if args[:2] == ("merge-base", "--is-ancestor")
        else subprocess.CompletedProcess(args, 0, refs["binding_path"] + "\n", "") if args[:2] == ("diff", "--name-only")
        else subprocess.CompletedProcess(args, 0, "", "") if args[:2] == ("ls-tree", "--name-only")
        else subprocess.CompletedProcess(args, 0, json.dumps(binding), "")
    ))
    assert flow.closeout_job_source_compatible(scope, refs["job_source"], refs["published_source"]) is False


@pytest.mark.parametrize("binding_duplicate", [None, 1])
def test_closeout_job_derives_d3_duplicate_demand_count(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, binding_duplicate: int | None,
) -> None:
    scope, binding, refs = _acquire_binding_fixture(tmp_path, monkeypatch)
    job_path = next((scope.state / "science-jobs").glob("MEPHC-SCIENCE-*.json"))
    job = json.loads(job_path.read_text(encoding="utf-8"))
    summary = job["result"]["result_summary"]
    summary.pop("duplicate_logical_demand_count")
    summary["logical_provider_demand_count"] = 3205
    summary["unique_provider_request_count"] = 3205
    write_json(job_path, job)
    if binding_duplicate is None:
        binding.pop("duplicate_logical_demand_count")
    else:
        binding["duplicate_logical_demand_count"] = binding_duplicate
    assert flow.closeout_job_source_compatible(scope, refs["job_source"], refs["published_source"]) is (binding_duplicate == 0)


@pytest.mark.parametrize("logical, unique", [(34, 35), (35.0, 35), (35, True)])
def test_closeout_job_rejects_invalid_d3_duplicate_derivation(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, logical: object, unique: object,
) -> None:
    scope, binding, refs = _acquire_binding_fixture(tmp_path, monkeypatch)
    job_path = next((scope.state / "science-jobs").glob("MEPHC-SCIENCE-*.json"))
    job = json.loads(job_path.read_text(encoding="utf-8"))
    summary = job["result"]["result_summary"]
    summary.pop("duplicate_logical_demand_count")
    summary["logical_provider_demand_count"] = logical
    summary["unique_provider_request_count"] = unique
    write_json(job_path, job)
    binding["duplicate_logical_demand_count"] = 0
    assert flow.closeout_job_source_compatible(scope, refs["job_source"], refs["published_source"]) is False


@pytest.mark.parametrize("field", [
    "acquisition_source_commit", "acquisition_dataset_id", "dataset_manifest_sha256",
    "entrypoint_sha256", "graph_sha256", "science_runtime_sha256",
])
def test_closeout_job_rejects_binding_identity_drift(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str) -> None:
    scope, binding, refs = _acquire_binding_fixture(tmp_path, monkeypatch)
    binding[field] = "f" * 64 if field != "acquisition_source_commit" else "f" * 40
    monkeypatch.setattr(flow, "git", lambda _paths, *args, **kwargs: (
        subprocess.CompletedProcess(args, 0, "", "") if args[:2] == ("merge-base", "--is-ancestor")
        else subprocess.CompletedProcess(args, 0, refs["binding_path"] + "\n", "") if args[:2] == ("diff", "--name-only")
        else subprocess.CompletedProcess(args, 0, "", "") if args[:2] == ("ls-tree", "--name-only")
        else subprocess.CompletedProcess(args, 0, json.dumps(binding), "")
    ))
    assert flow.closeout_job_source_compatible(scope, refs["job_source"], refs["published_source"]) is False


@pytest.mark.parametrize("changed", [
    "audit/e9f/qp_b_c2_c3_r8_c7_r256_targeted_acquisition.py",
    "audit/e9f/qp_b_c2_c3_r8_c7_r256_request_graph.json",
    "audit/e9f/qp_b_c2_c3_r8_c7_parity_aware_method_contract.json",
    "tools/mephc-flow/scientific_job.py",
])
def test_closeout_job_rejects_execution_input_or_runtime_change(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, changed: str) -> None:
    scope, _binding, refs = _acquire_binding_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(flow, "git", lambda _paths, *args, **kwargs: (
        subprocess.CompletedProcess(args, 0, "", "") if args[:2] == ("merge-base", "--is-ancestor")
        else subprocess.CompletedProcess(args, 0, changed + "\n", "") if args[:2] == ("diff", "--name-only")
        else subprocess.CompletedProcess(args, 0, "", "")
    ))
    assert flow.closeout_job_source_compatible(scope, refs["job_source"], refs["published_source"]) is False


def test_closeout_job_rejects_second_post_execution_file_and_preexisting_binding(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    scope, _binding, refs = _acquire_binding_fixture(tmp_path, monkeypatch)
    def second_file_git(_paths, *args, **kwargs):
        if args[:2] == ("merge-base", "--is-ancestor"):
            return subprocess.CompletedProcess(args, 0, "", "")
        if args[:2] == ("diff", "--name-only"):
            return subprocess.CompletedProcess(args, 0, refs["binding_path"] + "\naudit/e9f/extra.json\n", "")
        return subprocess.CompletedProcess(args, 0, "", "")
    monkeypatch.setattr(flow, "git", second_file_git)
    assert flow.closeout_job_source_compatible(scope, refs["job_source"], refs["published_source"]) is False

    scope, _binding, refs = _acquire_binding_fixture(tmp_path / "preexisting", monkeypatch)
    def preexisting_git(_paths, *args, **kwargs):
        if args[:2] == ("merge-base", "--is-ancestor"):
            return subprocess.CompletedProcess(args, 0, "", "")
        if args[:2] == ("diff", "--name-only"):
            return subprocess.CompletedProcess(args, 0, refs["binding_path"] + "\n", "")
        if args[:2] == ("ls-tree", "--name-only"):
            return subprocess.CompletedProcess(args, 0, refs["binding_path"] + "\n", "")
        return subprocess.CompletedProcess(args, 0, "", "")
    monkeypatch.setattr(flow, "git", preexisting_git)
    assert flow.closeout_job_source_compatible(scope, refs["job_source"], refs["published_source"]) is False


def _d5r3_binding_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[flow.Paths, dict, dict]:
    scope = paths(tmp_path)
    work_order_id = "MEPHC-E9F-D5R3-FR04-CORRECTED-K-REPLAY-20260829-329"
    job_source, published_source = "a" * 40, "b" * 40
    binding_path = "audit/e9f/d5r3_fr04_corrected_k_replay_binding.json"
    order_text = "WORK_ORDER_CONTRACT_JSON=" + json.dumps({
        "kind": "SCIENCE", "action": "acquire", "work_order_id": work_order_id,
        "allowed_writes": [binding_path],
    }) + "\n"
    monkeypatch.setattr(flow, "active_work_order", lambda _paths: {
        "work_order_id": work_order_id, "text": order_text,
    })
    spectrum = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]
    summary = {
        "work_order_id": work_order_id, "execution_source_commit": job_source,
        "science_runtime_sha256": "1" * 64, "corrected_graph_sha256": "2" * 64,
        "corrected_geometry_status": "PASS", "spectral_replay_pass": True,
        "maximum_absolute_frequency_error": 0.0,
        "live_k_gap_band0_band1": 0.1, "live_k_gap_band1_band2": 0.1,
        "validation_dataset_id": "3" * 64, "validation_dataset_manifest_sha256": "4" * 64,
        "validation_dataset_record_count": 1, "validation_entrypoint_sha256": "5" * 64,
        "native_invocation_count": 1, "provider_request_count": 1,
        "fresh_provider_execution_count": 1, "solver_executions": 1,
        "native_solves": 1, "mpb_execution": True, "native_retry_count": 0,
        "live_fr04_r64_six_band_spectrum": spectrum,
        "reference_fr04_r64_tess96_six_band_spectrum": spectrum,
    }
    binding = {
        "work_order_id": work_order_id, "acquisition_source_commit": job_source,
        "acquisition_dataset_id": summary["validation_dataset_id"],
        "dataset_manifest_sha256": summary["validation_dataset_manifest_sha256"],
        "entrypoint_sha256": summary["validation_entrypoint_sha256"],
        "science_runtime_sha256": summary["science_runtime_sha256"],
        "corrected_graph_sha256": summary["corrected_graph_sha256"],
        "dataset_record_count": 1, "spectral_replay_pass": True,
        "maximum_absolute_frequency_error": 0.0, "k_gap_band0_band1": 0.1,
        "k_gap_band1_band2": 0.1, "native_invocation_count": 1,
        "provider_request_count": 1, "fresh_provider_execution_count": 1,
        "solver_executions": 1, "native_solves": 1, "mpb_execution": True,
        "native_retry_count": 0, "actual_frequencies": spectrum,
        "reference_frequencies": spectrum, "completion_state": "COMPLETE",
    }
    job = {
        "job_id": "MEPHC-SCIENCE-" + "c" * 24, "work_order_id": work_order_id,
        "source_commit": job_source, "action": "acquire", "state": "succeeded",
        "native_run_id": "MEPHC-NATIVE-" + "d" * 24,
        "result": {
            "run_id": "MEPHC-NATIVE-" + "d" * 24, "state": "succeeded",
            "process_started": True, "return_code": 0, "launcher_return_code": 0,
            "result_summary": summary,
        },
    }
    write_json(scope.state / "science-jobs" / f"{job['job_id']}.json", job)

    def fake_git(_paths, *args, **kwargs):
        if args[:2] == ("merge-base", "--is-ancestor"):
            return subprocess.CompletedProcess(args, 0, "", "")
        if args[:2] == ("diff", "--name-only"):
            return subprocess.CompletedProcess(args, 0, binding_path + "\n", "")
        if args[:2] == ("ls-tree", "--name-only"):
            return subprocess.CompletedProcess(args, 0, "", "")
        if args[:1] == ("show",):
            return subprocess.CompletedProcess(args, 0, json.dumps(binding), "")
        raise AssertionError(args)
    monkeypatch.setattr(flow, "git", fake_git)
    return scope, binding, {"job_source": job_source, "published_source": published_source, "binding_path": binding_path}


def test_closeout_job_accepts_d5r3_post_execution_replay_binding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    scope, _binding, refs = _d5r3_binding_fixture(tmp_path, monkeypatch)
    assert flow.closeout_job_source_compatible(scope, refs["job_source"], refs["published_source"]) is True


@pytest.mark.parametrize("field", [
    "entrypoint_sha256", "corrected_graph_sha256", "acquisition_dataset_id",
    "dataset_manifest_sha256", "acquisition_source_commit",
])
def test_closeout_job_rejects_d5r3_binding_identity_drift(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str) -> None:
    scope, binding, refs = _d5r3_binding_fixture(tmp_path, monkeypatch)
    binding[field] = "f" * 40 if field == "acquisition_source_commit" else "f" * 64
    assert flow.closeout_job_source_compatible(scope, refs["job_source"], refs["published_source"]) is False


def test_closeout_job_rejects_d5r3_missing_completion_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    scope, binding, refs = _d5r3_binding_fixture(tmp_path, monkeypatch)
    binding.pop("completion_state")
    assert flow.closeout_job_source_compatible(scope, refs["job_source"], refs["published_source"]) is False


def test_closeout_job_rejects_d5r3_extra_post_execution_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    scope, _binding, refs = _d5r3_binding_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(flow, "git", lambda _paths, *args, **kwargs: (
        subprocess.CompletedProcess(args, 0, "", "") if args[:2] == ("merge-base", "--is-ancestor")
        else subprocess.CompletedProcess(args, 0, refs["binding_path"] + "\naudit/e9f/extra.json\n", "") if args[:2] == ("diff", "--name-only")
        else subprocess.CompletedProcess(args, 0, "", "")
    ))
    assert flow.closeout_job_source_compatible(scope, refs["job_source"], refs["published_source"]) is False


def test_closeout_job_rejects_failed_d5r3_science_job(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    scope, _binding, refs = _d5r3_binding_fixture(tmp_path, monkeypatch)
    job_path = next((scope.state / "science-jobs").glob("MEPHC-SCIENCE-*.json"))
    job = json.loads(job_path.read_text(encoding="utf-8"))
    job["state"] = "failed"
    write_json(job_path, job)
    assert flow.closeout_job_source_compatible(scope, refs["job_source"], refs["published_source"]) is False


def test_closeout_blocked_accepts_only_structured_code(tmp_path: Path) -> None:
    scope = paths(tmp_path)
    with pytest.raises(flow.FlowError, match="CLOSEOUT_BLOCKED_CODE_INVALID"):
        flow.canonical_closeout_report(scope, blocked_code="please send arbitrary text")


def test_reconcile_submission_not_started_is_read_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    scope = paths(tmp_path)
    request_id = "MEPHC-REPORT-eefa75f04fec965bf3dd98c8"
    directory = scope.outbox / request_id
    directory.mkdir(parents=True)
    write_json(directory / "request.json", {"project_id": "MEPHC", "request_id": request_id})
    write_json(directory / "receipt.json", {"state": "submission_not_started"})
    monkeypatch.setattr(flow, "courier_command", lambda *_args, **_kwargs: pytest.fail("must remain read-only"))
    result = flow.courier_reconcile(scope, request_id)
    assert result["state"] == "not_recoverable_read_only"
    assert result["submission_count"] == 0


def test_reconcile_late_response_does_not_launch_courier(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    scope = paths(tmp_path)
    request_id = "MEPHC-FLOW-1234567890abcdef12345678"
    directory = scope.outbox / request_id
    directory.mkdir(parents=True)
    write_json(directory / "request.json", {"project_id": "MEPHC", "request_id": request_id})
    write_json(directory / "receipt.json", {"state": "response_received"})
    (directory / "response.txt").write_text("NEXT_WORK_ORDER_ID=MEPHC-NEXT-ORDER-0001", encoding="utf-8")
    monkeypatch.setattr(flow, "courier_command", lambda *_args, **_kwargs: pytest.fail("must remain read-only"))
    result = flow.courier_reconcile(scope, request_id)
    assert result["state"] == "response_received"
    assert result["response_sha256"] == flow.sha256_file(directory / "response.txt")
    assert flow.active_work_order(scope)["work_order_id"] == "MEPHC-NEXT-ORDER-0001"


def test_resume_discovers_and_consumes_newest_receipt_bound_response(tmp_path: Path) -> None:
    scope = paths(tmp_path)
    install_active_order(scope, "NEXT_WORK_ORDER_ID=MEPHC-OLD-ORDER-0001\n", "MEPHC-OLD-ORDER-0001")
    directory = scope.outbox / "MEPHC-FLOW-NEWEST"
    directory.mkdir()
    write_json(directory / "request.json", {"project_id": "MEPHC", "request_id": directory.name})
    write_json(directory / "receipt.json", {"state": "response_received", "request_id": directory.name})
    (directory / "response.txt").write_text("NEXT_WORK_ORDER_ID=MEPHC-NEW-ORDER-0002\n", encoding="utf-8")
    assert flow.resume(scope)["work_order_id"] == "MEPHC-NEW-ORDER-0002"


def test_report_copies_message_bytes_exactly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    scope = paths(tmp_path)
    install_active_order(scope, "NEXT_WORK_ORDER_ID=MEPHC-TEST-WORK-ORDER-0001\n")
    message = tmp_path / "message.txt"
    message.write_bytes(b"line-one\r\nline-two\r\n")

    def fake_courier(_paths, operation, directory, **_kwargs):
        if operation == "run":
            write_json(directory / "receipt.json", {"state": "submission_not_started", "request_id": directory.name})
        return subprocess.CompletedProcess([], 0 if operation == "validate" else 1, "", "")

    monkeypatch.setattr(flow, "courier_command", fake_courier)
    result = flow.report(scope, "MEPHC-TEST-WORK-ORDER-0001", "blocked", message)
    durable = scope.outbox / result["request_id"] / "message.txt"
    assert durable.read_bytes() == message.read_bytes()
    manifest = json.loads((durable.parent / "request.json").read_text(encoding="utf-8"))
    assert manifest["message_sha256"] == flow.sha256_file(durable)


def test_main_push_hook_is_present_and_denies_main() -> None:
    text = (ROOT / ".githooks" / "pre-push").read_text(encoding="utf-8")
    assert "refs/heads/main" in text
    assert "MEPHC_MAIN_PUSH_FORBIDDEN" in text


def test_science_cli_exposes_only_fixed_actions() -> None:
    parser = flow.parser()
    assert parser.parse_args(["science-preflight"]).command == "science-preflight"
    assert parser.parse_args(["science-selftest"]).mpb_smoke is False
    assert parser.parse_args(["science-selftest", "--mpb-smoke"]).mpb_smoke is True
    assert parser.parse_args(["science-acquire"]).command == "science-acquire"
    assert parser.parse_args(["science-analyze"]).command == "science-analyze"
    assert parser.parse_args(["science-status", "MEPHC-SCIENCE-abcdef"]).job_id.startswith("MEPHC-SCIENCE-")
    assert parser.parse_args(["dataset-verify", "a" * 64]).dataset_id == "a" * 64
    assert parser.parse_args(["closeout"]).command == "closeout"
    assert parser.parse_args(["closeout-blocked", "--code", "FIXED_BLOCKER"]).code == "FIXED_BLOCKER"


def test_science_selftest_accepts_bounded_mpb_logs_before_final_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    scope = paths(tmp_path)
    head = "a" * 40
    monkeypatch.setattr(flow, "require_source", lambda *_args, **_kwargs: {"head": head})
    monkeypatch.setattr(flow, "ensure_checkout", lambda *_args, **_kwargs: f"/home/icy/checkouts/{head}")
    payload = {"schema": "mephc-science-runtime-certification-v1", "runtime_sha256": "b" * 64}
    output = "Initializing eigensolver\nfrequency progress\n" + json.dumps(payload) + "\n"
    monkeypatch.setattr(flow, "wsl", lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, output, ""))
    result = flow.science_selftest(scope, mpb_smoke=True)
    assert result["runtime_sha256"] == "b" * 64
    assert result["stdout_size_bytes"] == len(output.encode("utf-8"))


def test_science_selftest_accepts_mpb_logs_after_final_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    scope = paths(tmp_path)
    head = "a" * 40
    monkeypatch.setattr(flow, "require_source", lambda *_args, **_kwargs: {"head": head})
    monkeypatch.setattr(flow, "ensure_checkout", lambda *_args, **_kwargs: f"/home/icy/checkouts/{head}")
    payload = {"schema": "mephc-science-runtime-certification-v1", "runtime_sha256": "b" * 64}
    output = json.dumps(payload) + "\nMPB elapsed time line\n"
    monkeypatch.setattr(flow, "wsl", lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, output, ""))
    assert flow.science_selftest(scope, mpb_smoke=True)["runtime_sha256"] == "b" * 64


def test_science_job_id_binds_actual_execution_source() -> None:
    contract = {
        "contract_sha256": "a" * 64, "source_commit": "b" * 40,
        "entrypoint": "audit/e9f/run.py", "project": ".", "action": "analyze",
    }
    first = flow.science_job_id(contract, "c" * 40)
    second = flow.science_job_id(contract, "d" * 40)
    assert first != second
    assert first == flow.science_job_id(contract, "c" * 40)
