import json
from pathlib import Path
import pytest
from audit.e9f import rp3_b_r160_runtime as rp3

ROOT=Path(__file__).resolve().parents[1]
RUNTIME=Path("/home/icy/MePhC/.rp3-b-r160-runtime-20260825")
TRACE=ROOT/"audit/e9f/rp3_b_r160_compact_trace.json"

def raw():
    return json.loads((RUNTIME/"rp3_b_r160_result.json").read_text())

def checkpoint():
    return json.loads((RUNTIME/"matrix_checkpoint.json").read_text())

def test_contract_and_plan_are_fixed_six_r160():
    c=json.loads((ROOT/"audit/e9f/rp3_b_r160_execution_contract.json").read_text())
    assert c["resolution"]==160 and c["worker_count"]==6 and c["native_solves_per_worker"]==9
    rows=rp3.build_plan(ROOT)
    assert len(rows)==6 and rp3.execution_order(rows)[0].startswith("fr=0;grid_i=-5;grid_j=0")

def test_raw_result_has_exact_native_and_provider_resolution():
    r=raw()
    assert r["actual_native_solve_count"]==54
    assert len(r["payloads"])==6 and all(p["resolution"]==160 and p["provider"]["resolution"]==160 for p in r["payloads"])
    assert all(p["solve_count"]==9 for p in r["payloads"])

def test_checkpoint_is_complete_and_exact_prefix():
    rows=rp3.build_plan(ROOT); cp=checkpoint()
    rp3.validate_checkpoint(cp,root=ROOT,rows=rows,orphan_scan=lambda ids: [])
    assert cp["generation"]==6 and len(cp["completed_workers"])==6
    assert [x["item_generation"] for x in cp["completed_workers"]]==[1,2,3,4,5,6]

@pytest.mark.parametrize("mutation",["wrong","duplicate","permuted"])
def test_item_generation_mutations_fail_closed(mutation):
    rows=rp3.build_plan(ROOT); cp=checkpoint()
    if mutation=="wrong": cp["completed_workers"][0]["item_generation"]=99
    elif mutation=="duplicate": cp["completed_workers"][1]["item_generation"]=1
    else: cp["completed_workers"][0]["item_generation"],cp["completed_workers"][1]["item_generation"]=2,1
    with pytest.raises(ValueError):
        rp3.validate_checkpoint(cp,root=ROOT,rows=rows,orphan_scan=lambda ids: [])

def test_resume_suffix_counts():
    rows=rp3.build_plan(ROOT); cp=checkpoint()
    for n,expected in ((0,6),(1,5),(3,3),(6,0)):
        x=json.loads(json.dumps(cp)); x["completed_workers"]=x["completed_workers"][:n]; x["generation"]=n
        assert len(rp3.resume_suffix(checkpoint=x,root=ROOT,rows=rows,orphan_scan=lambda ids: []))==expected

def test_trace_binds_all_convergence_and_l0_rows():
    p=json.loads(TRACE.read_text())
    assert len(p["convergence_rows"])==24 and len(p["spectral_rows"])==6 and len(p["entries"])==12
    assert all({"omega_R64","omega_R96","omega_R128","omega_R160","delta_R128_to_R160_signed","direction_relation"} <= set(x) for x in p["convergence_rows"])

def test_trace_contains_l1_l2_l3_and_assignment_evidence():
    p=json.loads(TRACE.read_text())
    assert all("association" in x and all("assignment" in e for e in x["association"]["edges"]) for x in p["entries"])
    assert all("BAND2" in x and "BAND3" in x and "L2" in x and "L3" in x for x in p["entries"])

def test_bounded_h_gate_and_lifecycle():
    p=json.loads(TRACE.read_text())
    assert max(x["H_MAX"]["full6_offdiag"] for x in p["entries"]) < 1e-10
    assert max(x["H_MAX"]["normalization_error"] for x in p["entries"]) <= 1e-14
    assert all(x["direct_pid_gone"] and x["orphan_count"]==0 for x in p["measurements"])

def test_firewalls_and_replay_policy():
    r=raw(); p=json.loads(TRACE.read_text())
    assert r["reducer_admissible"] is False and r["rp3_reducer_started"] is False and r["rp3_chern_started"] is False
    assert r["replay_policy"]=="NOT_APPLICABLE_R160_ORIGINAL_RP2_HAS_NO_R160_KEY"
    assert p["actual_native_solve_count"]==54

def test_no_dense_projector_allocation_path_is_retained():
    text=(ROOT/"audit/e9f/rp3_b_r160_runtime.py").read_text()
    worker=(ROOT/"audit/e9f/rp3_b_r160_worker.py").read_text()
    assert "compute_worker" in worker and "small" not in text.lower() or "dense" not in worker.lower()
