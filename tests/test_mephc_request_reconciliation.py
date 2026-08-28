from __future__ import annotations

import io
import json
from pathlib import Path
import sys

RUNNER = Path(__file__).parents[1] / "tools" / "mephc-runner"
if str(RUNNER) not in sys.path:
    sys.path.insert(0, str(RUNNER))

import admission_requests
import jobctl
import mcp_server


def test_legacy_system_exit_is_a_request_rejection_and_mcp_survives(monkeypatch):
    requests = [
        {"jsonrpc":"2.0", "id":1, "method":"tools/call",
         "params":{"name":"mephc_native", "arguments":{"recipe_id":"missing"}}},
        {"jsonrpc":"2.0", "id":2, "method":"ping"},
    ]
    original = mcp_server.invoke_captured
    calls = {"count": 0}
    def fake(name, args):
        calls["count"] += 1
        if calls["count"] == 1:
            raise SystemExit("native recipe is not registered")
        return original(name, args)
    stdin = io.StringIO("".join(json.dumps(item) + "\n" for item in requests))
    stdout = io.StringIO()
    monkeypatch.setattr(mcp_server, "invoke_captured", fake)
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "stdout", stdout)
    mcp_server.main()
    replies = [json.loads(line) for line in stdout.getvalue().splitlines()]
    first = json.loads(replies[0]["result"]["content"][0]["text"])
    assert first["job_created"] is False
    assert first["failure_layer"] == "request_validation"
    assert replies[1]["result"] == {}


def test_request_envelope_binds_job_before_ready_and_finds_terminal(tmp_path, monkeypatch):
    request_root = tmp_path / "requests"
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    monkeypatch.setattr(admission_requests, "ROOT", request_root)
    monkeypatch.setattr(admission_requests.config, "JOBS", jobs)
    request_id = "a" * 32
    admission_requests.begin(request_id, "mephc_native", {"recipe_id":"r1"},
                             source_commit="1" * 40, runner_build="build", state_epoch="epoch")
    job = jobs / "MEPHC-JOB-TEST"
    job.mkdir()
    admission_requests.bind_job(request_id, job.name)
    (job / "state.json").write_text(json.dumps({"state":"succeeded", "operation":"native", "phase":"terminal"}), encoding="utf-8")
    status = admission_requests.status(request_id)
    assert status["job_created"] is True
    assert status["job_id"] == job.name
    assert status["terminal_state"] == "succeeded"
    assert status["native_process_started"] is False


def test_empty_native_registry_rejects_before_job(tmp_path, monkeypatch):
    registry = tmp_path / "native-recipes.json"
    registry.write_text('{"schema":"mephc-native-recipes-v1","recipes":{}}', encoding="utf-8")
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    monkeypatch.setattr(jobctl, "NATIVE_RECIPES", registry)
    monkeypatch.setattr(jobctl, "JOBS", jobs)
    monkeypatch.setattr(jobctl, "RUNTIME", tmp_path / "runtime")
    try:
        jobctl.submit_native("anything")
    except jobctl.RunnerRequestRejected as exc:
        assert exc.error_code == "WORK_ORDER_BLOCKED_MISSING_NATIVE_RECIPE"
        assert exc.safe_next_tool == "mephc_work_order_preflight"
    else:
        raise AssertionError("empty registry was accepted")
    assert list(jobs.iterdir()) == []


def test_request_status_is_advertised_read_only():
    names = {item["name"] for item in mcp_server.READONLY_TOOLS}
    assert "mephc_request_status" in names


def test_legacy_native_contract_requires_id_hash_and_budget():
    import work_order_contract
    digest = "1" * 64
    text = "\n".join([
        "NATIVE_RECIPE_ID=r8-stage-b",
        f"NATIVE_RECIPE_SHA256={digest}",
        "NATIVE_MAX_INVOCATIONS=1",
    ])
    value = work_order_contract.parse(text, "MEPHC-R8-TEST")
    assert value["native_recipes"] == [{"recipe_id":"r8-stage-b", "recipe_sha256":digest,
                                         "max_invocations":1}]


def test_machine_v2_native_contract_is_hash_bound():
    import work_order_contract
    raw = {"schema":"mephc-work-order-contract-v2", "work_order_id":"MEPHC-R8-TEST",
           "required_capabilities":["native.execute"], "authorized_actions":["native.execute"],
           "retention_bindings":[],
           "native_recipes":[{"recipe_id":"r8-stage-b", "recipe_sha256":"2" * 64,
                              "max_invocations":2}]}
    first = work_order_contract.validate(raw)
    raw["native_recipes"][0]["max_invocations"] = 3
    second = work_order_contract.validate(raw)
    assert first["contract_sha256"] != second["contract_sha256"]


