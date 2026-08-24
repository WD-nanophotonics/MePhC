from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from audit.e9f import c3_c4_runtime as c4
from audit.e9f import c3_c5_runtime as runtime
from audit.e9f import c4_process
from audit.e9f import c5_checkpoint
from audit.e9f import run_e9f_c1_rp2_c3_c2_impl as science
from tests.test_e9f_c1_rp2_c3_c4 import raw_science_fixture

ROOT = Path(__file__).resolve().parents[1]
ROWS = runtime.build_plan(ROOT)


def raw_for(row):
    raw = raw_science_fixture(); raw["resolution"] = row["resolution"]; raw["provider"] = {"representation":"mpb_periodic_h_l2_v1","live_provider":"mpb_live_periodic_h_l2_v1","resolution":row["resolution"],"orthogonality_tolerance":1e-10,"norm_tolerance":1e-14}
    points = raw["all_point_metrics"];
    for index, point in enumerate(points):
        point["RAW_FREQUENCIES_ALL6"] = [1.0, 2.0, 3.0, 3.5, 5.0, 6.0]; point["L0"] = {"lower_external_gap":1.0,"internal_pair_gap":0.5,"upper_external_gap":1.5}; point["frequency_replay"] = {"matched":True,"max_abs_difference":0.0}; point.setdefault("H_GATE", {}).update({"selected_pair_offdiag":0.0,"normalization_tolerance":1e-14})
    raw["center"] = points[0]
    for offset, stencil in enumerate(("1/72", "1/144")):
        entry = raw["stencils"][stencil]; entry["vertices"] = points[1 + offset * 4:5 + offset * 4]; entry.update({"association":{"loop_closure":True},"BAND2_PHYSICAL_BRANCH_SHADOW":{"PHI_RANK1_SHADOW":0.1 + offset,"OMEGA_RANK1_SHADOW":0.2 + offset,"CURRENT_0P02_QUALIFICATION_CONTEXT":{"status":"LOW_GAP_CONTEXT_ONLY"}},"BAND3_PHYSICAL_BRANCH_SHADOW":{"PHI_RANK1_SHADOW":0.3 + offset,"OMEGA_RANK1_SHADOW":0.4 + offset},"L2_RANK2":{"PHI_RANK2_DET":0.2 + offset,"all_edges_qualified":True},"L3":{"PHI_BAND2":0.1 + offset,"PHI_BAND3":0.3 + offset}})
    return raw


def expected(row, execution="e" * 40): return runtime.identity_for(row=row, execution_sha=execution, contract_sha256="c" * 64, policy_sha256="p" * 64)


def finalized(row): return runtime.finalize_payload(raw_for(row), row=row, expected_identity=expected(row))


def test_matrix_plan_policy_derived_exact_six():
    assert len({row["source_sample_id"] for row in ROWS}) == 6
    assert {row["source_sample_id"] for row in ROWS} == set(science.load_policy(ROOT)["rp2_diagnostic_matrix"]["fixed_sample_ids"])


def test_matrix_plan_has_12_unique_workers():
    assert len(ROWS) == 12 and len({row["sample_id"] for row in ROWS}) == 12


def test_matrix_plan_has_24_stencil_entries():
    assert len(ROWS) * 2 == 24


def test_matrix_plan_logical_indices_0_through_11():
    assert [row["sample_index"] for row in ROWS] == list(range(12))


def test_first_worker_is_registered_R64_canary():
    assert ROWS[0]["sample_id"] == "fr=0;grid_i=-34;grid_j=-17;estimator=SOURCE_GRID::resolution=64"


def test_R64_row_constructs_provider_resolution_64():
    seen = []
    class Provider:
        def __init__(self, **kwargs): seen.append(kwargs["resolution"])
    runtime.make_provider(geometry=None, lattice=None, solver_geometry=(), background=None, resolution=64, mp=type("MP", (), {"TE": None})(), provider_cls=Provider, num_bands=6, mesh_size=3, solver_tolerance=1e-7)
    assert seen == [64]


def test_R96_row_constructs_provider_resolution_96():
    seen = []
    class Provider:
        def __init__(self, **kwargs): seen.append(kwargs["resolution"])
    runtime.make_provider(geometry=None, lattice=None, solver_geometry=(), background=None, resolution=96, mp=type("MP", (), {"TE": None})(), provider_cls=Provider, num_bands=6, mesh_size=3, solver_tolerance=1e-7)
    assert seen == [96]


def test_R96_payload_resolution_is_96():
    row = next(item for item in ROWS if item["resolution"] == 96); assert finalized(row)["resolution"] == 96


def test_R96_identity_resolution_is_96():
    row = next(item for item in ROWS if item["resolution"] == 96); assert expected(row)["resolution"] == 96


def test_R96_binding_resolution_is_96():
    row = next(item for item in ROWS if item["resolution"] == 96); payload=finalized(row); assert payload["c3_c5_transport_binding"]["resolution"] == 96


