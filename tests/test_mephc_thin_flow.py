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


def test_closeout_launcher_is_zero_argument_and_fixed():
    launcher = (ROOT / "mephc-closeout.cmd").read_text(encoding="utf-8").lower()
    assert 'if not "%~1"==""' in launcher
    assert 'mephc-flow.cmd" closeout' in launcher
    for forbidden in ("%*", "courier-reconcile", "message-file", "browser", "chrome"):
        assert forbidden not in launcher


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


def test_missing_dataset_blocks_before_native(monkeypatch, tmp_path: Path):
    scope = paths(tmp_path)
    value = contract(inputs={
        "tests": ["tests/test_mephc_thin_flow.py"],
        "datasets": [{"dataset_id": "a" * 64, "manifest_sha256": "b" * 64,
                      "record_key_sha256": "c" * 64}],
    })
    monkeypatch.setattr(flow, "state_view", lambda _: {"state": "READY"})
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
