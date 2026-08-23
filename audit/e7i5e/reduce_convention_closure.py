import ast,json,hashlib,math,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
RAW_SHA="8e2e8c6a0320c0bd172586704fb13ad9d7df839b1585a1717bca97a525c11c08"
E7I5D_RESULT_SHA="328cdcaeb51ef39b481cff56bdd58d325be777ef6b14104dfa0fb9c8bb07b633"
MANIFEST_SHA="15b54229c13e122edef69df428783b9bb57332afc88a411f18efdf9d53a9fadb"
CONTRACT_SHA="7010bde6e89257fc062c531ca26cb7cacd919d08121e5dc1cc927ab0a2f44457"
PAPER_GAPS=(.045,.044)
def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path): return json.loads(Path(path).read_text())
def component_errors(row):
 return [row["abs_error_f1"],row["abs_error_f2"],row["abs_error_f3"],row["abs_error_gap21"],row["abs_error_gap32"]]
def component_changes(candidate,base):
 cr=candidate["R48"]; br=base["48"]
 keys=("abs_error_f1","abs_error_f2","abs_error_f3","abs_error_gap21","abs_error_gap32")
 return {key:cr[key]-br[key] for key in keys}
def classify(candidate,base):
 cr=candidate["R48"]; delta=component_changes(candidate,base)
 scale=[delta["abs_error_f1"],delta["abs_error_f2"],delta["abs_error_f3"]]
 gap=[delta["abs_error_gap21"],delta["abs_error_gap32"]]
 if candidate["candidate_id"]=="MATERIAL_N2P65_INTERPRETATION_DIAGNOSTIC" and all(x<0 for x in scale) and cr["gap21"]<PAPER_GAPS[0] and cr["gap32"]<PAPER_GAPS[1]:
  return "ABSOLUTE_FREQUENCY_SCALE_STRONGLY_IMPROVED_BUT_TWO_GAP_STRUCTURE_REMAINS_INCOMPATIBLE_WITH_PAPER"
 if candidate["candidate_id"]=="ALTERNATE_MPB_TM_CONVENTION_DIAGNOSTIC" and not all(x<0 for x in scale) and gap[0]>0 and gap[1]<0:
  return "ABSOLUTE_FREQUENCY_SCALE_NOT_RECOVERED_AND_GAP_RESPONSE_MIXED"
 raise AssertionError("component-wise classification did not match supervisor rule")
def self_check(root,raw):
 assert digest(root/"audit/e7i5e/result.json")==RAW_SHA
 assert digest(root/"audit/e7i5d/result.json")==E7I5D_RESULT_SHA
 assert digest(root/"audit/e7i5d/source_manifest.json")==MANIFEST_SHA
 assert digest(root/"audit/e7i5d/source_contract.json")==CONTRACT_SHA
 live=[x for x in raw["diagnostics"] if x["candidate_id"]!="BASELINE_REUSE"]
 assert len(live)==2 and len({x["candidate_id"] for x in live})==2
 assert not any(x["background_epsilon"]==7.0225 and x["polarization"]=="TM" for x in raw["candidate_list"]["candidates"])
 tree=ast.parse(Path(__file__).read_text())
 imports=[n.module or "" for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
 imports += [a.name for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names]
 assert not any(any(token in name.lower() for token in ("meep","mpb","berry","chern","wilson")) for name in imports)
 assert "sum(" not in Path(__file__).read_text().split("def classify",1)[1].split("def self_check",1)[0]
def run(out):
 raw=read(ROOT/"audit/e7i5e/result.json"); self_check(ROOT,raw); base=raw["baseline"]; rows=[]
 for candidate in raw["diagnostics"]:
  delta=component_changes(candidate,base); rows.append({"candidate_id":candidate["candidate_id"],"R48_component_error_change_from_baseline":delta,"R48_mean_first3_frequency_ratio_to_paper":candidate["R48"]["mean_first3_frequency_ratio_to_paper"],"R64_mean_first3_frequency_ratio_to_paper":candidate["R64"]["mean_first3_frequency_ratio_to_paper"],"classification":classify(candidate,base)})
 e7i5a=read(ROOT/"audit/e7i5a/result.json"); e7i4f=read(ROOT/"audit/e7i4f/result.json"); e7i5b=read(ROOT/"audit/e7i5b/result.json")
 stage1=float(e7i5a["sealed_composite_stage1_chern"]); stage2=float(e7i4f.get("stage2_composite_valley_chern",e7i4f["composite_valley_chern"]))
 levels=e7i5b["bands"]["0"]["levels"]; local=next(x for x in levels if math.isclose(float(x["delta"]),1/144,rel_tol=0,abs_tol=1e-15))
 closure={"schema":"e7i5e_componentwise_closure_v1","work_order":"TRILATT-E7I5E-C1-20260824-158","raw_e7i5e_result_sha256":RAW_SHA,"e7i5d_evidence_commit":"ebd99df0c6c41496d84b3084d9bbf8c28328e964","e7i5e_candidate_commit":"cdec92535304cbe261093223c0d03f897cdccad0","e7i5e_calculation_code_sha":"91d7f6f2ef1ef9b9ab4df0a030e6ce3e27d3fbc8","e7i5e_evidence_sha":"06f0068bf52f3922f694c46dfa8d5ab6b49aef88","component_wise_replay":rows,"paper_reference_model_recovered":False,"no_further_dai_parameter_hunt":True,"dai_fr00_reference_branch":"CLOSED","material_semantics_status":"POSSIBLE_PARTIAL_FREQUENCY_SCALE_CONTRIBUTOR_NOT_SOURCE_BOUND","polarization_convention_status":"DISFAVORED_AS_PRIMARY_ROOT_CAUSE","remaining_source_ambiguity":"PUBLIC_ARTIFACTS_INSUFFICIENT_FOR_EXACT_COMSOL_CONTRACT","internal_results":{"stage1":{"status":"VALID","value":stage1,"source":"audit/e7i5a/result.json"},"stage2":{"status":"VALID","value":stage2,"source":"audit/e7i4f/result.json"},"rank1_full_domain":{"status":"PARTIAL_NOT_CHERN_QUALIFIED","full_coverage_qualified":bool(e7i5a["full_coverage_qualified"])},"k_local_band0":{"status":"QUALIFIED_AT_1OVER144_UNDER_INTERNAL_CONTRACT","delta":float(local["delta"]),"qualified":bool(local["qualified"]),"source":"audit/e7i5b/result.json"}},"dai_reproduction":{"composite_chern":"NOT_ESTABLISHED","individual_chern":"NOT_ESTABLISHED","local_berry":"NOT_ESTABLISHED"},"new_mpb_solves":False,"new_meep_solves":False,"new_berry_calculation":False,"new_chern_calculation":False,"new_source_parameter_candidate":False,"production_code_changed":False,"main_push":False,"e7i5e_c1_overall":"DAI_FR00_PUBLIC_SOURCE_REFERENCE_LIMITATION_FORMALLY_CLOSED"}
 out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(closure,sort_keys=True,indent=2)+chr(10)); return closure
if __name__=="__main__":
 if "--self-check" in sys.argv: self_check(ROOT,read(ROOT/"audit/e7i5e/result.json")); print("E7I5E_C1_SELF_CHECK=PASS")
 else:
  target=Path(sys.argv[sys.argv.index("--output")+1]) if "--output" in sys.argv else ROOT/"audit/e7i5e/closure.json"; print(json.dumps({"schema":run(target)["schema"],"output":str(target)}))
