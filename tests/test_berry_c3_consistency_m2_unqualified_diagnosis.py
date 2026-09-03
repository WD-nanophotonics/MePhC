"""M3 solver-free diagnosis tests for the acquired M2 records."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / "audit" / "berry_c3_consistency" / "m2_live_c3_acquisition_and_reduction.py"
SPEC = importlib.util.spec_from_file_location("berry_c3_m3", ENTRYPOINT)
assert SPEC and SPEC.loader
M3 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M3)


def _records():
    plan = M3.derive_plan(M3.verify_m1_bundle())
    records = []
    for item in plan["live_requests"]:
        semantic = item["semantic_identity"]
        records.append({
            "record_id": f"m3-{item['request_key_sha256']}-{item['repeat_index']}",
            "geometry_id": semantic["geometry_id"],
            "member_index": semantic["member_index"],
            "repeat_index": item["repeat_index"],
            "solver_configuration": semantic["solver_configuration"],
            "qualification_status": "PENDING_REPEAT_QUALIFICATION",
            "band_identity": "band-2-of-4",
            "minimum_adjacent_gap_band2": 0.25,
            "observable": float(semantic["member_index"] + 1),
            "reductions": {"energy_eh": {"rank1_band2": {
                "minimum_link_singular_values": [0.8, 0.9, 0.85, 0.82],
                "projector_distances": [0.2, 0.3, 0.25, 0.22],
            }}},
        })
    return records


def test_m3_explains_all_24_unqualified_orbits_without_new_science():
    result = M3.analyze_m3_records(_records())
    assert result["record_count"] == 72
    assert result["c3_orbit_count"] == 24
    assert result["rank1_unqualified_orbit_count"] == 24
    assert result["dominant_qualification_failure"] == "BAND_OR_SUBSPACE_IDENTITY_FAILURE"
    assert result["qualification_failure_axis_counts"]["BAND_OR_SUBSPACE_IDENTITY_FAILURE"] == 72
    assert result["external_gap_global_min"] == 0.25
    assert result["minimum_link_singular_value"] == 0.8
    assert result["maximum_projector_distance"] == 0.3
    assert result["shadow_maximum_absolute_c3_residual"] == 2.0
    assert result["rank2_feasibility_status"] == "REQUIRES_NEW_LIVE_EVIDENCE"
    assert result["next_science_decision"] == "REACQUIRE_ONLY_SPECIFIC_MISSING_RANK_DIAGNOSTIC_PAYLOADS"
    assert result["native_invocation_count"] == 1
    assert result["provider_execution_count"] == result["solver_execution_count"] == result["dataset_record_count"] == 0


def test_m3_binds_exact_dataset_descriptors_and_reads_only_payloads(tmp_path, monkeypatch):
    records = _records()
    descriptors = []
    for index, record in enumerate(records):
        payload = json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")
        name = f"record-{index}.payload"
        (tmp_path / name).write_bytes(payload)
        descriptors.append({
            "dataset_id": M3.M3_DATASET_ID,
            "manifest_sha256": M3.M3_MANIFEST_SHA256,
            "record_key_sha256": hashlib.sha256(f"key-{index}".encode()).hexdigest(),
            "payload_file": name,
            "payload_sha256": hashlib.sha256(payload).hexdigest(),
            "payload_size_bytes": len(payload),
        })
    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_text(json.dumps({
        "schema": "mephc-thin-input-bundle-v1",
        "work_order_id": "MEPHC-BERRY-C3-M3-72-RECORD-QUALIFICATION-ANATOMY-AND-RANK-DECISION-20260903-016",
        "datasets": descriptors,
    }), encoding="utf-8")
    monkeypatch.setenv("MEPHC_INPUT_BUNDLE", str(bundle_path))
    result = M3.run_m3(json.loads(bundle_path.read_text(encoding="utf-8")))
    assert result["dataset_id"] == M3.M3_DATASET_ID
    assert result["manifest_sha256"] == M3.M3_MANIFEST_SHA256
    assert result["record_count"] == 72
    assert result["c3_orbit_count"] == 24


def test_m3_falls_back_to_supported_manifest_resolver_when_bundle_has_no_descriptors(tmp_path, monkeypatch):
    records = _records()
    payloads = {hashlib.sha256(f"key-{index}".encode()).hexdigest(): json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8") for index, record in enumerate(records)}

    class Resolver:
        @staticmethod
        def verify_dataset(state_root, dataset_id):
            assert dataset_id == M3.M3_DATASET_ID
            return {"dataset_id": dataset_id, "manifest_sha256": M3.M3_MANIFEST_SHA256, "record_count": 72, "record_key_sha256": list(payloads)}

        @staticmethod
        def resolve_dataset_record(state_root, dataset_id, manifest_sha256, record_key_sha256):
            assert dataset_id == M3.M3_DATASET_ID and manifest_sha256 == M3.M3_MANIFEST_SHA256
            return {"payload": payloads[record_key_sha256]}

    monkeypatch.setattr(M3, "_load_scientific_job", lambda: Resolver)
    counters = tmp_path / "state" / "runner" / "execution-counters.json"
    counters.parent.mkdir(parents=True)
    monkeypatch.setenv("MEPHC_EXECUTION_COUNTERS_PATH", str(counters))
    bundle = {
        "schema": "mephc-thin-input-bundle-v1",
        "work_order_id": "MEPHC-BERRY-C3-M3-72-RECORD-QUALIFICATION-ANATOMY-AND-RANK-DECISION-20260903-016",
        "datasets": [],
    }
    result = M3.run_m3(bundle)
    assert result["record_count"] == 72
    assert result["c3_orbit_count"] == 24
    assert result["schema"] == M3.M3_RESULT_SCHEMA


def test_m3_entrypoint_has_no_provider_or_solver_execution_path():
    source = ENTRYPOINT.read_text(encoding="utf-8")
    m3_source = source[source.index("def analyze_m3_records"):source.index("def execute_injected_plan")]
    assert "import meep" not in m3_source
    assert "provider.solve" not in m3_source
    assert "BudgetCounter" not in m3_source
    failure = M3.compact_m3_failure(M3.M2Error("M3_DATASET_DESCRIPTOR_COUNT_INVALID"))
    assert failure["schema"] == M3.M3_RESULT_SCHEMA