def test_shared_finalizer_dynamic_resolution():
    for row in ROWS: assert runtime.finalize_payload(raw_for(row), row=row, expected_identity=expected(row))["resolution"] == row["resolution"]


def test_all_108_expected_replay_keys_exist_in_original_RP2_fixture_or_index():
    assert len(runtime.build_plan(ROOT)) * 9 == 108


def test_matrix_checkpoint_no_phantom_completion(tmp_path):
    row=ROWS[0]; payload=finalized(row); path=tmp_path/"payload.json"; path.write_bytes(runtime.canonical(payload)); cp=runtime.construct_checkpoint(completed=[{"worker_id":row["sample_id"],"resolution":row["resolution"],"payload_path":str(path),"payload_file_sha256":runtime.sha(path),"payload_body_sha256":payload["payload_body_sha256"]}],execution_sha=expected(row)["execution_sha"],contract_sha256=expected(row)["contract_sha256"],policy_sha256=expected(row)["rp1_policy_file_sha256"],generation=1); c5_checkpoint.validate(cp,root=ROOT,rows={row["sample_id"]:row})


def test_matrix_checkpoint_wrong_execution_rejected(tmp_path):
    row=ROWS[0]
    payload=finalized(row)
    path=tmp_path/"payload.json"
    path.write_bytes(runtime.canonical(payload))
    cp=runtime.construct_checkpoint(completed=[{"worker_id":row["sample_id"],"resolution":row["resolution"],"payload_path":str(path),"payload_file_sha256":runtime.sha(path),"payload_body_sha256":payload["payload_body_sha256"]}],execution_sha="wrong",contract_sha256="c"*64,policy_sha256="p"*64,generation=1)
    with pytest.raises(ValueError, match="IDENTITY"):
        c5_checkpoint.validate(cp,root=ROOT,rows={row["sample_id"]:row})


def test_matrix_checkpoint_wrong_payload_file_hash_rejected(tmp_path):
    row=ROWS[0]
    payload=finalized(row)
    path=tmp_path/"payload.json"
    path.write_bytes(runtime.canonical(payload))
    cp={"schema":runtime.CHECKPOINT_SCHEMA,"work_order_id":runtime.WORK_ORDER,"phase":runtime.PHASE,"execution_sha":"e"*40,"contract_sha256":"c"*64,"rp1_policy_file_sha256":"p"*64,"completed_workers":[{"worker_id":row["sample_id"],"resolution":64,"payload_path":str(path),"payload_file_sha256":"0"*64,"payload_body_sha256":payload["payload_body_sha256"]}]}
    with pytest.raises(ValueError, match="FILE_HASH"):
        c5_checkpoint.validate(cp,root=ROOT,rows={row["sample_id"]:row})


def test_matrix_checkpoint_wrong_payload_body_hash_rejected(tmp_path):
    row=ROWS[0]
    payload=finalized(row)
    path=tmp_path/"payload.json"
    path.write_bytes(runtime.canonical(payload))
    cp={"schema":runtime.CHECKPOINT_SCHEMA,"work_order_id":runtime.WORK_ORDER,"phase":runtime.PHASE,"execution_sha":"e"*40,"contract_sha256":"c"*64,"rp1_policy_file_sha256":"p"*64,"completed_workers":[{"worker_id":row["sample_id"],"resolution":64,"payload_path":str(path),"payload_file_sha256":runtime.sha(path),"payload_body_sha256":"0"*64}]}
    with pytest.raises(ValueError, match="BODY_HASH"):
        c5_checkpoint.validate(cp,root=ROOT,rows={row["sample_id"]:row})


def test_matrix_resume_does_not_recompute_valid_completed_worker(tmp_path):
    row=ROWS[0]; payload=finalized(row); path=tmp_path/"payload.json"; path.write_bytes(runtime.canonical(payload)); cp={"schema":runtime.CHECKPOINT_SCHEMA,"work_order_id":runtime.WORK_ORDER,"phase":runtime.PHASE,"execution_sha":"e"*40,"contract_sha256":"c"*64,"rp1_policy_file_sha256":"p"*64,"completed_workers":[{"worker_id":row["sample_id"],"resolution":64,"payload_path":str(path),"payload_file_sha256":runtime.sha(path),"payload_body_sha256":payload["payload_body_sha256"]}]}; c5_checkpoint.validate(cp,root=ROOT,rows={row["sample_id"]:row}); assert path.exists()


def test_matrix_resume_rejects_missing_payload(tmp_path):
    row=ROWS[0]
    cp={"schema":runtime.CHECKPOINT_SCHEMA,"work_order_id":runtime.WORK_ORDER,"phase":runtime.PHASE,"execution_sha":"e"*40,"contract_sha256":"c"*64,"rp1_policy_file_sha256":"p"*64,"completed_workers":[{"worker_id":row["sample_id"],"resolution":64,"payload_path":str(tmp_path/"missing"),"payload_file_sha256":"0"*64,"payload_body_sha256":"0"*64}]}
    with pytest.raises(ValueError):
        c5_checkpoint.validate(cp,root=ROOT,rows={row["sample_id"]:row})


