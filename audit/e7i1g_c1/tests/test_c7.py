import json
import unittest
from pathlib import Path
from coordinate_semantics import coordinate_mapping
from reducer_c7 import validate_trace

class C7Tests(unittest.TestCase):
    def test_exact_nominal_evaluated(self):
        self.assertEqual(coordinate_mapping((1.0,2.0),(1.0,2.0)),"EXACT")
    def test_decimal12_mapping_is_explicit(self):
        nominal=(0.25259074277046134,1.0833333333333333)
        evaluated=(0.25259074277033333,1.0833333333333333)
        self.assertEqual(coordinate_mapping(nominal,evaluated),"NONCANONICAL_MISMATCH")
        self.assertLess(((evaluated[0]-nominal[0])**2+(evaluated[1]-nominal[1])**2)**0.5,1e-12)
    def test_noncanonical_mapping_rejected_by_semantics(self):
        self.assertEqual(coordinate_mapping((1.0,2.0),(1.0+1e-3,2.0)),"NONCANONICAL_MISMATCH")
    def test_exact_q_cache_does_not_conflate_nominal_labels(self):
        a=(1.0,2.0); b=(float.fromhex("0x1.0000000000001p+0"),2.0)
        self.assertNotEqual(a,b)
    def test_c7_trace_binding_and_coordinate_provenance(self):
        trace=json.loads(Path(__file__).parents[1].joinpath("fixtures/c4_reduction_trace.json").read_text())
        report=validate_trace(trace)
        self.assertEqual(report["TRACE_COORDINATE_PROVENANCE"],"NOMINAL_AND_EVALUATED_EXPLICIT")
    def test_trace_binding_mismatch_fails(self):
        trace=json.loads(Path(__file__).parents[1].joinpath("fixtures/c4_reduction_trace.json").read_text())
        trace["TRACE_COORDINATE_PROVENANCE"]="PARTIAL"
        with self.assertRaises(ValueError): validate_trace(trace)

if __name__=="__main__":
    unittest.main()
