"""Self-verifying C6 trace validator."""
from __future__ import annotations
import hashlib,math
from pathlib import Path
import reducer_c5 as prior
RULES=("coarse_centroid","fine_centroid","fine_three_point","refined_centroid")
def _digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def component_hashes():
    here=Path(__file__).parent
    return {"trace_generator_c6":_digest(here/"trace_generator_c6.py"),"trace_generator_base":_digest(here/"trace_generator.py"),"reducer_c6":_digest(here/"reducer_c6.py"),"sample_identity":_digest(here/"sample_identity.py")}
def validate_trace(trace,expected_area=1.0/math.sqrt(3.0)):
    prior.validate_trace(trace,expected_area)
    if trace.get("TRACE_VERSION")!="c6-structured-v1" or trace.get("trace_version")!="c4-structured-v1": raise ValueError("unrecognized C6 trace version")
    if trace.get("TRACE_GENERATOR_VERSION")!="c6-trace-generator-v1": raise ValueError("unrecognized C6 generator version")
    if trace.get("SOURCE_C4_EVIDENCE_SHA256")!=trace.get("source_raw_manifest_sha256"): raise ValueError("direct source evidence hash mismatch")
    rules=trace.get("rules",{})
    if tuple(sorted(rules))!=tuple(sorted(RULES)): raise ValueError("required exact-domain rule set mismatch")
    total=sum(int(rules[name]["total_record_count"]) for name in RULES); qualified=sum(int(rules[name]["qualified_count"]) for name in RULES)
    if int(trace.get("SOURCE_RECORD_COUNT",-1))!=total: raise ValueError("source record count closure failed")
    if int(trace.get("SOURCE_QUALIFIED_COUNT",-1))!=qualified: raise ValueError("source qualified count closure failed")
    for name in RULES:
        payload=rules[name]
        if not payload.get("exact_domain"): raise ValueError(f"not exact domain: {name}")
        if int(payload["qualified_count"])!=int(payload["total_record_count"]): raise ValueError(f"unqualified rule: {name}")
        if not math.isclose(float(payload["sum_signed_weights"]),expected_area,rel_tol=0,abs_tol=1e-12): raise ValueError(f"signed weight closure failed: {name}")
        for chunk in payload["chunks"]:
            if int(chunk["qualified_count"])!=int(chunk["input_record_count"]): raise ValueError(f"unqualified chunk: {name}")
            if not math.isfinite(float(chunk["signed_weight_sum"])): raise ValueError(f"nonfinite chunk weight: {name}")
            if "ordered_input_records_sha256" not in chunk: raise ValueError("missing exact-q chunk digest")
    if trace.get("AUDIT_COMPONENT_SHA256")!=component_hashes(): raise ValueError("repository component fingerprint mismatch")
    return {"TRACE_BINDING_VALIDATION":"FULLY_SELF_CONSISTENT_AND_REPOSITORY_VERIFIED","TRACE_SAMPLE_IDENTITY":"EXACT_AND_AUDITABLE"}
def reduce(trace,controls):
    validate_trace(trace)
    return prior.reduce(trace,controls)
