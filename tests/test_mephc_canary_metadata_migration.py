from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
SOURCE = ROOT / "tools" / "mephc-runner" / "migrate_canary_metadata.py"


def load():
    spec = importlib.util.spec_from_file_location("canary_metadata_migration", SOURCE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def request_fixture(module, tmp_path: Path) -> tuple[str, Path]:
    request_id = "MEPHC-INFRA-CANARY-" + "A" * 24
    module.config.OUTBOX = tmp_path / "outbox"
    module.config.RUNTIME = tmp_path / "runner"
    request_dir = module.config.OUTBOX / request_id
    request_dir.mkdir(parents=True)
    key = "a" * 64
    manifest = {
        "version": 1, "project_id": "MEPHC", "request_id": request_id,
        "message_file": "message.txt", "attachments": [], "transport_canary": True,
        "task_difficulty": "normal", "instruction_level": "low",
        "workflow_window_seconds": 600, "transport_canary_idempotency_key": key,
    }
    (request_dir / "request.json").write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
    (request_dir / "message.txt").write_text(
        "MEPHC infrastructure transport canary. No scientific task or content. "
        f"CANARY_BINDING={key}\nReply exactly: MEPHC_TRANSPORT_CANARY_OK={key}\n",
        encoding="utf-8",
    )
    return request_id, request_dir


def test_migrates_only_incompatible_enums_and_writes_hash_receipt(tmp_path):
    module = load()
    request_id, request_dir = request_fixture(module, tmp_path)
    before = json.loads((request_dir / "request.json").read_text(encoding="utf-8"))
    result = module.migrate(request_id, True)
    after = json.loads((request_dir / "request.json").read_text(encoding="utf-8"))
    assert {key: value for key, value in after.items() if key != "instruction_level"} == {
        key: value for key, value in before.items() if key != "instruction_level"
    }
    assert after["instruction_level"] == "normal"
    assert result["changes"] == {"instruction_level": {"before": "low", "after": "normal"}}
    assert result["request_sha256_before"] != result["request_sha256_after"]
    receipt = Path(result["migration_receipt"])
    assert receipt.is_file() and json.loads(receipt.read_text(encoding="utf-8"))["applied"] is True


def test_audit_mode_does_not_modify_request(tmp_path):
    module = load()
    request_id, request_dir = request_fixture(module, tmp_path)
    before = (request_dir / "request.json").read_bytes()
    result = module.migrate(request_id, False)
    assert result["applied"] is False
    assert (request_dir / "request.json").read_bytes() == before


@pytest.mark.parametrize("evidence", ["receipt.json", "response.txt"])
def test_rejects_transport_evidence(tmp_path, evidence):
    module = load()
    request_id, request_dir = request_fixture(module, tmp_path)
    (request_dir / evidence).write_text("evidence\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="CANARY_ALREADY_ENTERED_TRANSPORT"):
        module.migrate(request_id, True)


def test_rejects_request_submitted_event(tmp_path):
    module = load()
    request_id, request_dir = request_fixture(module, tmp_path)
    (request_dir / "events.jsonl").write_text('{"event":"request_submitted"}\n', encoding="utf-8")
    with pytest.raises(RuntimeError, match="CANARY_ALREADY_SUBMITTED"):
        module.migrate(request_id, True)


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("workflow_window_seconds", 0, "CANARY_WORKFLOW_WINDOW_INVALID"),
        ("queue_wait_seconds", 7201, "CANARY_QUEUE_WAIT_INVALID"),
        ("task_difficulty", "easy", "CANARY_TASK_DIFFICULTY_INVALID"),
        ("instruction_level", "brief", "CANARY_INSTRUCTION_LEVEL_INVALID"),
    ],
)
def test_rejects_other_courier_schema_drift(tmp_path, field, value, error):
    module = load()
    request_id, request_dir = request_fixture(module, tmp_path)
    path = request_dir / "request.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest[field] = value
    path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match=error):
        module.migrate(request_id, True)


def test_factory_uses_courier_supported_difficulty():
    text = (ROOT / "tools" / "mephc-runner" / "mcp_server.py").read_text(encoding="utf-8")
    factory = text[text.index("def transport_canary"):]
    assert '"task_difficulty": "normal"' in factory
    assert '"task_difficulty": "low"' not in factory
    assert '"instruction_level": "normal"' in factory
    assert '"instruction_level": "low"' not in factory
