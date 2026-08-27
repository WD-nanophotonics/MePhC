from __future__ import annotations

import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tarfile
import subprocess

import pytest

RUNNER = Path(__file__).parents[1] / "tools" / "mephc-runner"
sys.path.insert(0, str(RUNNER))


def load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, RUNNER / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_active_work_order_allowlist_binds_ids_to_exact_hashes():
    jobctl = load("retention_jobctl_allowlist", "jobctl.py")
    digest = "a" * 64
    text = f"RETENTION_ID=RP3_TEST\nEXPECTED_SHA256={digest}\nAUTHORITATIVE_R96_RESULT_SHA256={'b' * 64}\n"
    assert jobctl._retention_allowlist(text) == {
        "RP3_TEST": digest,
        "AUTHORITATIVE_R96_RESULT": "b" * 64,
    }


def test_search_submission_rejects_unbound_before_job_and_reuses_query(tmp_path, monkeypatch):
    jobctl = load("retention_jobctl_submit", "jobctl.py")
    jobs, certs = tmp_path / "jobs", tmp_path / "certificates"
    jobs.mkdir(); certs.mkdir(); (certs / "doctor.json").write_text("{}")
    digest = "a" * 64
    active = {"active_work_order_id": "WO-RETENTION", "work_order_text":
              f"RETENTION_ID=BOUND_RESULT\nEXPECTED_SHA256={digest}\n"}
    monkeypatch.setattr(jobctl, "JOBS", jobs)
    monkeypatch.setattr(jobctl, "CERTIFICATES", certs)
    monkeypatch.setattr(jobctl.workflow, "active", lambda: active)
    monkeypatch.setattr(jobctl, "git_head", lambda: "b" * 40)
    monkeypatch.setattr(jobctl, "git_origin_main", lambda: jobctl.config.EXPECTED_ORIGIN_MAIN)
    monkeypatch.setattr(jobctl.config, "state_epoch", lambda: "test-epoch")
    monkeypatch.setattr(jobctl, "current_runner_build", lambda: "1" * 16)
    monkeypatch.setattr(jobctl.active_index, "update", lambda *_: None)
    with pytest.raises(jobctl.RetentionRejected, match="RETENTION_BINDING_NOT_IN_ACTIVE_WORK_ORDER"):
        jobctl.submit_retention_search([{"retention_id": "UNBOUND", "expected_sha256": digest}])
    assert list(jobs.iterdir()) == []
    first, reused = jobctl.submit_retention_search(
        [{"retention_id": "BOUND_RESULT", "expected_sha256": digest}])
    assert reused is False
    record = json.loads((first / "job.json").read_text())
    assert record["schema"] == "mephc-runner-job-v3" and record["active_work_order_id"] == "WO-RETENTION"
    assert record["runner_build"] == "1" * 16
    (first / "state.json").write_text('{"state":"succeeded"}')
    second, reused = jobctl.submit_retention_search(
        [{"retention_id": "BOUND_RESULT", "expected_sha256": digest}])
    assert reused is True and second == first


def test_interrupted_search_reuses_same_job_and_requires_explicit_recovery(tmp_path, monkeypatch):
    jobctl = load("retention_jobctl_interrupted", "jobctl.py")
    jobs, certs = tmp_path / "jobs", tmp_path / "certificates"
    jobs.mkdir(); certs.mkdir(); (certs / "doctor.json").write_text("{}")
    digest = "c" * 64
    active = {"active_work_order_id": "WO-RETENTION", "work_order_text":
              f"RETENTION_ID=BOUND_RESULT\nEXPECTED_SHA256={digest}\n"}
    monkeypatch.setattr(jobctl, "JOBS", jobs)
    monkeypatch.setattr(jobctl, "CERTIFICATES", certs)
    monkeypatch.setattr(jobctl.workflow, "active", lambda: active)
    monkeypatch.setattr(jobctl, "git_head", lambda: "b" * 40)
    monkeypatch.setattr(jobctl, "git_origin_main", lambda: jobctl.config.EXPECTED_ORIGIN_MAIN)
    monkeypatch.setattr(jobctl.config, "state_epoch", lambda: "test-epoch")
    monkeypatch.setattr(jobctl, "current_runner_build", lambda: "2" * 16)
    monkeypatch.setattr(jobctl.active_index, "update", lambda *_: None)
    first, _ = jobctl.submit_retention_search(
        [{"retention_id": "BOUND_RESULT", "expected_sha256": digest}])
    (first / "state.json").write_text('{"state":"recovery_required"}')
    second, reused = jobctl.submit_retention_search(
        [{"retention_id": "BOUND_RESULT", "expected_sha256": digest}])
    assert reused is True and second == first
    assert len(list(jobs.iterdir())) == 1


