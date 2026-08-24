"""C3.C5 complete six-sample, two-resolution diagnostic matrix runner."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Mapping

from audit.e9f import c3_c2_hardening as c2
from audit.e9f import c3_c4_runtime as c4
from audit.e9f import c3_c5_runtime as runtime
from audit.e9f import run_e9f_c1_rp2_c3_c2_impl as c2science
from audit.e9f import c4_process
from audit.e9f import c5_checkpoint

WORKER = Path("audit/e9f/run_e9f_c1_rp2_c3_c5_worker.py")
CONTRACT = Path("audit/e9f/rp2_c3_c5_execution_contract.json")


def git(root: Path, *args: str) -> str: return subprocess.check_output(["git", *args], cwd=root, text=True).strip()
def tail(data: bytes) -> str: return data[-65536:].decode(errors="replace")


def load_contract(root: Path) -> dict[str, Any]:
    value = json.loads((root / CONTRACT).read_text())
    if value.get("work_order_id") != runtime.WORK_ORDER or value.get("parent_failed_execution_sha") != runtime.FAILED_PARENT_EXECUTION_SHA or value.get("runner_relative_path") != str(runtime.RUNNER_RELATIVE_PATH).replace("\\", "/"): raise ValueError("C3_C5_CONTRACT_IDENTITY")
    if tuple(value.get("required_incident_ids", ())) != runtime.REQUIRED_INCIDENT_IDS or value.get("open_p1") != list(runtime.OPEN_P1): raise ValueError("C3_C5_CONTRACT_REGISTRY")
    return value


def run_prelive(root: Path) -> dict[str, Any]:
    tests = ["tests/test_e9f_c1_rp2_c3_c2.py", "tests/test_e9f_c1_rp2_c3_c2_required_nodes.py", "tests/test_e9f_c1_rp2_c3_c3.py", "tests/test_e9f_c1_rp2_c3_c3_required_nodes.py", "tests/test_e9f_c1_rp2_c3_c4.py", "tests/test_e9f_c1_rp2_c3_c4_required_nodes.py", "tests/test_e9f_c1_rp2_c3_c5.py", "tests/test_e9f_c1_rp2_c3_c5_required_nodes.py"]
    runtime.validate_process_review(json.loads((root / "audit/e9f/c3_c5_process_reliability_review.json").read_text()))
    command = [sys.executable, "-m", "pytest", "-q", *tests, "--disable-warnings"]; collect = subprocess.run([*command, "--collect-only"], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True); nodes = [line.strip() for line in (collect.stdout + collect.stderr).splitlines() if "::" in line]; process = subprocess.run(command, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True); output = process.stdout + process.stderr
    manifest = {"schema":"mephc_e9f_c1_rp2_c3_c5_prelive_manifest_v1","work_order_id":runtime.WORK_ORDER,"pytest_exit_status":process.returncode,"pytest_node_ids":nodes,"pytest_node_count":len(nodes),"pytest_output_tail":output[-65536:],"placeholder_pass_scan":"PASSED" if "checks[" not in (root/"tests/test_e9f_c1_rp2_c3_c5.py").read_text() else "FAILED"}; runtime.atomic_write(root/"audit/e9f/c3_c5_prelive_manifest.json",manifest)
    if process.returncode != 0 or manifest["placeholder_pass_scan"] != "PASSED": raise RuntimeError(f"C3_C5_PRELIVE_FAILED:{manifest}")
    return manifest


def rss() -> int | None:
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmRSS:"): return int(line.split()[1])
    except OSError: return None
    return None


def run_child(root: Path, row: Mapping[str, Any], runtime_root: Path, execution: str, contract_sha: str, policy_sha: str) -> tuple[dict[str, Any], dict[str, Any]]:
    slot = runtime_root / "workers" / hashlib.sha256(row["sample_id"].encode()).hexdigest()[:32]; slot.mkdir(parents=True, exist_ok=False); payload_path = slot/"payload.json"; failure_path=slot/"failure.json"; identity=runtime.identity_for(row=row,execution_sha=execution,contract_sha256=contract_sha,policy_sha256=policy_sha); runtime.atomic_write(slot/"binding.json",{"schema":"mephc_e9f_c1_rp2_c3_c5_binding_v1",**identity,"payload_path":str(payload_path),"failure_path":str(failure_path),"artifact_schema":runtime.PAYLOAD_SCHEMA})
    command=[sys.executable,str(root/WORKER),"--root",str(root),"--worker-id",row["sample_id"],"--resolution",str(row["resolution"]),"--coordinate-json",json.dumps(row["authoritative_coordinate"],separators=(",",":")),"--payload-path",str(payload_path),"--failure-path",str(failure_path),"--execution-sha",execution,"--contract-sha256",contract_sha,"--rp1-policy-sha256",policy_sha]; before=rss(); started=time.monotonic(); child=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE); output,error=child.communicate(timeout=3600); orphan_pids=c4_process.scan_orphans(WORKER.name,row["sample_id"],(child.pid,)); measurement={"pid":int(child.pid),"return_code":int(child.returncode),"direct_pid_gone":not(Path("/proc")/str(child.pid)).exists(),"orphan_pids":orphan_pids,"orphan_count":len(orphan_pids),"stdout_byte_count":len(output),"stderr_byte_count":len(error),"stdout_sha256":hashlib.sha256(output).hexdigest(),"stderr_sha256":hashlib.sha256(error).hexdigest(),"stdout_tail":tail(output),"stderr_tail":tail(error),"parent_rss_before_kib":before,"parent_rss_after_kib":rss(),"elapsed_seconds":time.monotonic()-started,"worker_id":row["sample_id"],"resolution":row["resolution"],"payload_path":str(payload_path),"failure_path":str(failure_path),"failure_sidecar_exists":failure_path.exists()}
    if child.returncode != 0 or measurement["orphan_count"] != 0 or not measurement["direct_pid_gone"]: failure={"schema":"mephc_e9f_c1_rp2_c3_c5_parent_failure_v1","work_order_id":runtime.WORK_ORDER,"execution_sha":execution,"stage":"child_lifecycle","process_measurement":measurement,"child_failure_sidecar":json.loads(failure_path.read_text()) if failure_path.exists() else None}; runtime.atomic_write(runtime_root/"parent_failure.json",failure); raise RuntimeError(f"E9F_C1_RP2_C3_C5_MATRIX_INCOMPLETE_FAIL_CLOSED:{failure}")
    payload=json.loads(payload_path.read_text()); runtime.validate_payload(payload,row=row,expected_identity=identity); measurement.update({"payload_file_sha256":runtime.sha(payload_path),"payload_body_sha256":payload["payload_body_sha256"]}); return payload,measurement


def entry_record(payload: Mapping[str, Any], row: Mapping[str, Any], stencil: str) -> dict[str, Any]:
    entry=payload["stencils"][stencil]; return {"source_sample_id":row["source_sample_id"],"source_sample_index":row["source_sample_index"],"logical_sample_index":row["sample_index"],"resolution":row["resolution"],"stencil":stencil,"L0":entry["vertices"][0]["L0"],"association_loop_closure":entry["association"]["loop_closure"],"band2_phase":entry["BAND2_PHYSICAL_BRANCH_SHADOW"].get("PHI_RANK1_SHADOW"),"band2_omega":entry["BAND2_PHYSICAL_BRANCH_SHADOW"].get("OMEGA_RANK1_SHADOW"),"band3_phase":entry["BAND3_PHYSICAL_BRANCH_SHADOW"].get("PHI_RANK1_SHADOW"),"band3_omega":entry["BAND3_PHYSICAL_BRANCH_SHADOW"].get("OMEGA_RANK1_SHADOW"),"rank2_status":entry["L2_RANK2"]["wilson_status"],"rank2_det_phase":entry["L2_RANK2"].get("PHI_RANK2_DET"),"l3_residual":None if entry.get("L3") is None else entry["L3"].get("DELTA_PHASE_RANK1SUM_RANK2DET"),"h_max_full6":max(point["H_GATE"]["max_offdiag"] for point in [payload["center"]]+entry["vertices"]),"h_max_selected_pair":max(point["H_GATE"]["selected_pair_offdiag"] for point in [payload["center"]]+entry["vertices"]),"h_max_normalization":max(point["H_GATE"]["max_normalization_error"] for point in [payload["center"]]+entry["vertices"]),"replay_max":max(point["frequency_replay"]["max_abs_difference"] for point in [payload["center"]]+entry["vertices"])}


def main(argv: list[str]|None=None)->int:
    parser=argparse.ArgumentParser(); parser.add_argument("--root",default=str(Path(__file__).resolve().parents[2])); parser.add_argument("--runtime-root",default=None); args=parser.parse_args(argv); root=Path(args.root).resolve(); actual_runner=runtime.runner_path(root,Path(__file__)); contract=load_contract(root); rows=runtime.build_plan(root)
    if len(rows) != 12 or len({row["sample_id"] for row in rows}) != 12 or sum(row["resolution"] == 64 for row in rows) != 6 or sum(row["resolution"] == 96 for row in rows) != 6:
        raise RuntimeError("C3_C5_MATRIX_PLAN_NOT_FIXED_SIX_BY_TWO")
    prelive=run_prelive(root); execution=git(root,"rev-parse","HEAD"); contract_sha=runtime.sha(root/CONTRACT); policy_sha=runtime.sha(root/c2science.POLICY_REL); runtime_root=Path(args.runtime_root) if args.runtime_root else root/"audit/e9f/rp2_c3_c5_runtime"; runtime_root.mkdir(parents=True,exist_ok=False); payloads=[]; measurements=[]; completed=[]; row_map={row["sample_id"]:row for row in rows}
    for row in rows:
        payload,measurement=run_child(root,row,runtime_root,execution,contract_sha,policy_sha); payloads.append(payload); measurements.append(measurement); completed.append({"worker_id":row["sample_id"],"resolution":row["resolution"],"payload_path":measurement["payload_path"],"payload_file_sha256":measurement["payload_file_sha256"],"payload_body_sha256":measurement["payload_body_sha256"]}); checkpoint=runtime.construct_checkpoint(completed=completed,execution_sha=execution,contract_sha256=contract_sha,policy_sha256=policy_sha,generation=len(completed)); c5_checkpoint.validate(checkpoint,root=root,rows=row_map); runtime.atomic_write(runtime_root/"matrix_checkpoint.json",checkpoint)
    if len(payloads) != 12 or sum(payload["solve_count"] for payload in payloads) != 108:
        raise RuntimeError("C3_C5_MATRIX_COMPLETION_NOT_108_SOLVES")
    summary=runtime.matrix_summary(payloads); summary.update({"native_child_pids":[measurement["pid"] for measurement in measurements],"total_orphan_count":sum(measurement["orphan_count"] for measurement in measurements),"parent_rss_min_kib":min(measurement["parent_rss_before_kib"] for measurement in measurements),"parent_rss_max_kib":max(measurement["parent_rss_after_kib"] for measurement in measurements)})
    entries=[entry_record(payload,row,stencil) for payload,row in zip(payloads,rows) for stencil in ("1/72","1/144")]; by_key={(row["source_sample_id"],row["resolution"],stencil):entry for row,payload in zip(rows,payloads) for stencil,entry in ((stencil,entry_record(payload,row,stencil)) for stencil in ("1/72","1/144"))}; deltas=[]
    for row in rows[::2]:
        for branch in ("band2_omega","band3_omega"):
            for sample in {row["source_sample_id"]}:
                coarse=by_key[(sample,64,"1/144")][branch]; fine=by_key[(sample,64,"1/72")][branch]; r64=by_key[(sample,64,"1/72")][branch]; r96=by_key[(sample,96,"1/72")][branch]; deltas.append({"source_sample_id":sample,"branch":branch,"stencil_delta_signed":coarse-fine,"stencil_delta_abs":abs(coarse-fine),"resolution_delta_signed":r96-r64,"resolution_delta_abs":abs(r96-r64)})
    result={"status":"E9F_C1_RP2_C3_C5_FIXED_SIX_H_MATRIX_COMPLETE_READY_FOR_RP3_POLICY_DECISION","project_id":"MEPHC","work_order_id":runtime.WORK_ORDER,"base_sha":runtime.FAILED_PARENT_EXECUTION_SHA,"execution_sha":execution,"contract_sha256":contract_sha,"runner_sha256":runtime.sha(actual_runner),"prelive":prelive,"summary":summary,"entries":entries,"deltas":deltas,"measurements":measurements,"payloads":payloads,"process_review_valid":True,"pipeline_health":"PIPELINE_REQUIRES_CORRECTIVE"}; runtime.atomic_write(runtime_root/"c3_c5_matrix_result.json",result); manifest={"schema":"mephc_e9f_c1_rp2_c3_c5_matrix_manifest_v1","work_order_id":runtime.WORK_ORDER,"execution_sha":execution,"checkpoint_sha256":runtime.sha(runtime_root/"matrix_checkpoint.json"),"result_sha256":runtime.sha(runtime_root/"c3_c5_matrix_result.json"),"worker_count":12,"matrix_entry_count":24,"total_native_solves":108}; runtime.atomic_write(runtime_root/"c3_c5_matrix_manifest.json",manifest); print(json.dumps({"status":result["status"],"execution_sha":execution,"worker_count":12,"matrix_entry_count":24,"total_native_solves":108,"result_sha256":runtime.sha(runtime_root/"c3_c5_matrix_result.json"),"manifest_sha256":runtime.sha(runtime_root/"c3_c5_matrix_manifest.json")},sort_keys=True)); return 0


if __name__ == "__main__": raise SystemExit(main())
