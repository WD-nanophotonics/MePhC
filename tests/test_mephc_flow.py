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