def test_search_finds_regular_and_tar_copies_without_exposing_paths(tmp_path):
    inspector = load("retention_inspector_search", "retention_inspector.py")
    root, job = tmp_path / "root", tmp_path / "job"
    root.mkdir(); job.mkdir()
    data = json.dumps({"value": [1, 2, 3]}).encode()
    digest = hashlib.sha256(data).hexdigest()
    (root / "result.json").write_bytes(data)
    with tarfile.open(root / "recovery.tar.gz", "w:gz") as archive:
        info = tarfile.TarInfo("retained/result.json"); info.size = len(data)
        archive.addfile(info, io.BytesIO(data))
        unsafe = tarfile.TarInfo("../secrets/result.json"); unsafe.size = len(data)
        archive.addfile(unsafe, io.BytesIO(data))
    result = inspector.search_bindings(
        [{"retention_id": "TEST_RESULT", "expected_sha256": digest}],
        [("TEST_ROOT", root)], job, deadline=__import__("time").time() + 10,
    )
    artifact = result["artifacts"][0]
    assert result["exhaustive"] is True and artifact["status"] == "FOUND_EXACT"
    assert artifact["copy_count"] == 2
    public = json.dumps({key: value for key, value in result.items() if key != "internal_locators"})
    assert str(root) not in public and "retained/result.json" not in public


def test_search_timeout_is_incomplete_not_exhaustive(tmp_path):
    inspector = load("retention_inspector_timeout", "retention_inspector.py")
    root, job = tmp_path / "root", tmp_path / "job"
    root.mkdir(); job.mkdir(); (root / "x.json").write_text("{}")
    result = inspector.search_bindings(
        [{"retention_id": "TEST", "expected_sha256": "a" * 64}],
        [("TEST", root)], job, deadline=0,
    )
    assert result["exhaustive"] is False
    assert result["error_code"] == "SEARCH_INCOMPLETE"
    assert result["artifacts"][0]["status"] == "SEARCH_INCOMPLETE"


@pytest.mark.skipif(not Path("/usr/bin/git").is_file(), reason="WSL Git bundle fixture")
def test_search_and_inspect_exact_blob_from_git_recovery_bundle(tmp_path, monkeypatch):
    inspector = load("retention_inspector_bundle", "retention_inspector.py")
    repo, root, job = tmp_path / "repo", tmp_path / "root", tmp_path / "job"
    repo.mkdir(); root.mkdir(); job.mkdir()
    data = b'{"bundle_value":42}'
    subprocess.run(["/usr/bin/git", "-C", str(repo), "init", "-q"], check=True)
    subprocess.run(["/usr/bin/git", "-C", str(repo), "config", "user.name", "Fixture"], check=True)
    subprocess.run(["/usr/bin/git", "-C", str(repo), "config", "user.email", "fixture@example.invalid"], check=True)
    (repo / "retained.json").write_bytes(data)
    subprocess.run(["/usr/bin/git", "-C", str(repo), "add", "retained.json"], check=True)
    subprocess.run(["/usr/bin/git", "-C", str(repo), "commit", "-qm", "fixture"], check=True)
    bundle = root / "recovery.bundle"
    subprocess.run(["/usr/bin/git", "-C", str(repo), "bundle", "create", str(bundle), "HEAD"], check=True)
    digest = hashlib.sha256(data).hexdigest()
    result = inspector.search_bindings(
        [{"retention_id": "BUNDLE_RESULT", "expected_sha256": digest}],
        [("RECOVERY", root)], job, deadline=__import__("time").time() + 30,
    )
    assert result["artifacts"][0]["status"] == "FOUND_EXACT"
    assert any(value["kind"] == "git" for value in result["internal_locators"].values())


def _inspection_fixture(tmp_path, monkeypatch):
    inspector = load("retention_inspector_read", "retention_inspector.py")
    data = json.dumps({"path": "/home/icy/private/result.json", "email": "person@example.com",
                       "values": [1.0, 2.0, 0.0]}).encode()
    digest = hashlib.sha256(data).hexdigest()
    retained = tmp_path / "retained.json"; retained.write_bytes(data)
    job_id = "MEPHC-JOB-TESTRETENTION"
    job = tmp_path / job_id; job.mkdir()
    (job / "job.json").write_text(json.dumps({"schema": "mephc-runner-job-v3",
        "operation": "retention_search", "retention_query": {"bindings": [
        {"retention_id": "TEST_RESULT", "expected_sha256": digest}
    ]}}))
    (job / "retention-search-result.json").write_text(json.dumps({
        "artifacts": [{"retention_id": "TEST_RESULT", "status": "FOUND_EXACT",
                       "opaque_locators": ["RET-OPAQUE"]}],
        "internal_locators": {"RET-OPAQUE": {"kind": "file", "path": str(retained)}},
    }))
    monkeypatch.setattr(inspector.config, "JOBS", tmp_path)
    return inspector, job_id, retained