def test_active_index_preserves_but_does_not_index_pre_manifest_residue(tmp_path):
    import active_index
    jobs = tmp_path / "jobs"
    residue = jobs / "MEPHC-JOB-RESIDUE"
    residue.mkdir(parents=True)
    assert active_index.rebuild(jobs) == {}
    assert residue.is_dir()


def test_active_index_keeps_explicit_migrated_orphan_visible(tmp_path):
    import active_index
    jobs = tmp_path / "jobs"
    orphan_id = next(iter(active_index.LEGACY_DURABLE_ORPHANS))
    (jobs / orphan_id).mkdir(parents=True)
    value = active_index.rebuild(jobs)
    assert value == {orphan_id:{"state":"unknown", "operation":None}}


def test_failed_native_never_authorizes_a_new_job():
    import job_semantics
    value = job_semantics.enrich("failed", "native", "CHILD_PROCESS_FAILED", "terminal")
    assert value["retry_allowed"] is False
    assert value["same_job_recovery_allowed"] is False
    assert value["new_job_allowed"] is False


def test_disconnect_before_job_is_explicit_and_never_retryable(tmp_path, monkeypatch):
    monkeypatch.setattr(admission_requests, "ROOT", tmp_path / "requests")
    monkeypatch.setattr(admission_requests.config, "JOBS", tmp_path / "jobs")
    request_id = "b" * 32
    admission_requests.begin(request_id, "mephc_native", {"recipe_id":"r1"},
                             source_commit="1" * 40, runner_build="build", state_epoch="epoch")
    value = admission_requests.disconnected(request_id)
    assert value["phase"] == "disconnected_before_job"
    assert value["job_created"] is False
    assert value["retry_allowed"] is False
    assert value["new_job_allowed"] is False


def test_request_status_distinguishes_native_start_marker(tmp_path, monkeypatch):
    monkeypatch.setattr(admission_requests, "ROOT", tmp_path / "requests")
    jobs = tmp_path / "jobs"
    monkeypatch.setattr(admission_requests.config, "JOBS", jobs)
    request_id = "c" * 32
    admission_requests.begin(request_id, "mephc_native", {"recipe_id":"r1"},
                             source_commit="1" * 40, runner_build="build", state_epoch="epoch")
    job = jobs / "MEPHC-JOB-NATIVE"
    job.mkdir(parents=True)
    admission_requests.bind_job(request_id, job.name)
    (job / "state.json").write_text(json.dumps({"state":"running", "operation":"native",
                                                  "phase":"native_process_starting"}), encoding="utf-8")
    assert admission_requests.status(request_id)["native_process_started"] is False
    (job / "native-lifecycle.json").write_text(json.dumps({"schema":"mephc-native-lifecycle-v1",
                                                             "native_process_started":True,
                                                             "phase":"native_process_started"}), encoding="utf-8")
    assert admission_requests.status(request_id)["native_process_started"] is True


def test_native_recipe_hash_mismatch_rejected_before_job(tmp_path, monkeypatch):
    recipe = {"argv":["/usr/bin/true"]}
    registry = tmp_path / "native-recipes.json"
    registry.write_text(json.dumps({"schema":"mephc-native-recipes-v1", "recipes":{"r1":recipe}}), encoding="utf-8")
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    monkeypatch.setattr(jobctl, "NATIVE_RECIPES", registry)
    monkeypatch.setattr(jobctl, "JOBS", jobs)
    monkeypatch.setattr(jobctl, "RUNTIME", tmp_path / "runtime")
    monkeypatch.setattr(jobctl.workflow, "active", lambda: {
        "active_work_order_id":"MEPHC-R8-TEST",
        "work_order_text":"NATIVE_RECIPE_ID=r1\nNATIVE_RECIPE_SHA256=" + "f" * 64 + "\nNATIVE_MAX_INVOCATIONS=1\n",
    })
    try:
        jobctl.submit_native("r1")
    except jobctl.RunnerRequestRejected as exc:
        assert exc.error_code == "NATIVE_RECIPE_HASH_MISMATCH"
    else:
        raise AssertionError("mismatched native recipe hash was accepted")
    assert list(jobs.iterdir()) == []
