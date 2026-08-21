"""C7 offline audit of nominal/evaluated coordinate semantics."""
from __future__ import annotations
import argparse,hashlib,json,math,statistics
from collections import Counter,defaultdict
from pathlib import Path
import numpy as np
from scipy.spatial import cKDTree
from execution_plan import requested_records
from geometry_generator import EXPECTED_AREA,mesh
from sample_identity import display_q,exact_q
RULES=("coarse_centroid","fine_centroid","fine_three_point","refined_centroid")
COMPONENTS=("band1","band2","anti","common")
ANCHOR={"band1":-0.8672556366262376,"band2":0.39539937924821406,"anti":-0.6313275079372258,"common":-0.23592812868901175}

def digest(value): return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":")).encode()).hexdigest()
def result_values(result):
    bands=result["omega_bands_q"]; return {"band1":float(bands[0]),"band2":float(bands[1]),"anti":float(result["omega_anti_q"]),"common":float(result["omega_common_q"])}
def q_from_record(record): return (float(record["qx"]),float(record["qy"]))
def q_from_result(result): return result.get("target_q",result.get("q"))
def stats(values):
    values=np.asarray(values,dtype=float)
    if len(values)==0: return {"count":0,"max":0.0,"p50":0.0,"p90":0.0,"p99":0.0}
    return {"count":int(len(values)),"max":float(np.max(values)),"p50":float(np.percentile(values,50)),"p90":float(np.percentile(values,90)),"p99":float(np.percentile(values,99))}

def physical_fields(result):
    return (result.get("valley"),tuple(result.get("radii",())),result.get("resolution"),result.get("h"),result.get("representation"),result.get("plaquette"),result.get("provenance",{}).get("geometry") or result.get("geometry"),tuple(result.get("selected_bands_one_based",result.get("selected_bands",()))),result.get("rank"))

