import hashlib,json,math,subprocess,sys,time
from pathlib import Path
import meep as mp
from audit.e7i3c.run_representation_bridge import build_triangular_coordinate_preflight
from mephc.mpb_energy_spectral_provider import MPBLiveEnergySpectralProvider
from mephc.mpb_reference_adapter import build_reference_mpb_adapter
from mephc.valley_reference_geometry import build_triangular_reference_geometry
K=(2/3,0); KM=(1/3,1/3)
P=(.265748031496063,.3136482939632546,.35761154855643046); G=(.045,.044)
B={48:(.4127885526847116,.4324603969585135,.4374999521076174,.8359496983403484),64:(.4128386288270905,.43259270691012874,.43779271088014937,.8361580223439125)}
RS="328cdcaeb51ef39b481cff56bdd58d325be777ef6b14104dfa0fb9c8bb07b633"
MS="15b54229c13e122edef69df428783b9bb57332afc88a411f18efdf9d53a9fadb"
CS="7010bde6e89257fc062c531ca26cb7cacd919d08121e5dc1cc927ab0a2f44457"
def digest(x): return hashlib.sha256(Path(x).read_bytes()).hexdigest()
def metric(v):
 f=[float(x) for x in v]
 if len(f)!=4 or not all(math.isfinite(x) for x in f): raise RuntimeError("four finite bands required")
 a,b=f[1]-f[0],f[2]-f[1]; e=[abs(f[i]-P[i]) for i in range(3)]
 return {"frequencies":f,"gap21":a,"gap32":b,"absolute_scale_vector":f[:3],"paper_absolute_scale_vector":list(P),"gap_vector":[a,b],"paper_gap_vector":list(G),"abs_error_f1":e[0],"abs_error_f2":e[1],"abs_error_f3":e[2],"abs_error_gap21":abs(a-G[0]),"abs_error_gap32":abs(b-G[1]),"mean_first3_frequency":sum(f[:3])/3,"mean_first3_frequency_ratio_to_paper":(sum(f[:3])/3)/(sum(P)/3)}
def baseline(): return {str(k):metric(v) for k,v in B.items()}
def classify(row):
 b=baseline(); s=sum(row["R48"]["abs_error_f"+str(i)] for i in (1,2,3)); bs=sum(b["48"]["abs_error_f"+str(i)] for i in (1,2,3)); g=row["R48"]["abs_error_gap21"]+row["R48"]["abs_error_gap32"]; bg=b["48"]["abs_error_gap21"]+b["48"]["abs_error_gap32"]
 if s<bs and g<bg: return "BOTH_ABSOLUTE_SCALE_AND_GAP_STRUCTURE_IMPROVED"
 if s<bs: return "ABSOLUTE_SCALE_IMPROVED_BUT_GAP_STRUCTURE_MISMATCHED"
 if g<bg: return "GAP_STRUCTURE_IMPROVED_BUT_ABSOLUTE_SCALE_MISMATCHED"
 return "SPECTRALLY_STRONGLY_DISFAVORED"
def checks(root,c):
 ids=[x["candidate_id"] for x in c["candidates"]]
 assert ids==["BASELINE_REUSE","MATERIAL_N2P65_INTERPRETATION_DIAGNOSTIC","ALTERNATE_MPB_TM_CONVENTION_DIAGNOSTIC"]
 assert sum(bool(x["new_live_diagnostic"]) for x in c["candidates"])==2
 assert c["forbidden_combined_candidate"]=={"background_epsilon":7.0225,"polarization":"TM"}
 assert c["exact_k"]["resolutions"]==[48,64] and c["exact_k"]["num_bands"]==4
 p=build_triangular_coordinate_preflight(); assert p.ready and tuple(round(float(x),12) for x in p.public_q_to_mpb(K))==tuple(round(x,12) for x in KM)
 g=build_triangular_reference_geometry(0); assert abs(float(g.air_area/g.cell_area)-.107)<=5e-13 and abs(float(g.triangle_orientation_degrees)%120-90)<1e-12
 assert digest(root/"audit/e7i5d/result.json")==RS and digest(root/"audit/e7i5d/source_manifest.json")==MS and digest(root/"audit/e7i5d/source_contract.json")==CS
