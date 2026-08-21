"""Generate a C7 trace with nominal/evaluated coordinate provenance."""
from __future__ import annotations
import argparse,hashlib,json
from pathlib import Path
from trace_generator import generate
def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def component_hashes():
    here=Path(__file__).parent
    return {"trace_generator_c7":digest(here/"trace_generator_c7.py"),"trace_generator_base":digest(here/"trace_generator.py"),"reducer_c7":digest(here/"reducer_c7.py"),"sample_identity":digest(here/"sample_identity.py"),"coordinate_semantics":digest(here/"coordinate_semantics.py")}
def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--evidence",type=Path,required=True); parser.add_argument("--lineage",type=Path,required=True); parser.add_argument("--output",type=Path,required=True); args=parser.parse_args()
    evidence=json.loads(args.evidence.read_text()); trace=generate(evidence,args.evidence); total=sum(len(rows) for rows in evidence["rules"].values()); qualified=sum(sum(row.get("result",{}).get("production_decision")=="QUALIFIED_VALUE" for row in rows) for rows in evidence["rules"].values())
    trace.update({"TRACE_VERSION":"c7-structured-v1","TRACE_GENERATOR_VERSION":"c7-trace-generator-v1","TRACE_GENERATOR_BLOB_OR_FILE_SHA256":digest(Path(__file__)),"SOURCE_C4_EVIDENCE_SHA256":digest(args.evidence),"SOURCE_RECORD_COUNT":total,"SOURCE_QUALIFIED_COUNT":qualified,"MANIFEST_LINEAGE_SHA256":digest(args.lineage),"AUDIT_COMPONENT_SHA256":component_hashes(),"TRACE_COORDINATE_PROVENANCE":"NOMINAL_AND_EVALUATED_EXPLICIT"})
    args.output.write_text(json.dumps(trace,indent=2,sort_keys=True),encoding="utf-8"); print(json.dumps({"event":"c7_trace_generated","source_record_count":total,"source_qualified_count":qualified},sort_keys=True))
if __name__=="__main__": main()