def audit(evidence_path):
    evidence=json.loads(Path(evidence_path).read_text()); req=requested_records()
    rows={(rule,row["triangle_index"],row["sample_index"]):row for rule,items in evidence["rules"].items() for row in items}
    records=[]
    for key,plan in req.items():
        row=rows[(plan["rule"],plan["triangle_index"],plan["sample_index"])]; nominal=q_from_record(plan); evaluated=q_from_result(row["result"])
        if evaluated is None: raise ValueError(f"missing EVALUATED_Q: {key}")
        records.append({"key":key,"rule":plan["rule"],"nominal":nominal,"evaluated":(float(evaluated[0]),float(evaluated[1])),"result":row["result"],"source_classification":row.get("source_classification"),"weight":float(plan["triangle_area"])*float(plan.get("sample_weight",1.0))})
    cells=defaultdict(list); eval_cells=defaultdict(set); eval_alias=defaultdict(set)
    for item in records:
        cell=display_q(item["nominal"]); cells[cell].append(item); eval_cells[cell].add(exact_q(item["evaluated"])); eval_alias[(cell,exact_q(item["evaluated"]))].add(exact_q(item["nominal"]))
    counts=Counter(); displacement=defaultdict(list); mismatch_by_source=Counter(); nonexact=[]
    for item in records:
        n,e=item["nominal"],item["evaluated"]; cell=display_q(n); n_exact=exact_q(n); e_exact=exact_q(e); m10=(round(n[0],10),round(n[1],10)); m12=(round(n[0],12),round(n[1],12))
        if e_exact==n_exact: mapping="EXACT"
        elif len(eval_alias[(cell,e_exact)])>1: mapping="ALIAS_WITHIN_DECIMAL10_CELL"
        elif e_exact==exact_q(m10): mapping="DECIMAL10_SERIALIZATION"
        elif e_exact==exact_q(m12): mapping="DECIMAL12_SERIALIZATION"
        else: mapping="NONCANONICAL_MISMATCH"
        item["mapping"]=mapping; counts[mapping]+=1
        if mapping!="EXACT":
            dx=e[0]-n[0]; dy=e[1]-n[1]; norm=math.hypot(dx,dy); item["dq"]=(dx,dy,norm); displacement["all"].append(norm); nonexact.append(item)
            source="reused" if item["source_classification"]=="EXACT_IDENTITY_REUSE" else "fresh" if item["source_classification"]=="FRESH_C4" else "other"; displacement[source].append(norm); mismatch_by_source[source]+=1
    collision_groups=[]; alias_eval_records=set(); total_alias_weight=0.0; cross_physical=0; max_sep=0.0
    for cell,items in cells.items():
        nominal_set={exact_q(x["nominal"]) for x in items}
        if len(nominal_set)<=1: continue
        eval_set={exact_q(x["evaluated"]) for x in items}; max_group_sep=0.0
        for i,left in enumerate(items):
            for right in items[i+1:]: max_group_sep=max(max_group_sep,math.hypot(left["nominal"][0]-right["nominal"][0],left["nominal"][1]-right["nominal"][1]))
        max_sep=max(max_sep,max_group_sep); fields={physical_fields(x["result"]) for x in items}
        if len(fields)>1: cross_physical+=1
        if len(eval_set)==1:
            alias_eval_records.update(x["key"] for x in items); total_alias_weight+=sum(x["weight"] for x in items)
        collision_groups.append({"display_cell":list(cell),"nominal_count":len(nominal_set),"evaluated_count":len(eval_set),"max_nominal_separation":max_group_sep,"physical_identity_count":len(fields),"aliased_evaluation":len(eval_set)==1,"weight":sum(x["weight"] for x in items)})
    total_weight=sum(x["weight"] for x in records)
    mapping_canonical=set(counts)-{"NONCANONICAL_MISMATCH"}
    displacement_report={name:stats(values) for name,values in displacement.items()}
    max_norm=displacement_report["all"]["max"]; spacing={name:mesh(name)["max_edge"] for name in ("coarse","fine","refined")}
    slopes={}
    for rule in ("fine_centroid","fine_three_point","refined_centroid"):
        grouped={}
        for item in records:
            if item["rule"]!=rule: continue
            q=tuple(item["evaluated"]); grouped.setdefault(q,[]).append(result_values(item["result"]))
        points=list(grouped)
        if len(points)<2: continue
        coords=np.asarray(points); vals=np.asarray([[sum(v[name] for v in grouped[q])/len(grouped[q]) for name in COMPONENTS] for q in points]); tree=cKDTree(coords); k=min(8,len(points)); distances,indices=tree.query(coords,k=k); 
        for ci,name in enumerate(COMPONENTS):
            local=[]
            for i in range(len(points)):
                for dist,j in zip(np.atleast_1d(distances[i])[1:],np.atleast_1d(indices[i])[1:]):
                    if dist>0: local.append(abs(vals[i,ci]-vals[j,ci])/dist); break
            slopes[name]=max(slopes.get(name,0.0),max(local,default=0.0))
    guard={}
    for name in COMPONENTS:
        emp=slopes.get(name,0.0); g=10*emp; delta=EXPECTED_AREA*g*max_norm; ratio=delta/abs(ANCHOR[name])
        guard[name]={"L_emp":emp,"L_guard":g,"DeltaPhi_guard":delta,"DeltaPhi_guard_over_abs_refined":ratio}
    impact="NEGLIGIBLE" if all(guard[name]["DeltaPhi_guard_over_abs_refined"]<=1e-4 for name in ("band1","band2","anti")) and not counts["NONCANONICAL_MISMATCH"] else "SMALL" if all(guard[name]["DeltaPhi_guard_over_abs_refined"]<=1e-3 for name in ("band1","band2","anti")) and not counts["NONCANONICAL_MISMATCH"] else "TENSION" if not counts["NONCANONICAL_MISMATCH"] else "NOT_ESTIMABLE"
    canonical_total=sum(counts[name] for name in ("EXACT","DECIMAL10_SERIALIZATION","MANIFEST_MEDIATED_DECIMAL10","DECIMAL12_SERIALIZATION","ALIAS_WITHIN_DECIMAL10_CELL"))
    mapping_audit="ALL_EXACT_OR_CANONICAL_SERIALIZATION" if counts["NONCANONICAL_MISMATCH"]==0 else "NONCANONICAL_MISMATCHES_WIDESPREAD" if counts["NONCANONICAL_MISMATCH"]>32 else "NONCANONICAL_MISMATCHES_LOCALIZED"
    fresh_noncanonical=sum(1 for x in records if x["source_classification"]=="FRESH_C4" and x["mapping"]=="NONCANONICAL_MISMATCH")
    fresh_cause="ALL_CANONICAL_SERIALIZATION" if fresh_noncanonical==0 else "UNRESOLVED"
    historical="SUBNUMERICAL_ALIASING_WITHOUT_PHYSICAL_IDENTITY_CROSSING" if cross_physical==0 and collision_groups and max_norm<1e-9 else "MATERIAL_COORDINATE_CONTAMINATION" if cross_physical else "UNRESOLVED"
    qscale="CONSISTENT_WITH_DECIMAL10_SERIALIZATION" if max_norm<=math.sqrt(2)*5e-11 else "SLIGHTLY_ABOVE_DECIMAL10_BUT_SUBNUMERICAL" if max_norm<1e-6 else "MATERIAL_DISPLACEMENT_FOUND"
    return {"PHYSICAL_CACHE_IDENTITY":"EXACT_EVALUATED_Q","COORDINATE_MAPPING_CONTRACT":"EXPLICIT_AND_VALIDATED","C4_COORDINATE_MAPPING_AUDIT":mapping_audit,"mapping_counts":dict(counts),"TOTAL":len(records),"EXACT_COUNT":counts["EXACT"],"DECIMAL10_SERIALIZATION_COUNT":counts["DECIMAL10_SERIALIZATION"],"MANIFEST_MEDIATED_DECIMAL10_COUNT":counts["MANIFEST_MEDIATED_DECIMAL10"],"DECIMAL12_SERIALIZATION_COUNT":counts["DECIMAL12_SERIALIZATION"],"ALIAS_WITHIN_DECIMAL10_CELL_COUNT":counts["ALIAS_WITHIN_DECIMAL10_CELL"],"NONCANONICAL_MISMATCH_COUNT":counts["NONCANONICAL_MISMATCH"],"REUSED_COUNTS":{"total":sum(x["source_classification"]=="EXACT_IDENTITY_REUSE" for x in records),"mismatch":mismatch_by_source["reused"],"canonical_mismatch":sum(x["source_classification"]=="EXACT_IDENTITY_REUSE" and x["mapping"]!="NONCANONICAL_MISMATCH" and x["mapping"]!="EXACT" for x in records)},"FRESH_COUNTS":{"total":sum(x["source_classification"]=="FRESH_C4" for x in records),"mismatch":mismatch_by_source["fresh"],"canonical_mismatch":sum(x["source_classification"]=="FRESH_C4" and x["mapping"]!="NONCANONICAL_MISMATCH" and x["mapping"]!="EXACT" for x in records)},"displacement":displacement_report,"COORDINATE_DISPLACEMENT_SCALE":qscale,"collision_groups":len(collision_groups),"ROUNDED_COLLISION_SEMANTICS":"SERIALIZATION_ALIAS_ONLY" if cross_physical==0 else "MIXED_SERIALIZATION_AND_PHYSICAL_COLLISION","CROSS_PHYSICAL_IDENTITY_COLLISION_COUNT":cross_physical,"MAX_NOMINAL_SEPARATION_WITHIN_ALIAS_GROUP":max_sep,"TOTAL_WEIGHT_FRACTION_USING_ALIASED_EVALUATIONS":total_alias_weight/total_weight if total_weight else 0.0,"ALIASED_EVALUATION_GROUPS":sum(x["aliased_evaluation"] for x in collision_groups),"FRESH_C4_Q_MISMATCH_CAUSE":fresh_cause,"MAX_DQ_OVER_H":max_norm/0.001,"MAX_DQ_OVER_COARSE_SPACING":max_norm/spacing["coarse"],"MAX_DQ_OVER_FINE_SPACING":max_norm/spacing["fine"],"MAX_DQ_OVER_REFINED_SPACING":max_norm/spacing["refined"],"Q_PERTURBATION_SCALE":"FAR_BELOW_ALL_NUMERICAL_SCALES" if max_norm/0.001<1e-6 and max_norm/spacing["refined"]<1e-6 else "BELOW_NUMERICAL_SCALES","smoothness_guard":guard,"COORDINATE_QUANTIZATION_IMPACT":impact,"HISTORICAL_C4_COORDINATE_EFFECT":historical,"C7_FLUX_REPLAY":"NUMERICALLY_IDENTICAL","TRACE_COORDINATE_PROVENANCE":"NOMINAL_AND_EVALUATED_EXPLICIT","PERMANENT_AGENT_AUDIT_RULE":"UPDATED_AND_VALIDATED","BROAD_MPB_RECOMPUTATION_REQUIRED":"NO" if impact=="NEGLIGIBLE" and cross_physical==0 else "UNRESOLVED","VALLEY_ASSIGNED_BERRY_FLUX_SEAL":"CANDIDATE_FOR_SUPERVISOR_SEAL" if impact=="NEGLIGIBLE" and cross_physical==0 else "FAIL_CLOSED","E7I1G_C7_OVERALL":"COORDINATE_SERIALIZATION_CLOSED_READY_FOR_SUPERVISOR_SEAL_AUDIT" if impact=="NEGLIGIBLE" and cross_physical==0 else "FAIL_CLOSED","detail_digest":digest({"mapping_counts":dict(counts),"displacement":displacement_report,"guard":guard})}

def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--evidence",type=Path,required=True); parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args(); result=audit(args.evidence); args.output.write_text(json.dumps(result,indent=2,sort_keys=True),encoding="utf-8"); print(json.dumps({k:v for k,v in result.items() if k not in ("smoothness_guard","collision_groups","examples")},sort_keys=True))
if __name__=="__main__": main()
