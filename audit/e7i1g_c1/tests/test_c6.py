import copy
import json
import math
import unittest
from pathlib import Path

from identity_cache import build_cache, lookup
from reducer_c7 import validate_trace
from sample_identity import QProvenanceMismatch, display_q, exact_q, identity_from_result
from trace_generator import _chunk

def result(q=(1.0,2.0)):
    return {"target_q":list(q),"valley":"K","radii":[0.15,0.25],"resolution":64,"h":0.001,"representation":"mpb_live_energy_eh_v1","plaquette":"CENTERED_CCW","geometry":"d0500-minus-sealed-honeycomb","selected_bands_one_based":[1,2],"rank":1,"omega_bands_q":[1.0,-1.0],"omega_anti_q":1.0,"omega_common_q":0.0,"production_decision":"QUALIFIED_VALUE"}

class C6Tests(unittest.TestCase):
    def test_exact_q_is_separate_from_rounded_display(self):
        q1=(1.0,2.0); q2=(float.fromhex("0x1.0000000000001p+0"),2.0)
        self.assertEqual(display_q(q1),display_q(q2))
        self.assertNotEqual(exact_q(q1),exact_q(q2))
    def test_result_q_mismatch_fails_closed(self):
        with self.assertRaises(QProvenanceMismatch):
            identity_from_result(result((1.0,2.0)),requested_q=(1.0,2.0000000000000004))
    def test_exact_cache_does_not_use_display_label(self):
        q1=(1.0,2.0); q2=(float.fromhex("0x1.0000000000001p+0"),2.0)
        cache=build_cache([("one",q1,result(q1))])
        self.assertIsNone(lookup(cache,q2))
    def test_exact_q_changes_chunk_digest(self):
        base={"triangle_area":1.0,"sample_weight":1.0,"triangle_index":0,"sample_index":0}
        a=dict(base,qx=1.0,qy=2.0,result=result((1.0,2.0)))
        b=dict(base,qx=float.fromhex("0x1.0000000000001p+0"),qy=2.0,result=result((float.fromhex("0x1.0000000000001p+0"),2.0)))
        self.assertNotEqual(_chunk("r",0,[a])["ordered_input_records_sha256"],_chunk("r",0,[b])["ordered_input_records_sha256"])
    def test_committed_trace_is_repository_self_verifying(self):
        trace=json.loads(Path(__file__).parents[1].joinpath("fixtures/c4_reduction_trace.json").read_text())
        report=validate_trace(trace)
        self.assertEqual(report["TRACE_BINDING_VALIDATION"],"FULLY_SELF_CONSISTENT_AND_REPOSITORY_VERIFIED")
        self.assertEqual(report["TRACE_COORDINATE_PROVENANCE"],"NOMINAL_AND_EVALUATED_EXPLICIT")
    def test_trace_source_count_closes(self):
        trace=json.loads(Path(__file__).parents[1].joinpath("fixtures/c4_reduction_trace.json").read_text())
        trace["SOURCE_RECORD_COUNT"]-=1
        with self.assertRaises(ValueError): validate_trace(trace)
    def test_component_fingerprint_mismatch_fails(self):
        trace=json.loads(Path(__file__).parents[1].joinpath("fixtures/c4_reduction_trace.json").read_text())
        trace["AUDIT_COMPONENT_SHA256"]["sample_identity"]="0"*64
        with self.assertRaises(ValueError): validate_trace(trace)

if __name__=="__main__":
    unittest.main()
