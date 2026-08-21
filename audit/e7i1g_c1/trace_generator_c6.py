"""Generate the C6 trace and bind source evidence plus repository components."""
from __future__ import annotations
import argparse,hashlib,json
from pathlib import Path
from trace_generator import generate
def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def component_hashes():
    here=Path(__file__).parent
    return {"trace_generator_c6":digest(here/"trace_generator_c6.py"),"trace_generator_base":digest(here/"trace_generator.py"),"reducer_c6":digest(here/"reducer_c6.py"),"sample_identity":digest(here/"sample_identity.py")}
def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--evidence",type=Path,required=True); parser.add_argument("--lineage",type=Path,required=True); parser.add_argument("--output",type=Path,required=True); args=parser.parse_args()
    evidence=json.loads(args.evidence.read_text()); trace=generate(evidence,args.evidence)
    source_count=sum(len(rows) for rows in evidence["rules"].values()); qualified_count=sum(sum(row.get("result",{}).get("production_decision")=="QUALIFIED_VALUE" for row in rows) for rows in evidence["rules"].values())
    trace.update({"TRACE_VERSION":"c6-structured-v1","TRACE_GENERATOR_VERSION":"c6-trace-generator-v1","TRACE_GENERATOR_BLOB_OR_FILE_SHA256":digest(Path(__file__)),"SOURCE_C4_EVIDENCE_SHA256":digest(args.evidence),"SOURCE_RECORD_COUNT":source_count,"SOURCE_QUALIFIED_COUNT":qualified_count,"MANIFEST_LINEAGE_SHA256":digest(args.lineage),"AUDIT_COMPONENT_SHA256":component_hashes()})
    args.output.write_text(json.dumps(trace,indent=2,sort_keys=True),encoding="utf-8")
    print(json.dumps({"event":"c6_trace_generated","source_c4_evidence_sha256":trace["SOURCE_C4_EVIDENCE_SHA256"],"source_record_count":source_count,"source_qualified_count":qualified_count},sort_keys=True))
if __name__=="__main__": main()
