import unittest
from boundary_gate import classify_boundary

class BoundaryGateTests(unittest.TestCase):
    def test_zero_measure_boundary_exception_is_explicit(self):
        records = [
            {"exact_boundary": True, "production_decision": "MASKED", "field_continuity": "zero_measure_exception"},
            {"exact_boundary": False, "production_decision": "QUALIFIED_VALUE", "field_continuity": "consistent"},
        ]
        self.assertEqual(classify_boundary(records), "SMOOTH_WITH_LOCAL_QUALIFICATION_EXCEPTIONS")
