from pathlib import Path
import copy, hashlib, json
from audit.e9f import c3_c5_c1_postprocess as c1

ROOT = Path("/home/icy/MePhC/.c3-rp3-b-exec")
RUNTIME = Path("/home/icy/MePhC/.rp3-b-r160-runtime-20260825")
A_TRACE = Path("/home/icy/MePhC/.c3-c5-c1-live4/audit/e9f/rp3_a_r128_compact_trace.json")

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    result = json.loads((RUNTIME / "rp3_b_r160_result.json").read_text())
    a = json.loads(A_TRACE.read_text())
    old = json.loads((ROOT / "audit/e9f/c3_c5_c1_c1_postprocess.json").read_text())["complete_entries"]
    oldmap = {(x["source_sample_id"], int(x["resolution"]), x["stencil"]): x for x in old}
    amap = {(x["source_sample_id"], x["branch"], x["stencil"]): x for x in a["convergence_rows"]}
    rows=[]; spectral=[]; entries=[]
    for payload in result["payloads"]:
        sample=payload["source_sample_id"]
        for stencil in ("1/72","1/144"):
            old64=oldmap[(sample,64,stencil)]
            src=copy.deepcopy(payload["stencils"][stencil])
            assoc=src["association"]
            for edge in assoc["edges"]:
                edge["assignment"]=c1.derive_positional_assignment(edge, assoc["candidate_window_zero_based"])
            points=[payload["center"],*src["vertices"]]
            entries.append({"source_sample_id":sample,"source_sample_index":payload["source_sample_index"],"logical_sample_index":payload["logical_sample_index"],"worker_id":payload["worker_id"],"resolution":160,"stencil":stencil,"CENTER_L0":payload["center"]["L0"],"VERTEX_L0":[x["L0"] for x in src["vertices"]],"association":assoc,"BAND2":src["BAND2_PHYSICAL_BRANCH_SHADOW"],"BAND3":src["BAND3_PHYSICAL_BRANCH_SHADOW"],"L2":src["L2_RANK2"],"L3":src.get("L3"),"H_MAX":{"full6_offdiag":max(x["H_GATE"]["max_offdiag"] for x in points),"selected_pair_offdiag":max(x["H_GATE"]["selected_pair_offdiag"] for x in points),"normalization_error":max(x["H_GATE"]["max_normalization_error"] for x in points)},"replay_policy":"NOT_APPLICABLE_R160_ORIGINAL_RP2_HAS_NO_R160_KEY"})
            for branch,key in (("band2","BAND2"),("band3","BAND3")):
                r64=old64[key]["OMEGA_RANK1_SHADOW"]; r96=oldmap[(sample,96,stencil)][key]["OMEGA_RANK1_SHADOW"]; r128=amap[(sample,branch,stencil)]["omega_R128"]; r160=src[key+"_PHYSICAL_BRANCH_SHADOW"]["OMEGA_RANK1_SHADOW"]
                d1=r96-r64; d2=r128-r96; d3=r160-r128
                rows.append({"source_sample_id":sample,"branch":branch,"stencil":stencil,"omega_R64":r64,"omega_R96":r96,"omega_R128":r128,"omega_R160":r160,"delta_R64_to_R96_signed":d1,"delta_R64_to_R96_abs":abs(d1),"delta_R96_to_R128_signed":d2,"delta_R96_to_R128_abs":abs(d2),"delta_R128_to_R160_signed":d3,"delta_R128_to_R160_abs":abs(d3),"contraction_ratio_128_to_160":None if d2==0 else abs(d3)/abs(d2),"direction_relation":"ZERO_CASE" if d2==0 or d3==0 else ("SAME_DIRECTION" if d2*d3>0 else "REVERSAL")})
        l0a=next(x for x in a["spectral_rows"] if x["source_sample_id"]==sample)
        l0=payload["center"]["L0"]
        spectral.append({"source_sample_id":sample,"center_L0_R128":l0a["center_L0_R128"],"center_L0_R160":l0,"delta_L0_R128_to_R160":{k:l0[k]-l0a["center_L0_R128"][k] for k in ("lower_external_gap","internal_pair_gap","upper_external_gap")},"center_frequency_R160":payload["center"]["RAW_FREQUENCIES_ALL6"],"R160_REPLAY_POLICY":"NOT_APPLICABLE_R160"})
    by_sb={(x["source_sample_id"],x["branch"]):[] for x in rows}
    for x in rows: by_sb[(x["source_sample_id"],x["branch"])].append(x)
    for group in by_sb.values():
        vals={x["stencil"]:x["omega_R160"] for x in group}; d=vals["1/144"]-vals["1/72"]
        for x in group: x["R160_STENCIL_DELTA_SIGNED"]=d; x["R160_STENCIL_DELTA_ABS"]=abs(d)
    summary={}
    for branch in ("band2","band3"):
        q=[x for x in rows if x["branch"]==branch]; summary[branch]={"contraction_lt1":sum(x["contraction_ratio_128_to_160"] is not None and x["contraction_ratio_128_to_160"]<1 for x in q),"contraction_gt1":sum(x["contraction_ratio_128_to_160"] is not None and x["contraction_ratio_128_to_160"]>1 for x in q),"REVERSAL":sum(x["direction_relation"]=="REVERSAL" for x in q),"SAME_DIRECTION":sum(x["direction_relation"]=="SAME_DIRECTION" for x in q),"ZERO_CASE":sum(x["direction_relation"]=="ZERO_CASE" for x in q)}
    meas=[{"worker_id":m["worker_id"],"pid":m["pid"],"return_code":m["return_code"],"direct_pid_gone":m["direct_pid_gone"],"orphan_count":m["orphan_count"],"elapsed_seconds":m["elapsed_seconds"],"payload_file_sha256":m["payload_file_sha256"],"payload_body_sha256":m["payload_body_sha256"]} for m in result["measurements"]]
    out={"schema":"mephc_e9f_c1_rp3_b_r160_compact_trace_v1","work_order_id":result["work_order_id"],"execution_sha":result["execution_sha"],"source_r128_execution_sha":"39b63b80bf42d48e5b256dd1a211f6bec2585cd4","raw_runtime_root":str(RUNTIME),"raw_result_sha256":sha(RUNTIME/"rp3_b_r160_result.json"),"raw_manifest_sha256":sha(RUNTIME/"rp3_b_r160_manifest.json"),"raw_checkpoint_sha256":sha(RUNTIME/"matrix_checkpoint.json"),"authorized_native_solve_count":54,"actual_native_solve_count":result["actual_native_solve_count"],"worker_count":6,"entry_count":12,"replay_policy":result["replay_policy"],"convergence_rows":rows,"spectral_rows":spectral,"summary_counts":summary,"r128_compact_trace_sha256":sha(A_TRACE),"measurements":meas,"entries":entries,"no_convergence_verdict":True,"diagnostic_only":True,"reducer_admissible":False}
    p=ROOT/"audit/e9f/rp3_b_r160_compact_trace.json"; p.write_text(json.dumps(out,indent=2,sort_keys=True,allow_nan=False)+"
"); print(sha(p))
if __name__=="__main__": main()
