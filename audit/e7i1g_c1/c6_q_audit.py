"""C6 exact-q, three-way provenance, and rounded-key collision audit."""
from __future__ import annotations
import argparse, hashlib, json
from collections import defaultdict
from pathlib import Path
from execution_plan import requested_records
from sample_identity import display_q, exact_q

RULES=("coarse_centroid","fine_centroid","fine_three_point","refined_centroid")

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":")).encode()).hexdigest()

def evidence_index(evidence):
    return {(rule,row["triangle_index"],row["sample_index"]):row for rule,rows in evidence["rules"].items() for row in rows}

def manifest_rows(path,key):
    data=json.loads(Path(path).read_text()); rows=[]
    for row in data.get(key,[]):
        result=row.get("result"); q=row.get("q",[row.get("qx"),row.get("qy")])
        if result is not None and q[0] is not None and q[1] is not None:
            rows.append({"source":key,"manifest_q":q,"result":result,"result_digest":digest(result)})
    return rows

def audit(fixed_manifest,legacy_manifest,evidence_path):
    evidence=json.loads(Path(evidence_path).read_text())
    current=evidence_index(evidence)
    requested=requested_records()
    sources=manifest_rows(fixed_manifest,"samples")+manifest_rows(legacy_manifest,"tasks")
    by_display=defaultdict(list)
    for row in sources: by_display[display_q(row["manifest_q"])].append(row)
    total=len(requested); request_result_exact=0; request_result_mismatch=0
    reused_match=0; reused_mismatch=0; fresh_match=0; fresh_mismatch=0
    exact_qs=set(); mismatched_qs=set(); reused_mismatched_qs=set(); rounded=defaultdict(set); examples=[]
    for key,record in requested.items():
        row=current[(record["rule"],record["triangle_index"],record["sample_index"])]
        req_q=(float(record["qx"]),float(record["qy"])); req_exact=exact_q(req_q)
        exact_qs.add(req_exact); rounded[display_q(req_q)].add(req_exact)
        result=row.get("result") or {}; result_q=result.get("target_q",result.get("q"))
        result_matches=result_q is not None and exact_q(result_q)==req_exact
        if result_matches: request_result_exact+=1
        else:
            request_result_mismatch+=1
            mismatched_qs.add(req_exact)
            if len(examples)<20: examples.append({"rule":record["rule"],"sample_index":record["sample_index"],"requested_q":req_exact,"result_q":None if result_q is None else exact_q(result_q)})
        classification=row.get("source_classification")
        candidates=by_display.get(display_q(req_q),[])
        current_digest=digest(result) if result else None
        matching=[source for source in candidates if source["result_digest"]==current_digest]
        if classification=="EXACT_IDENTITY_REUSE":
            triad=any(exact_q(source["manifest_q"])==req_exact and exact_q(source["result"].get("target_q",source["result"].get("q")))==req_exact for source in matching)
            if triad: reused_match+=1
            else:
                reused_mismatch+=1
                reused_mismatched_qs.add(req_exact)
        elif classification=="FRESH_C4":
            if result_matches: fresh_match+=1
            else: fresh_mismatch+=1
    collision_groups=[(label,values) for label,values in rounded.items() if len(values)>1]
    mismatch_kind="ALL_RECORDS_EXACT" if request_result_mismatch==0 and reused_mismatch==0 else ("WIDESPREAD_MISMATCH" if request_result_mismatch>32 or reused_mismatch>32 else "MISMATCHES_FOUND_AND_LOCALIZED")
    binding="REQUEST_MANIFEST_RESULT_EXACT" if request_result_mismatch==0 and reused_mismatch==0 else ("REQUEST_RESULT_EXACT_MANIFEST_LEGACY_EQUIVALENT" if request_result_exact==total and reused_mismatch>0 else "MISMATCH_FOUND")
    return {
        "EXACT_Q_IDENTITY":"IEEE_EXACT_AND_SEPARATE_FROM_DISPLAY_KEY",
        "Q_PROVENANCE_BINDING":binding,
        "C4_Q_PROVENANCE_AUDIT":mismatch_kind,
        "TOTAL_C4_RECORDS":total,
        "REQUEST_RESULT_EXACT_MATCH_COUNT":request_result_exact,
        "REQUEST_RESULT_MISMATCH_COUNT":request_result_mismatch,
        "REUSED_REQUEST_MANIFEST_RESULT_MATCH_COUNT":reused_match,
        "REUSED_Q_MISMATCH_COUNT":reused_mismatch,
        "FRESH_C4_Q_MATCH_COUNT":fresh_match,
        "FRESH_C4_Q_MISMATCH_COUNT":fresh_mismatch,
        "MISMATCHED_UNIQUE_Q_COUNT":len(mismatched_qs),
        "REUSED_MISMATCHED_UNIQUE_Q_COUNT":len(reused_mismatched_qs),
        "UNIQUE_EXACT_Q_COUNT":len(exact_qs),
        "UNIQUE_OLD_ROUNDED_Q_COUNT":len(rounded),
        "ROUNDED_KEY_COLLISION_GROUPS":len(collision_groups),
        "ROUNDED_KEY_COLLIDED_RECORDS":sum(len(values) for _,values in collision_groups),
        "OLD_ROUNDED_Q_COLLISION_EFFECT":"ZERO_COLLISIONS" if not collision_groups else "PHYSICAL_REUSE_CONTAMINATION_FOUND",
        "CACHE_Q_IDENTITY":"EXACT_PHYSICAL_Q",
        "C4_CACHE_EFFECT":"NO_PHYSICAL_CONTAMINATION" if request_result_mismatch==0 else "CONTAMINATION_FOUND_NOT_REPAIRED",
        "C6_MPB_REPAIR":"NOT_REQUIRED" if request_result_mismatch==0 and reused_mismatch==0 else ("MORE_THAN_32_POINTS_REQUIRES_NEW_AUTHORIZATION" if len({item["requested_q"] for item in examples})>32 or request_result_mismatch>32 else "BOUNDED_REPAIR_REQUIRED"),
        "examples":examples,
        "detail_digest":digest({"examples":examples,"counts":[request_result_exact,request_result_mismatch,reused_match,reused_mismatch,fresh_match,fresh_mismatch]}),
    }

def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--fixed-manifest",type=Path,required=True); parser.add_argument("--legacy-manifest",type=Path,required=True); parser.add_argument("--evidence",type=Path,required=True); parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args(); result=audit(args.fixed_manifest,args.legacy_manifest,args.evidence); args.output.write_text(json.dumps(result,indent=2,sort_keys=True),encoding="utf-8"); print(json.dumps(result,sort_keys=True))
if __name__=="__main__": main()
