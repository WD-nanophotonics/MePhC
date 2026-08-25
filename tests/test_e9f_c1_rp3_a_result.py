import json
from pathlib import Path
from audit.e9f import c3_c5_c1_postprocess as c1
from audit.e9f import rp3_a_r128_runtime as rp3

ROOT = Path(__file__).resolve().parents[1]
TRACE = ROOT / "audit/e9f/rp3_a_r128_compact_trace.json"


def test_r128_trace_is_complete_and_bound():
    trace = json.loads(TRACE.read_text())
    assert trace["execution_sha"] == "39b63b80bf42d48e5b256dd1a211f6bec2585cd4"
    assert trace["source_science_execution_sha"] == "02b8fc343b3dd786769c42cfa8e44bd57add482d"
    assert trace["authorized_native_solve_count"] == 54
    assert trace["actual_native_solve_count"] == 54
    assert trace["worker_count"] == 6
    assert trace["entry_count"] == 12
    assert len(trace["entries"]) == 12
    assert len(trace["convergence_rows"]) == 24
    assert len(trace["spectral_rows"]) == 6
    assert all(item["resolution"] == 128 for item in trace["entries"])
    assert all(item["orphan_count"] == 0 and item["direct_pid_gone"] for item in trace["measurements"])
    assert all(item["replay_policy"] == "NOT_APPLICABLE_R128_ORIGINAL_RP2_HAS_NO_R128_KEY" for item in trace["entries"])
    assert trace["no_convergence_verdict"] is True
    for item in trace["entries"]:
        window = item["association"]["candidate_window_zero_based"]
        for edge in item["association"]["edges"]:
            c1.validate_positional_assignment(edge, window)


def test_r128_trace_is_diagnostic_only_and_no_reducer():
    trace = json.loads(TRACE.read_text())
    assert trace["diagnostic_only"] is True
    assert trace["reducer_admissible"] is False


def test_published_resume_checkpoint_has_full_prefix_binding():
    checkpoint = json.loads((ROOT / "audit/e9f/rp3_a_r128_resume_checkpoint.json").read_text())
    rows = rp3.build_plan(ROOT)
    rp3.validate_checkpoint(checkpoint, root=ROOT, rows=rows, orphan_scan=lambda ids: [])
    assert checkpoint["generation"] == 6
    assert len(checkpoint["completed_workers"]) == 6
    assert rp3.resume_suffix(checkpoint=checkpoint, root=ROOT, rows=rows, orphan_scan=lambda ids: []) == []
    required = {"worker_id","source_sample_id","logical_sample_index","resolution","payload_path","payload_file_sha256","payload_body_sha256","execution_sha","contract_sha256","policy_sha256","item_generation","terminal_payload_status"}
    assert all(required <= set(item) for item in checkpoint["completed_workers"])
