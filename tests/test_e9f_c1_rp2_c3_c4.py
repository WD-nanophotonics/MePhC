from __future__ import annotations

import json
from pathlib import Path

import pytest

from audit.e9f import c3_c4_runtime as runtime
from audit.e9f import run_e9f_c1_rp2_c3_c2_impl as science
from audit.e9f import run_e9f_c1_rp2_c3_c4 as runner
from tests.test_e9f_c1_rp2_c3_c3 import fake_payload

ROOT = Path(__file__).resolve().parents[1]
ROW = next(row for row in science.build_plan(ROOT) if row["sample_id"].endswith("::resolution=64"))


def raw_science_fixture():
    value, _ = fake_payload()
    raw = dict(value)
    for key in ("execution_sha", "contract_sha256", "phase", "c3_c3_transport_binding", "payload_body_sha256", "payload_transport"):
        raw.pop(key, None)
    raw["schema"] = "mephc_e9f_c1_rp2_c3_c2_worker_v1"
    raw["work_order_id"] = "MEPHC-E9F-C1-RP2-C3-C2-20260825-242"
    raw["execution_git_sha"] = "legacy-execution-sha"
    raw["rp1_policy_sha256"] = "legacy-policy-sha"
    return raw


def identity():
    return runtime.identity_for(row=ROW, execution_sha="e" * 40, contract_sha256="c" * 64, policy_sha256="p" * 64)


def finalized():
    expected = identity()
    return runtime.finalize_payload(raw_science_fixture(), row=ROW, expected_identity=expected), expected


def test_raw_science_fixture_omits_canonical_execution_identity():
    raw = raw_science_fixture()
    assert "execution_sha" not in raw and "contract_sha256" not in raw


def test_finalize_payload_adds_execution_sha():
    payload, expected = finalized()
    assert payload["execution_sha"] == expected["execution_sha"]


def test_finalize_payload_adds_contract_sha256():
    payload, expected = finalized()
    assert payload["contract_sha256"] == expected["contract_sha256"]


def test_finalize_payload_adds_all_canonical_identity_fields():
    payload, expected = finalized()
    assert all(payload.get(key) == expected[key] for key in runtime.CANONICAL_IDENTITY_FIELDS)


def test_finalize_payload_binding_equals_top_level_identity():
    payload, expected = finalized()
    assert payload["c3_c4_transport_binding"] == expected


def test_real_worker_finalize_path_produces_parent_acceptable_payload(tmp_path):
    payload, expected = finalized()
    path = tmp_path / "payload.json"; path.write_bytes(runtime.canonical(payload))
    runtime.validate_payload(json.loads(path.read_text()), row=ROW, expected_identity=expected)


def test_real_worker_finalize_path_rejects_wrong_execution():
    payload, expected = finalized(); payload["execution_sha"] = "wrong"
    with pytest.raises(ValueError, match="TOP_LEVEL_IDENTITY"):
        runtime.validate_payload(payload, row=ROW, expected_identity=expected)


def test_real_worker_finalize_path_rejects_wrong_contract():
    payload, expected = finalized(); payload["c3_c4_transport_binding"]["contract_sha256"] = "wrong"
    with pytest.raises(ValueError, match="BINDING_IDENTITY"):
        runtime.validate_payload(payload, row=ROW, expected_identity=expected)


def test_end_to_end_parent_publication_uses_shared_finalizer(tmp_path):
    payload, expected = finalized(); path = tmp_path / "worker/payload.json"; path.parent.mkdir(); path.write_bytes(runtime.canonical(payload))
    published = runtime.publish_artifacts(runtime_root=tmp_path / "runtime", payload=payload, measurement={"payload_path": str(path), "return_code": 0, "direct_pid_gone": True, "orphan_count": 0}, expected_identity=expected, runner_sha256="r" * 64)
    assert Path(published["manifest_path"]).is_file() and published["payload_file_sha256"] != published["payload_body_sha256"]


def test_legacy_execution_git_sha_cannot_conflict():
    raw = raw_science_fixture(); expected = identity(); raw["execution_git_sha"] = "conflict"
    payload = runtime.finalize_payload(raw, row=ROW, expected_identity=expected)
    assert "execution_git_sha" not in payload


def test_h_norm_gate_accepts_below_1e14():
    payload, _ = finalized(); payload["all_point_metrics"][0]["H_GATE"]["max_normalization_error"] = 0.9e-14
    runtime.validate_h_gates(payload)


def test_h_norm_gate_rejects_above_1e14():
    payload, _ = finalized(); payload["all_point_metrics"][0]["H_GATE"]["max_normalization_error"] = 1.1e-14
    with pytest.raises(ValueError, match="NORMALIZATION"):
        runtime.validate_h_gates(payload)


def test_contract_rejects_norm_tolerance_1e10():
    value = json.loads((ROOT / "audit/e9f/rp2_c3_c4_execution_contract.json").read_text()); value["h_gate"]["normalization_tolerance"] = 1e-10
    path = ROOT / "audit/e9f/rp2_c3_c4_execution_contract.json"
    assert value["h_gate"]["normalization_tolerance"] != json.loads(path.read_text())["h_gate"]["normalization_tolerance"]


def test_contract_requires_norm_tolerance_1e14():
    value = json.loads((ROOT / "audit/e9f/rp2_c3_c4_execution_contract.json").read_text())
    assert value["h_gate"]["normalization_tolerance"] == 1e-14


def review(): return json.loads((ROOT / "audit/e9f/c3_c4_process_reliability_review.json").read_text())


@pytest.mark.parametrize("incident_id", ["REL-036", "REL-037", "REL-038"])
def test_process_review_missing_required_incident_rejected(incident_id):
    value = review(); value["incidents"] = [item for item in value["incidents"] if item["incident_id"] != incident_id]
    value["p1_items"] = [item for item in value["p1_items"] if item != incident_id]
    with pytest.raises(ValueError, match="REGISTRY"):
        runtime.validate_process_review(value)


def test_process_review_missing_REL036_rejected():
    test_process_review_missing_required_incident_rejected("REL-036")


def test_process_review_missing_REL037_rejected():
    test_process_review_missing_required_incident_rejected("REL-037")


def test_process_review_missing_REL038_rejected():
    test_process_review_missing_required_incident_rejected("REL-038")


def test_process_review_missing_any_contract_incident_rejected():
    value = review(); value["incidents"].pop()
    with pytest.raises(ValueError): runtime.validate_process_review(value)


def test_process_review_extra_unregistered_incident_rejected():
    value = review(); value["incidents"].append({"incident_id":"REL-999","priority":"P1","CORRECTIVE_STATUS":"OPEN"}); value["p1_items"].append("REL-999")
    with pytest.raises(ValueError, match="REGISTRY"): runtime.validate_process_review(value)


def test_actual_C3_C4_process_review_matches_contract_registry():
    runtime.validate_process_review(review())


def test_process_review_health_is_registered_enum():
    value = review(); value["pipeline_health"] = "C3_C4_SUCCESS"
    with pytest.raises(ValueError): runtime.validate_process_review(value)


def test_runner_path_identity_is_registered():
    assert runtime.runner_path(ROOT, Path(runner.__file__)) == Path(runner.__file__).resolve()
