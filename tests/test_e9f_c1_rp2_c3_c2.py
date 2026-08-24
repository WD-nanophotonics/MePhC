from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from audit.e9f import c3_c2_hardening as hardening
from audit.e9f import run_e9f_c1_rp2_c3_c2 as runner
from audit.e9f import run_e9f_c1_rp2_c3_c2_impl as impl
from audit.e9f import run_e9f_c1_rp2_c3_c2_worker as worker
from audit.e9f import run_e9f_c1_rp2_c3_c1_impl as base

ROOT = Path(__file__).resolve().parents[1]


def raw(q=(0.1, 0.2), frequencies=None, swap=False):
    frequencies = frequencies or (1.0, 2.0, 3.0, 3.5, 5.0, 6.0)
    vectors = [np.eye(6, dtype=np.complex128)[:, i] for i in range(6)]
    if swap:
        vectors[2], vectors[3] = vectors[3], vectors[2]
    return SimpleNamespace(
        k_point=tuple(q), frequencies=tuple(frequencies), normalized_vectors=vectors,
        gram_matrix=np.eye(6, dtype=np.complex128), orthogonality_status="MPB_H_ENVELOPE_QUALIFIED",
        max_off_diagonal_gram=0.0, max_normalization_error=0.0,
    )


def plaquette():
    return [raw((0.1 + i * 0.001, 0.2 + i * 0.001)) for i in range(4)]


def review():
    def incident(name, priority, status):
        return {"incident_id": name, "priority": priority, "CORRECTIVE_STATUS": status}
    return {"incidents": [incident("REL-021", "P1", "OPEN"), incident("REL-035", "P2", "CLOSED")], "pipeline_health": "PIPELINE_REQUIRES_CORRECTIVE", "p0_items": [], "p1_items": ["REL-021"], "p2_items": []}


def test_full_worker_mock_provider_collects_4_before_analysis():
    calls = []
    analyses = []
    for index in range(1 + 2 * 4):
        calls.append(index)
        if index in (4, 8):
            values = [raw((index + vertex, 0.2)) for vertex in range(4)]
            analyses.append(impl.analyze_plaquette(values, 1 / (72 if index == 4 else 144)))
    assert len(calls) == 9 and len(analyses) == 2


def test_partial_plaquette_analysis_rejected():
    for count in (0, 1, 2, 3, 5):
        with pytest.raises(ValueError, match="REQUIRES_FOUR"):
            impl.analyze_plaquette((plaquette() + [raw()])[:count], 1 / 72)


def test_distinct_band2_band3_shadow_records():
    result = impl.analyze_plaquette(plaquette(), 1 / 72)
    assert result["BAND2_PHYSICAL_BRANCH_SHADOW"]["name"] != result["BAND3_PHYSICAL_BRANCH_SHADOW"]["name"]


def test_solver_slot_swap_follows_physical_branch():
    values = [raw() for _ in range(4)]
    values[1] = raw(swap=True)
    association, maps = base.associate_h(values)
    assert association["candidate_window_zero_based"] == [2, 3]
    assert maps is not None
    assert maps[1][2] in (2, 3) and maps[1][3] in (2, 3)


def test_rank1_shadow_survives_gap_below_0p02():
    values = plaquette()
    for value in values:
        value.frequencies = (1.0, 2.99, 3.0, 3.5, 5.0, 6.0)
    association, maps = base.associate_h(values)
    result = base._rank1_shadow(values, maps, 2, 1 / 72)
    assert result["CURRENT_0P02_QUALIFICATION_CONTEXT"][0]["would_pass_gap_threshold"] is False
    assert result["diagnostic_only"] is True


def test_l1_ambiguous_l2_still_executes(monkeypatch):
    called = []
    monkeypatch.setattr(base, "associate_h", lambda values: ({"loop_closure": False}, None))
    monkeypatch.setattr(base, "_rank1_shadow", lambda *args: {"PHI_RANK1_SHADOW": None})
    monkeypatch.setattr(base, "_reduce_l2", lambda values: called.append(True) or {"PHI_RANK2_DET": None, "all_edges_qualified": False})
    result = impl.analyze_plaquette(plaquette(), 1 / 72)
    assert called and result["L2_RANK2"]["independent_of_l1"] is True