def solve(c,a,count):
 pol=mp.TE if c["polarization"]=="TE" else mp.TM; out={}
 for r in (48,64):
  p=MPBLiveEnergySpectralProvider(geometry=list(a.geometry),geometry_lattice=a.geometry_lattice,resolution=r,num_bands=4,polarization=pol,default_material=mp.Medium(epsilon=float(c["background_epsilon"])),eigensolver_tolerance=1e-7,deterministic=True,mesh_size=3)
  raw=p.solve(K); count[0]+=1; out["R"+str(r)]=metric(raw.frequencies); out["R"+str(r)]["solver_provenance"]=str(raw.provenance)
 row={"candidate_id":c["candidate_id"],"background_epsilon":c["background_epsilon"],"polarization":c["polarization"],"R48":out["R48"],"R64":out["R64"]}
 row.update({"R48_R64_drift_f1":abs(out["R48"]["frequencies"][0]-out["R64"]["frequencies"][0]),"R48_R64_drift_f2":abs(out["R48"]["frequencies"][1]-out["R64"]["frequencies"][1]),"R48_R64_drift_f3":abs(out["R48"]["frequencies"][2]-out["R64"]["frequencies"][2]),"R48_R64_drift_gap21":abs(out["R48"]["gap21"]-out["R64"]["gap21"]),"R48_R64_drift_gap32":abs(out["R48"]["gap32"]-out["R64"]["gap32"])})
 row["candidate_spectral_classification"]=classify(row); return row
def run(out):
 root=Path(__file__).resolve().parents[2]; c=json.loads((root/"audit/e7i5e/candidates.json").read_text()); checks(root,c); g=build_triangular_reference_geometry(0); p=build_triangular_coordinate_preflight(); a=build_reference_mpb_adapter(g,p); count=[0]; t=time.monotonic(); rows=[solve(x,a,count) for x in c["candidates"] if x["new_live_diagnostic"]]
 mat=next(x for x in rows if x["candidate_id"].startswith("MATERIAL")); pol=next(x for x in rows if x["candidate_id"].startswith("ALTERNATE")); joint=any(x["candidate_spectral_classification"]=="BOTH_ABSOLUTE_SCALE_AND_GAP_STRUCTURE_IMPROVED" for x in rows)
 payload={"schema":"e7i5e_convention_diagnostics_v1","complete":True,"work_order":"TRILATT-E7I5E-20260824-156","code_change":"SANDBOX_AUDIT_ONLY","source_e7i5d_binding":{"evidence_commit":"ebd99df0c6c41496d84b3084d9bbf8c28328e964","source_manifest_json_sha256":MS,"source_contract_json_sha256":CS,"result_json_sha256":RS},"candidate_list":c,"candidate_list_committed_before_execution":True,"baseline_reused":True,"baseline":baseline(),"diagnostics":rows,"new_live_candidate_count":count[0]//2,"new_live_solve_count":count[0],"mapping":{"public_K":list(K),"mpb_fractional_K":list(p.public_q_to_mpb(K)),"expected_mpb_fractional_K":list(KM),"status":"VERIFIED"},"orientation_mod_120":90.0,"fill_factor":.107,"material_convention_diagnostic":"SUPPORTED_AS_LIKELY_CONTRIBUTOR" if mat["candidate_spectral_classification"]!="SPECTRALLY_STRONGLY_DISFAVORED" else "DISFAVORED","polarization_convention_diagnostic":"SUPPORTED_AS_LIKELY_CONTRIBUTOR" if pol["candidate_spectral_classification"]!="SPECTRALLY_STRONGLY_DISFAVORED" else "DISFAVORED","paper_reference_model_recovered":False,"dai_fr00_exact_model_recovery_status":"EMPIRICALLY_SUPPORTED_CONVENTION_HYPOTHESIS" if joint else "PUBLIC_SOURCE_ARTIFACTS_INSUFFICIENT","no_further_dai_parameter_hunt":not joint,"new_berry_calculation":"NOT_AUTHORIZED","new_chern_calculation":"NOT_AUTHORIZED","full_domain_run":False,"production_code_changed":False,"main_push":False,"calculation_code_git_sha":subprocess.check_output(["git","rev-parse","HEAD"],cwd=root,text=True).strip(),"telemetry":{"wall_time_seconds":time.monotonic()-t,"new_live_solve_count":count[0]},"E7I5E_overall":"DISCRETE_CONVENTION_DIAGNOSIS_COMPLETE"}
 out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(payload,sort_keys=True,indent=2)+chr(10)); return payload
if __name__=="__main__":
 root=Path(__file__).resolve().parents[2]; c=json.loads((root/"audit/e7i5e/candidates.json").read_text())
 if "--self-check" in sys.argv: checks(root,c); print("E7I5E_SELF_CHECK=PASS")
 else:
  o=Path(sys.argv[sys.argv.index("--output")+1]) if "--output" in sys.argv else root/"audit/e7i5e/result.json"; q=run(o); print(json.dumps({"schema":q["schema"],"new_live_candidate_count":q["new_live_candidate_count"],"new_live_solve_count":q["new_live_solve_count"],"telemetry":q["telemetry"]}))
