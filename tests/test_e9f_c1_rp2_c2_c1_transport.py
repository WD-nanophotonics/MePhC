from __future__ import annotations

import json
from pathlib import Path
import time
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from audit.e9f import run_e9f_c1_rp2_c2_c1 as transport


def _slot(tmp_path: Path, name: str = "worker") -> dict[str, Path]:
    directory = tmp_path / name
    directory.mkdir()
    return {"directory": directory, "payload": directory / "payload.json", "binding": directory / "binding.json"}


def _fake_command(slot: dict[str, Path], payload: object, stdout: str = "diagnostic") -> list[str]:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    code = (
        "import pathlib,sys;"
        "p=pathlib.Path(sys.argv[1]);"
        "p.write_bytes((" + repr(encoded + "\n") + ").encode());"
        "print(sys.argv[2]);"
        "print('{\"arbitrary\":true}');"
        "print('stderr-diagnostic', file=sys.stderr)"
    )
    return [sys.executable, "-c", code, str(slot["payload"]), stdout]


def test_frozen_scientific_objects_and_agents_are_unchanged():
    hashes = transport.verify_frozen_inputs(ROOT)
    assert hashes["scientific_impl_git_blob_sha"] == "a4d66bb5174306d5b45d95fc0bcd64860a98ca47"
    assert hashes["scientific_contract_sha256"] == "f1656a023469f8596afab00faddcc5b6cefddfd919dbad7e8b68ed625df79e65"


def test_exact_real_provider_module_resolution():
    code = (
        "import importlib; "
        "m=importlib.import_module('audit.e9c.run_k_kprime_rank1_berry'); "
        "assert all(callable(getattr(m, n, None)) for n in ('build_inputs','geometry_inputs','make_provider'))"
    )
    subprocess.check_call([sys.executable, "-c", code], cwd=ROOT)


def test_hostile_stdout_payload_is_accepted_and_stdout_is_not_parsed(tmp_path: Path):
    payload = {"schema": "fake", "value": 7}
    first = _slot(tmp_path, "first")
    second = _slot(tmp_path, "second")
    _, m1 = transport.run_file_backed_child(_fake_command(first, payload, "text { not-json }"), "first", first)
    _, m2 = transport.run_file_backed_child(_fake_command(second, payload, "second-json {\"x\":1}"), "second", second)
    assert m1["worker_payload_sha256"] == m2["worker_payload_sha256"]
    assert m1["child_stdout_byte_count"] != m2["child_stdout_byte_count"]
    assert "json.loads(stdout)" not in Path(transport.__file__).read_text(encoding="utf-8")


def test_missing_final_payload_fails_closed(tmp_path: Path):
    slot = _slot(tmp_path)
    command = [sys.executable, "-c", "print('valid-looking-json {\"x\":1}')"]
    with pytest.raises(transport.PayloadChannelError, match="FINAL_MISSING"):
        transport.run_file_backed_child(command, "missing", slot)


def test_nonzero_child_fails_closed_without_payload(tmp_path: Path):
    command = [
        sys.executable,
        "-c",
        "import time; time.sleep(3)",
        "run_e9f_c1_rp2_c2_c1_worker.py",
        "--worker-id",
        "orphan-test",
    ]
    child = subprocess.Popen(command)
    try:
        time.sleep(0.15)
        assert child.pid in transport.scan_transport_processes("orphan-test")
    finally:
        child.terminate()
        child.wait(timeout=5)

    slot = _slot(tmp_path)
    command = [sys.executable, "-c", "import sys; print('diagnostic'); sys.exit(3)"]
    with pytest.raises(transport.PayloadChannelError, match="NATIVE_CHILD_FAILED"):
        transport.run_file_backed_child(command, "failed", slot)


def test_malformed_payload_fails_closed(tmp_path: Path):
    slot = _slot(tmp_path)
    command = [sys.executable, "-c", f"open({str(slot['payload'])!r},'wb').write(b'{{bad')"]
    with pytest.raises(transport.PayloadChannelError, match="MALFORMED"):
        transport.run_file_backed_child(command, "malformed", slot)