def test_l3_distinct_phase_mutations_rejected(monkeypatch):
    monkeypatch.setattr(base, "associate_h", lambda values: ({"loop_closure": True}, [{2: 2, 3: 3}] * 5))
    monkeypatch.setattr(base, "_rank1_shadow", lambda values, maps, branch, h: {"PHI_RANK1_SHADOW": 0.1 * branch})
    monkeypatch.setattr(base, "_reduce_l2", lambda values: {"PHI_RANK2_DET": 0.1, "all_edges_qualified": True})
    result = impl.analyze_plaquette(plaquette(), 1 / 72)
    assert result["L3"]["status"] == "DIAGNOSTIC_ONLY"
    assert result["L3"]["DELTA_PHASE_RANK1SUM_RANK2DET"] >= 0


def test_l2_external_bands_exactly_0_1_4_5():
    result = impl.analyze_plaquette(plaquette(), 1 / 72)["L2_RANK2"]
    assert result["external_bands_zero_based"] == [0, 1, 4, 5]


def test_l2_u2_gauge_invariance():
    assert impl.analyze_plaquette(plaquette(), 1 / 72)["L2_RANK2"]["gauge_order_fixtures"]["u2_projector_error"] < 1e-12


def test_l2_column_swap_invariance():
    fixture = impl.analyze_plaquette(plaquette(), 1 / 72)["L2_RANK2"]["gauge_order_fixtures"]
    assert fixture["column_swap_projector_error"] < 1e-12


def test_real_subspace_qualification_reduction_path():
    result = impl.analyze_plaquette(plaquette(), 1 / 72)["L2_RANK2"]
    assert "qualification_status" in result["edges"][0]
    assert result["diagnostic_only"] is True


def test_frequency_replay_exact_match(tmp_path):
    directory = tmp_path / "audit/e9f/rp2_evidence/workers"
    directory.mkdir(parents=True)
    q = [0.1, 0.2]
    (directory / "prior.json").write_text(json.dumps({"execution_git_sha": "8121dbfba352b1a77551213771694d25c1bf3f01", "source_sample_id": "sample", "resolution": 64, "stencils": {"1/72": {"center_sampling": {"EVALUATED_Q": q, "frequencies": [1, 2, 3, 3.5, 5, 6]}}}}))
    index = impl.replay_index(tmp_path, "sample", 64)
    assert impl.point(raw(q), q, index)["frequency_replay"]["matched"] is True


def test_frequency_replay_detects_mutated_frequency(tmp_path):
    directory = tmp_path / "audit/e9f/rp2_evidence/workers"
    directory.mkdir(parents=True)
    q = [0.1, 0.2]
    (directory / "prior.json").write_text(json.dumps({"execution_git_sha": "8121dbfba352b1a77551213771694d25c1bf3f01", "source_sample_id": "sample", "resolution": 64, "stencils": {"1/72": {"center_sampling": {"EVALUATED_Q": q, "frequencies": [1, 2, 3, 3.5, 5, 6]}}}}))
    mutated = raw(q, frequencies=(1, 2, 3.25, 3.5, 5, 6))
    replay = impl.point(mutated, q, impl.replay_index(tmp_path, "sample", 64))["frequency_replay"]
    assert replay["matched"] is True and replay["max_abs_difference"] > 1e-8


def test_l3_aggregate_is_data_derived():
    entries = [impl.analyze_plaquette(plaquette(), 1 / 72), impl.analyze_plaquette(plaquette(), 1 / 144)]
    metrics = [{**base._point(item, item.k_point), "frequency_replay": {"matched": True, "max_abs_difference": 0.0}} for item in plaquette()]
    payload = {"stencils": {str(i): entry for i, entry in enumerate(entries)}, "all_point_metrics": metrics, "replay_matched_point_count": 4, "replay_unmatched_point_count": 0, "solve_count": 9}
    summary = impl.aggregate([payload])
    assert summary["total_native_solves"] == 9
    assert summary["L3_COMPUTABLE_ENTRIES"] == sum(entry["L3"] is not None for entry in entries)


