from pathlib import Path

import pytest

from tools.mephc_runner_loader import load_runner_module

planner = load_runner_module("plan_windows_copy_cleanup")


def fixture(classification="AMBIGUOUS_FAIL_CLOSED"):
    root = planner.COPY_ROOTS["AGENTRELAY"]
    retention = {
        "copy_roots": [{
            "project_id": "AGENTRELAY",
            "path": str(root),
            "files": [{
                "path": "evidence.json",
                "bytes": 3,
                "sha256": "a" * 64,
                "classification": classification,
            }],
        }]
    }
    manifest = {
        "artifact_id": "ARCHIVE-001",
        "archive_commit": "b" * 40,
        "payloads": [{"path": "payload/chunk.tar.gz", "bytes": 2, "sha256": "c" * 64}],
        "files": [{
            "project_id": "AGENTRELAY",
            "original_path": "evidence.json",
            "bytes": 3,
            "sha256": "a" * 64,
        }],
    }
    return retention, manifest


def test_ambiguous_path_requires_exact_archive_binding():
    retention, manifest = fixture()
    manifest["files"][0]["sha256"] = "d" * 64
    with pytest.raises(RuntimeError, match="UNRETAINED_AMBIGUOUS_PATH"):
        planner.build_plan(retention, manifest, "e" * 40)


def test_plan_binds_exact_files_payload_and_hash():
    retention, manifest = fixture()
    plan = planner.build_plan(retention, manifest, "e" * 40)
    assert plan["copy_root_file_count"] == 1
    assert plan["payload_retirement_count"] == 1
    assert plan["execution_authorized"] is False
    claimed = plan.pop("plan_sha256")
    assert claimed == planner.canonical_sha256(plan)


def test_secret_or_unknown_classification_is_rejected():
    retention, manifest = fixture("SECRET_OR_CREDENTIAL")
    with pytest.raises(RuntimeError, match="UNSAFE_CLASSIFICATION"):
        planner.build_plan(retention, manifest, "e" * 40)


def test_planner_has_no_delete_primitive():
    text = Path(planner.__file__).read_text(encoding="utf-8")
    for forbidden in (".unlink(", "rmtree(", "remove(", "git clean", "git reset"):
        assert forbidden not in text