def test_inspect_redacts_host_identity_pages_and_summarizes_numbers(tmp_path, monkeypatch):
    inspector, job_id, _ = _inspection_fixture(tmp_path, monkeypatch)
    page = inspector.inspect(job_id, "TEST_RESULT", "json_page")
    assert page["value"]["path"] == "<HOST_REDACTED>/private/result.json"
    assert page["value"]["email"] == "<HOST_REDACTED>"
    summary = inspector.inspect(job_id, "TEST_RESULT", "numeric_summary", "/values")
    assert summary["numeric_count"] == 3 and summary["finite_count"] == 3
    assert summary["nonzero_count"] == 2 and summary["l2_norm"] == pytest.approx(5 ** 0.5)
    assert summary["shape"] == [3]


def test_inspect_page_bounds_and_invalid_json_fail_closed(tmp_path, monkeypatch):
    inspector, job_id, retained = _inspection_fixture(tmp_path, monkeypatch)
    with pytest.raises(inspector.RetentionError, match="RETENTION_PAGE_INVALID"):
        inspector.inspect(job_id, "TEST_RESULT", "json_page", limit=inspector.PAGE_LIMIT + 1)
    invalid = b"not-json"
    retained.write_bytes(invalid)
    job = tmp_path / job_id
    record = json.loads((job / "job.json").read_text())
    record["retention_query"]["bindings"][0]["expected_sha256"] = hashlib.sha256(invalid).hexdigest()
    (job / "job.json").write_text(json.dumps(record))
    with pytest.raises(inspector.RetentionError, match="RETENTION_JSON_INVALID"):
        inspector.inspect(job_id, "TEST_RESULT", "outline")


def test_search_skips_symlink_escape(tmp_path):
    inspector = load("retention_inspector_symlink", "retention_inspector.py")
    root, outside, job = tmp_path / "root", tmp_path / "outside.json", tmp_path / "job"
    root.mkdir(); job.mkdir(); outside.write_text('{"secret":1}')
    link = root / "linked.json"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation unavailable")
    digest = hashlib.sha256(outside.read_bytes()).hexdigest()
    result = inspector.search_bindings(
        [{"retention_id": "ESCAPE", "expected_sha256": digest}], [("ROOT", root)], job,
        deadline=__import__("time").time() + 10,
    )
    assert result["artifacts"][0]["status"] == "NOT_FOUND_EXHAUSTIVE"


def test_inspect_rehashes_and_rejects_byte_drift(tmp_path, monkeypatch):
    inspector, job_id, retained = _inspection_fixture(tmp_path, monkeypatch)
    retained.write_text('{"changed":true}')
    with pytest.raises(inspector.RetentionError, match="RETENTION_BYTE_DRIFT"):
        inspector.inspect(job_id, "TEST_RESULT", "metadata")


def test_inspect_missing_and_unfinished_jobs_are_structured(tmp_path, monkeypatch):
    inspector = load("retention_inspector_missing", "retention_inspector.py")
    monkeypatch.setattr(inspector.config, "JOBS", tmp_path)
    with pytest.raises(inspector.RetentionError, match="RETENTION_SEARCH_JOB_NOT_FOUND"):
        inspector.inspect("MEPHC-JOB-NOTFOUND123", "TEST_RESULT", "metadata")
    job = tmp_path / "MEPHC-JOB-NOTREADY123"; job.mkdir()
    (job / "job.json").write_text(json.dumps({"schema": "mephc-runner-job-v3",
                                               "operation": "retention_search",
                                               "retention_query": {"bindings": []}}))
    with pytest.raises(inspector.RetentionError, match="RETENTION_SEARCH_NOT_READY"):
        inspector.inspect(job.name, "TEST_RESULT", "metadata")


def test_admission_replays_inspect_but_never_search():
    source = (Path(__file__).parents[1] / "tools/mephc-admission/mephc_admission.py").read_text(encoding="utf-8")
    readonly = source.split("READ_ONLY_TOOLS =", 1)[1].split("}", 1)[0]
    assert "mephc_retention_inspect" in readonly
    assert "mephc_retention_search" not in readonly