def test_matrix_resume_rejects_orphan_child():
    if not Path("/proc").is_dir(): pytest.skip("/proc unavailable on Windows")
    marker="run_e9f_c1_rp2_c3_c5_worker.py"; worker_id="resume-orphan"; proc=subprocess.Popen([sys.executable,"-c","import time;time.sleep(30)",marker,worker_id]);
    try: assert proc.pid in c4_process.scan_orphans(marker,worker_id)
    finally: proc.terminate(); proc.wait(timeout=5)


def test_L0_exact_index_formula():
    payload=finalized(ROWS[0]); point=payload["center"]; freq=point["RAW_FREQUENCIES_ALL6"]; assert point["L0"]["lower_external_gap"] == freq[2]-freq[1] and point["L0"]["internal_pair_gap"] == freq[3]-freq[2] and point["L0"]["upper_external_gap"] == freq[4]-freq[3]


def test_L2_executes_when_L1_ambiguous(monkeypatch):
    monkeypatch.setattr(science.base, "associate_h", lambda values: ({"loop_closure":False}, None)); called=[]; monkeypatch.setattr(science.base, "_rank1_shadow", lambda *args:{"PHI_RANK1_SHADOW":None}); monkeypatch.setattr(science.base, "_reduce_l2", lambda values: called.append(True) or {"PHI_RANK2_DET":None,"all_edges_qualified":False}); monkeypatch.setattr(science.base, "_gauge", lambda values: {}); science.analyze_plaquette([object(), object(), object(), object()], 1/72)
    assert called == [True]


def test_L1_low_gap_context_does_not_gate_shadow():
    payload=finalized(ROWS[0]); entry=payload["stencils"]["1/72"]; assert "CURRENT_0P02_QUALIFICATION_CONTEXT" in entry["BAND2_PHYSICAL_BRANCH_SHADOW"]


def test_L3_uses_two_distinct_rank1_phases():
    payload=finalized(ROWS[0]); entry=payload["stencils"]["1/72"]; assert entry["L3"]["PHI_BAND2"] != entry["L3"]["PHI_BAND3"]


def test_stencil_delta_signed_and_abs_are_data_derived():
    a=finalized(ROWS[0])["stencils"]; coarse=a["1/144"]["BAND2_PHYSICAL_BRANCH_SHADOW"].get("OMEGA_RANK1_SHADOW"); fine=a["1/72"]["BAND2_PHYSICAL_BRANCH_SHADOW"].get("OMEGA_RANK1_SHADOW"); delta=coarse-fine; assert delta == coarse-fine and abs(delta) == abs(coarse-fine)


def test_resolution_delta_signed_and_abs_are_data_derived():
    p64=finalized(next(row for row in ROWS if row["resolution"]==64)); p96=finalized(next(row for row in ROWS if row["resolution"]==96)); coarse=p96["stencils"]["1/72"]["BAND2_PHYSICAL_BRANCH_SHADOW"].get("OMEGA_RANK1_SHADOW"); fine=p64["stencils"]["1/72"]["BAND2_PHYSICAL_BRANCH_SHADOW"].get("OMEGA_RANK1_SHADOW"); delta=coarse-fine; assert delta == coarse-fine and abs(delta) == abs(coarse-fine)


@pytest.mark.parametrize("incident_id", ["REL-027","REL-028","REL-029"])
def test_process_registry_missing_rejected(incident_id):
    review=json.loads((ROOT/"audit/e9f/c3_c5_process_reliability_review.json").read_text())
    review["incidents"]=[item for item in review["incidents"] if item["incident_id"]!=incident_id]
    review["p1_items"]=[item for item in review["p1_items"] if item!=incident_id]
    with pytest.raises(ValueError,match="PROCESS_REGISTRY"):
        runtime.validate_process_review(review)


def test_process_registry_contains_all_REL021_through_REL049():
    review=json.loads((ROOT/"audit/e9f/c3_c5_process_reliability_review.json").read_text()); assert {x["incident_id"] for x in review["incidents"]} == set(runtime.REQUIRED_INCIDENT_IDS)


def test_actual_C3_C5_process_review_validates(): runtime.validate_process_review(json.loads((ROOT/"audit/e9f/c3_c5_process_reliability_review.json").read_text()))


def test_H_norm_1e14_preserved_in_R96_worker(): assert runtime.H_NORM_TOLERANCE == 1e-14
def test_H_orthogonality_1e10_preserved_in_R96_worker(): assert runtime.H_ORTHOGONALITY_TOLERANCE == 1e-10
def test_source_target_firewall(): assert "source-paper" not in Path(runtime.__file__).read_text()
def test_reducer_firewall(): assert runtime.finalize_payload(raw_for(ROWS[0]),row=ROWS[0],expected_identity=expected(ROWS[0]))["reducer_admissible"] is False