def test_partial_temporary_payload_without_final_fails_closed(tmp_path: Path):
    slot = _slot(tmp_path)
    code = f"open({str(slot['directory'] / '.payload.json.fake.tmp')!r},'wb').write(b'partial')"
    with pytest.raises(transport.PayloadChannelError, match="TEMP_EXISTS"):
        transport.run_file_backed_child([sys.executable, "-c", code], "partial", slot)


def test_preexisting_final_file_is_rejected_before_launch(tmp_path: Path):
    runtime = tmp_path / "runtime"
    slot = transport.transport_slot(runtime, "worker")
    slot["directory"].mkdir(parents=True)
    slot["payload"].write_bytes(b"{}\n")
    with pytest.raises((transport.PayloadChannelError, FileExistsError)):
        transport.prepare_transport_slot(runtime, {"sample_id": "worker", "resolution": 64}, "sha")


def _identity_validator(item: dict[str, object]) -> None:
    expected = {
        "worker_id": "worker",
        "resolution": 64,
        "transport_execution_git_sha": "sha",
        "scientific_contract_sha256": "contract",
        "schema": "fake",
    }
    for key, value in expected.items():
        if item.get(key) != value:
            raise transport.PayloadChannelError("IDENTITY_MISMATCH")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("worker_id", "wrong"),
        ("resolution", 96),
        ("transport_execution_git_sha", "wrong-sha"),
        ("schema", "wrong-schema"),
        ("scientific_contract_sha256", "wrong-contract"),
    ],
)
def test_payload_identity_fields_are_validated(tmp_path: Path, field: str, value: object):
    payload = {
        "schema": "fake",
        "worker_id": "worker",
        "resolution": 64,
        "transport_execution_git_sha": "sha",
        "scientific_contract_sha256": "contract",
    }
    payload[field] = value
    slot = _slot(tmp_path)
    slot["payload"].write_bytes(transport.canonical_json(payload))
    with pytest.raises(transport.PayloadChannelError, match="IDENTITY"):
        transport.read_payload_file(slot, validator=_identity_validator)


def test_nonfinite_payload_fails_closed(tmp_path: Path):
    slot = _slot(tmp_path)
    slot["payload"].write_text('{"value":NaN}\n', encoding="utf-8")
    with pytest.raises(transport.PayloadChannelError, match="NONFINITE"):
        transport.read_payload_file(slot)


def test_stdout_json_never_fallbacks_when_payload_invalid(tmp_path: Path):
    slot = _slot(tmp_path)
    command = [sys.executable, "-c", "print('{\"scientific\":\"valid\"}')"]
    with pytest.raises(transport.PayloadChannelError, match="FINAL_MISSING"):
        transport.run_file_backed_child(command, "fallback", slot)


def test_failure_metric_is_retained_before_parent_gate():
    metric = {
        "NOMINAL_Q": [0.0, 0.0],
        "GRAM_DECOMPOSITION_CLOSURE_MAX": 2e-12,
        "GRAM_DECOMPOSITION_CLOSURE_TOL": 1e-12,
        "GRAM_DECOMPOSITION_CLOSURE_PASS": False,
    }
    payload = {
        "primary": {
            "center": metric,
            "stencils": {"1/72": {"vertices": []}, "1/144": {"vertices": []}},
        },
        "control": {"center": metric},
        "closure_failures": [{
            "NOMINAL_Q": [0.0, 0.0],
            "MEASURED_VALUE": 2e-12,
            "THRESHOLD_VALUE": 1e-12,
        }],
    }
    transport._validate_failure_metrics(payload)
    payload["closure_failures"] = []
    with pytest.raises(transport.PayloadChannelError, match="FAILURE_METRIC"):
        transport._validate_failure_metrics(payload)


def test_parent_is_solver_free_and_transport_contract_is_exact():
    contract = transport.load_contract(ROOT)
    assert contract["payload_transport"] == "ATOMIC_FILE"
    assert contract["stdout_used_as_payload"] is False
    assert "meep" not in sys.modules
