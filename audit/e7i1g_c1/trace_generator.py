"""Generate a compact trace with exact-q sample identity digests."""
from __future__ import annotations
import argparse,hashlib,json
from pathlib import Path
from sample_identity import exact_q
from coordinate_semantics import coordinate_mapping
COMPONENTS=("band1","band2","anti","common")
CHUNK_SIZE=512
def _canonical(value): return json.dumps(value,separators=(",",":"),sort_keys=True).encode()
def _curvature(result): return {"band1":float(result["omega_bands_q"][0]),"band2":float(result["omega_bands_q"][1]),"anti":float(result["omega_anti_q"]),"common":float(result["omega_common_q"])}
def _record_key(record):
    key=(record.get("qx"),record.get("qy")) if record.get("qx") is not None and record.get("qy") is not None else record.get("q") or record.get("sample_key")
    if not key or len(key)!=2: raise ValueError("record lacks q")
    return (float(key[0]),float(key[1]))
def _chunk(rule,index,records):
    ordered=sorted(records,key=_record_key); first,last=_record_key(ordered[0]),_record_key(ordered[-1])
    signed_weight=sum(float(row["triangle_area"])*float(row.get("sample_weight",row.get("weight",1.0))) for row in ordered)
    qualified=sum(row.get("result",{}).get("production_decision")=="QUALIFIED_VALUE" for row in ordered)
    flux={component:0.0 for component in COMPONENTS}; canonical_records=[]
    for row in ordered:
        result=row.get("result")
        if result is None or result.get("production_decision")!="QUALIFIED_VALUE": continue
        weight=float(row["triangle_area"])*float(row.get("sample_weight",row.get("weight",1.0))); values=_curvature(result); physical_q=_record_key(row)
        for component in COMPONENTS: flux[component]+=weight*values[component]
        evaluated_q=tuple(float(value) for value in result.get("target_q",result.get("q",physical_q)))
        canonical_records.append({"nominal_q_exact":list(exact_q(physical_q)),"evaluated_q_exact":list(exact_q(evaluated_q)),"coordinate_mapping_class":coordinate_mapping(physical_q,evaluated_q),"display_sample_key":[round(physical_q[0],10),round(physical_q[1],10)],"triangle_index":row.get("triangle_index"),"sample_index":row.get("sample_index"),"triangle_area":float(row["triangle_area"]),"sample_weight":float(row.get("sample_weight",row.get("weight",1.0))),"result_digest":hashlib.sha256(_canonical(result)).hexdigest()})
    return {"rule":rule,"chunk_index":index,"first_sample_key":list(first),"last_sample_key":list(last),"input_record_count":len(ordered),"qualified_count":qualified,"signed_weight_sum":signed_weight,"weighted_curvature_sum":flux,"ordered_input_records_sha256":hashlib.sha256(_canonical(canonical_records)).hexdigest()}
def generate(evidence,raw_manifest):
    rules={}
    for rule,records in evidence["rules"].items():
        if not records: raise ValueError(f"empty rule: {rule}")
        ordered=sorted(records,key=_record_key); chunks=[_chunk(rule,index,ordered[start:start+CHUNK_SIZE]) for index,start in enumerate(range(0,len(ordered),CHUNK_SIZE))]
        flux={component:sum(float(chunk["weighted_curvature_sum"][component]) for chunk in chunks) for component in COMPONENTS}
        rules[rule]={"exact_domain":bool(evidence.get("exact_domain",{}).get(rule,False)),"total_record_count":len(ordered),"qualified_count":sum(chunk["qualified_count"] for chunk in chunks),"sum_signed_weights":sum(chunk["signed_weight_sum"] for chunk in chunks),"resulting_flux":flux,"chunks":chunks}
    return {"trace_version":"c4-structured-v1","trace_generator_version":"c4-trace-generator-v1","source_raw_manifest_sha256":hashlib.sha256(raw_manifest.read_bytes()).hexdigest(),"rules":rules}
def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--evidence",type=Path,required=True); parser.add_argument("--raw-manifest",type=Path,required=True); parser.add_argument("--output",type=Path,required=True); args=parser.parse_args()
    trace=generate(json.loads(args.evidence.read_text()),args.raw_manifest); args.output.write_text(json.dumps(trace,indent=2,sort_keys=True),encoding="utf-8")
if __name__=="__main__": main()
