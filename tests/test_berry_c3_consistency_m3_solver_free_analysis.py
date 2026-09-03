"""Contract tests for the dedicated M3 solver-free analysis entrypoint."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / "audit" / "berry_c3_consistency" / "m3_solver_free_qualification_and_rank_analysis.py"
SPEC = importlib.util.spec_from_file_location("berry_c3_m3_dedicated", ENTRYPOINT)
assert SPEC and SPEC.loader
M3 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M3)


def _records() -> list[dict]:
    records = []
    for geometry in ("G15", "G16"):
        for deterministic in (False, True):
            for stencil in ("lab_fixed", "c3_covariant"):
                for repeat in range(3):
                    for member in range(3):
                        records.append({
                            "record_id": f"{geometry}-{deterministic}-{stencil}-{repeat}-{member}",
                            "geometry_id": geometry,
                            "member_index": member,
                            "repeat_index": repeat,
                            "solver_configuration": {"deterministic": deterministic, "stencil": stencil},
                            "qualification_status": "PENDING_REPEAT_QUALIFICATION",
                            "band_identity": "band-2-of-4",
                            "minimum_adjacent_gap_band2": 0.25,
                            "observable": float(member + 1),
                            "reductions": {"energy_eh": {"rank1_band2": {
                                "minimum_link_singular_values": [0.8, 0.9],
                                "projector_distances": [0.2, 0.3],
                            }}},
                        })
    assert len(records) == 72
    return records


def _bundle_with_descriptors(tmp_path: Path, records: list[dict], *, manifest: str | None = None, count: int | None = None) -> tuple[Path, dict]:
    descriptors = []
    for index, record in enumerate(records[:count or len(records)]):
        payload = json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")
        name = f"record-{index}.payload"
        (tmp_path / name).write_bytes(payload)
        descriptors.append({
            "dataset_id": M3.DATASET_ID,
            "manifest_sha256": manifest or M3.MANIFEST_SHA256,
            "record_key_sha256": hashlib.sha256(f"key-{index}".encode()).hexdigest(),
            "payload_file": name,
            "payload_sha256": hashlib.sha256(payload).hexdigest(),
            "payload_size_bytes": len(payload),
        })
    bundle = {"schema": "mephc-thin-input-bundle-v1", "work_order_id": "MEPHC-BERRY-C3-M3R2-TEST", "datasets": descriptors}
    path = tmp_path / "bundle.json"
    path.write_text(json.dumps(bundle), encoding="utf-8")
    return path, bundle


def test_valid_72_record_dataset_uses_1_0_0_budget_and_reducer(tmp_path, monkeypatch):
    records = _records()
    path, bundle = _bundle_with_descriptors(tmp_path, records)
    monkeypatch.setenv("MEPHC_INPUT_BUNDLE", str(path))
    monkeypatch.setenv("MEPHC_PROVIDER_REQUEST_BUDGET", "0")
    monkeypatch.setenv("MEPHC_SOLVER_EXECUTION_BUDGET", "0")

    M3.validate_budgets()
    result = M3.analyze(M3.load_payloads(bundle))

    assert result["schema"] == M3.RESULT_SCHEMA
    assert result["record_count"] == 72
    assert result["c3_orbit_count"] == 24
    assert result["rank1_unqualified_orbit_count"] == 24
    assert result["dominant_qualification_failure"] == "BAND_OR_SUBSPACE_IDENTITY_FAILURE"
    assert result["qualification_failure_axis_counts"] == {"BAND_OR_SUBSPACE_IDENTITY_FAILURE": 72}
    assert result["external_gap_global_min"] == 0.25
    assert result["minimum_link_singular_value"] == 0.8
    assert result["maximum_projector_distance"] == 0.3
    assert result["shadow_maximum_absolute_c3_residual"] == 2.0
    assert result["rank2_feasibility_status"] == "REQUIRES_NEW_LIVE_EVIDENCE"
    assert result["next_science_decision"] == "REACQUIRE_ONLY_SPECIFIC_MISSING_RANK_DIAGNOSTIC_PAYLOADS"
    assert result["native_invocation_count"] == 1
    assert result["provider_execution_count"] == result["solver_execution_count"] == result["dataset_record_count"] == 0


@pytest.mark.parametrize("kwargs,code", [
    ({"count": 71}, "M3_DATASET_DESCRIPTOR_COUNT_INVALID"),
    ({"manifest": "0" * 64}, "M3_DATASET_BINDING_MISMATCH"),
])
def test_wrong_dataset_manifest_or_count_fails_closed(tmp_path, monkeypatch, kwargs, code):
    path, bundle = _bundle_with_descriptors(tmp_path, _records(), **kwargs)
    monkeypatch.setenv("MEPHC_INPUT_BUNDLE", str(path))
    with pytest.raises(M3.M3Error, match=code):
        M3.load_payloads(bundle)


def test_duplicate_record_key_fails_closed(tmp_path, monkeypatch):
    path, bundle = _bundle_with_descriptors(tmp_path, _records())
    bundle["datasets"][1]["record_key_sha256"] = bundle["datasets"][0]["record_key_sha256"]
    monkeypatch.setenv("MEPHC_INPUT_BUNDLE", str(path))
    with pytest.raises(M3.M3Error, match="M3_DATASET_RECORD_KEY_ENUMERATION_INVALID"):
        M3.load_payloads(bundle)


def test_entrypoint_is_solver_free_and_uses_result_schema():
    source = ENTRYPOINT.read_text(encoding="utf-8")
    assert "import meep" not in source
    assert "MPBLive" not in source
    assert ".solve(" not in source
    assert M3.RESULT_SCHEMA == "mephc-berry-c3-consistency-m3-qualification-anatomy-and-rank-decision-v1"
