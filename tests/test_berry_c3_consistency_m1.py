"""Solver-free contract tests for the Berry-C3 M1 preparation milestone."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
HARNESS_PATH = ROOT / "audit" / "berry_c3_consistency" / "m1_solver_free_diagnostic_harness.py"
SPEC = importlib.util.spec_from_file_location("berry_c3_m1_harness", HARNESS_PATH)
assert SPEC and SPEC.loader
HARNESS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HARNESS)


def record(member_index: int, *, observable: float | None = 1.0, **changes):
    values = HARNESS.c3_orbit()
    item = {
        "record_id": f"fake-M7-{member_index}",
        "orbit_id": "M7",
        "member_index": member_index,
        "coordinate": list(values[member_index]),
        "geometry_id": "G16",
        "domain_id": "raw_hbz",
        "band_identity": "band-1-of-4",
        "subspace_identity": "rank1-withheld",
        "qualification_status": "QUALIFIED",
        "observable": observable,
    }
    item.update(changes)
    return item


def complete_records(**changes):
    return [record(index) for index in range(3)]


def test_exact_orbit_and_proper_rotation():
    result = HARNESS.diagnose_orbit(complete_records())
    assert result["status"] == "COMPARABLE_DEFERRED_THRESHOLD"
    assert result["coordinate_status"] == "PASS"
    assert result["proper_rotation"]["determinant_status"] == "PASS"
    assert result["proper_rotation"]["c3_cubed_identity"] is True
    assert result["proper_rotation"]["pseudoscalar_rule"] == "preserve_sign_under_proper_C3"


def test_deliberate_observable_inconsistency_is_preserved():
    records = complete_records()
    records[2]["observable"] = 3.0
    result = HARNESS.diagnose_orbit(records)
    assert result["status"] == "COMPARABLE_DEFERRED_THRESHOLD"
    assert result["numerical_observable_status"] == "DEFERRED_THRESHOLD"
    assert result["observable_residuals"] == [0.0, 0.0, 2.0]


def test_missing_member_is_incomplete_not_zero():
    result = HARNESS.diagnose_orbit(complete_records()[:2])
    assert result["status"] == "INCOMPLETE_EVIDENCE"
    assert result["missing_member_indices"] == [2]
    assert result["numerical_observable_status"] == "NOT_COMPARABLE"


def test_wrong_rotation_fails_closed():
    records = complete_records()
    records[1]["coordinate"] = [0.70, 0.0]
    assert HARNESS.diagnose_orbit(records)["status"] == "INCONSISTENT"


@pytest.mark.parametrize(
    "changes",
    [
        {"band_identity": "band-2-of-4"},
        {"subspace_identity": "rank2"},
        {"geometry_id": "G15"},
        {"domain_id": "lab_fixed"},
    ],
)
def test_identity_geometry_and_domain_mismatch_fails_closed(changes):
    records = complete_records()
    records[1].update(changes)
    assert HARNESS.diagnose_orbit(records)["status"] == "INCONSISTENT"


def test_duplicate_conflict_is_rejected():
    with pytest.raises(HARNESS.DiagnosticError, match="DUPLICATE_CONFLICTING_IDENTITY"):
        HARNESS.diagnose_orbit(complete_records() + [record(0, record_id="conflict", geometry_id="G15")])


def test_unqualified_status_propagates_without_numeric_claim():
    records = complete_records()
    for item in records:
        item["qualification_status"] = "UNQUALIFIED"
    result = HARNESS.diagnose_orbit(records)
    assert result["status"] == "UNQUALIFIED"
    assert result["qualification_status"] == "UNQUALIFIED_PROPAGATED"


def test_nonfinite_coordinate_is_rejected():
    records = complete_records()
    records[0]["coordinate"] = [float("nan"), 0.0]
    with pytest.raises(HARNESS.DiagnosticError, match="NONFINITE_COORDINATE"):
        HARNESS.diagnose_orbit(records)


def test_deterministic_hashes_and_unique_future_requests():
    graph = HARNESS.build_future_request_graph()
    assert graph == HARNESS.build_future_request_graph()
    keys = [node["request_key_sha256"] for node in graph["nodes"]]
    assert len(keys) == len(set(keys)) == 24
    assert graph["expanded_future_request_count"] == 72
    assert graph["future_native_invocation_count"] == 72
    assert all(node["semantic_identity"]["independent_repeat_count"] == 3 for node in graph["nodes"])


def test_no_real_execution_and_result_is_zero_budget():
    source = HARNESS_PATH.read_text(encoding="utf-8").lower()
    assert "import meep" not in source
    assert "import mpb" not in source
    assert ".solve(" not in source
    baseline = HARNESS.diagnose_records(complete_records())
    result = HARNESS.bounded_result(inventory_record_count=1, baseline=baseline, graph=HARNESS.build_future_request_graph())
    assert result["actual_counts"] == {"native": 0, "provider": 0, "solver": 0, "dataset": 0}
    assert result["execution_status"] == "PASS"


def test_static_baseline_declares_absence_without_inference():
    baseline = json.loads((ROOT / "audit" / "berry_c3_consistency" / "m1_c3_orbit_baseline.json").read_text(encoding="utf-8"))
    inventory = json.loads((ROOT / "audit" / "berry_c3_consistency" / "m1_frozen_record_inventory.json").read_text(encoding="utf-8"))
    assert baseline["classification"] == "INCOMPLETE_EVIDENCE"
    assert baseline["no_absence_as_zero"] is True
    assert inventory["complete_member_evidence"] is False