def test_failure_sidecar_retains_exception_and_stage(tmp_path):
    path = tmp_path / "failure.json"
    worker.atomic(path, {"schema": "mephc_e9f_c1_rp2_c3_c2_failure_sidecar_v1", "stage": "compute_worker", "exception_type": "ValueError", "exception_message": "boom", "traceback_tail": "x" * 65536})
    value = json.loads(path.read_text())
    assert value["stage"] == "compute_worker" and len(value["traceback_tail"]) >= 65536


def test_parent_retains_stderr_tail_when_child_fails_without_sidecar():
    assert len(runner.tail(b"x" * 70000)) == 65536


def test_stdout_json_never_used_as_payload():
    source = Path(runner.__file__).read_text()
    assert "payload_path.read_bytes()" in source and "json.loads(out" not in source


def test_checkpoint_binds_exact_payload_hash(tmp_path):
    payload = {"x": 1}
    payload_path = tmp_path / "payload.json"
    payload_path.write_bytes(hardening.canonical(payload))
    expected = {"schema": "s", "project_id": "MEPHC", "work_order_id": "w", "execution_sha": "e", "contract_sha256": "c", "worker_id": "i", "logical_sample_index": 0, "resolution": 64, "payload_sha256": hardening.sha(payload_path), "artifact_schema": "a", "generation": 1}
    hardening.validate_checkpoint(dict(expected), expected=expected, payload_path=payload_path)


@pytest.mark.parametrize("field", ["execution_sha", "worker_id"])
def test_checkpoint_rejects_wrong_identity(tmp_path, field):
    payload_path = tmp_path / "payload.json"
    payload_path.write_bytes(b"{}\n")
    expected = {"schema": "s", "project_id": "MEPHC", "work_order_id": "w", "execution_sha": "e", "contract_sha256": "c", "worker_id": "i", "logical_sample_index": 0, "resolution": 64, "payload_sha256": hardening.sha(payload_path), "artifact_schema": "a", "generation": 1}
    actual = dict(expected); actual[field] = "wrong"
    with pytest.raises(ValueError, match="IDENTITY"):
        hardening.validate_checkpoint(actual, expected=expected, payload_path=payload_path)


def test_policy_derived_six_sample_plan():
    assert len(base.load_policy(ROOT)["rp2_diagnostic_matrix"]["fixed_sample_ids"]) == 6


def test_unique_12_logical_worker_indices():
    rows = base.build_plan(ROOT)
    assert len(rows) == 12 and [row["sample_index"] for row in rows] == list(range(12))


def test_work_order_identity_consistency():
    contract = impl.load_contract(ROOT)
    assert contract["work_order_id"] == impl.WORK_ORDER and contract["parent_failed_execution_sha"] == impl.PARENT_FAILED_EXECUTION_SHA


def test_source_anchor_firewall():
    assert "8121dbfba352b1a77551213771694d25c1bf3f01" in Path(impl.__file__).read_text()


def test_reducer_firewall():
    assert impl.analyze_plaquette(plaquette(), 1 / 72)["reducer_admissible"] is False


def test_parent_mpb_import_isolation():
    source = Path(runner.__file__).read_text()
    assert "import meep" not in source and "mpb_spectral_provider" not in source


def test_orphan_fake_child_detection():
    assert runner.proc_cmdline(-1) == ""


def test_process_review_closed_incident_not_in_open_list():
    value = review(); value["incidents"][0]["CORRECTIVE_STATUS"] = "CLOSED"; value["p1_items"] = []
    hardening.validate_process_review(value)


def test_process_review_open_incident_must_be_in_open_list():
    value = review(); value["p1_items"] = []
    with pytest.raises(ValueError, match="OPEN_SET"):
        hardening.validate_process_review(value)


def test_process_review_wrong_priority_rejected():
    value = review(); value["p0_items"] = ["REL-021"]
    with pytest.raises(ValueError, match="OPEN_LIST"):
        hardening.validate_process_review(value)


def test_process_review_duplicate_open_incident_rejected():
    value = review(); value["p1_items"] = ["REL-021", "REL-021"]
    with pytest.raises(ValueError, match="DUPLICATE"):
        hardening.validate_process_review(value)


def test_py_compile_and_import():
    paths = [Path(impl.__file__), Path(worker.__file__), Path(runner.__file__)]
    result = subprocess.run([sys.executable, "-m", "py_compile", *(str(path) for path in paths)], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
