"""R7.1 geometry equivalence tests."""
from __future__ import annotations

import unittest

import numpy as np

from mephc.geometry_equivalence import match_geometry


class GeometryEquivalenceTests(unittest.TestCase):
    def setUp(self):
        self.square = np.asarray([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]])
        self.triangle = np.asarray([[2.0, 0.0], [2.5, 0.5], [2.0, 1.0]])

    def test_polygon_and_vertex_reordering_is_absolute_equivalence(self):
        candidate = [self.triangle[[2, 1, 0]], self.square[[2, 3, 0, 1]]]
        result = match_geometry([self.square, self.triangle], candidate)
        self.assertTrue(result.equivalent)
        self.assertEqual(result.reason, "EQUIVALENT_ABSOLUTE")
        self.assertEqual(result.assignment, (1, 0))

    def test_translation_is_shape_equivalent_but_not_absolute(self):
        translated = [self.square + [0.25, 0.0], self.triangle + [0.25, 0.0]]
        absolute = match_geometry([self.square, self.triangle], translated)
        shape = match_geometry([self.square, self.triangle], translated, shape_only=True)
        self.assertFalse(absolute.equivalent)
        self.assertEqual(absolute.reason, "polygon_position_difference")
        self.assertTrue(shape.equivalent)

    def test_shape_change_is_not_equivalent(self):
        changed = self.square.copy()
        changed[2, 1] += 0.01
        result = match_geometry([self.square], [changed], tolerance=1e-6, shape_only=True)
        self.assertFalse(result.equivalent)
        self.assertEqual(result.reason, "polygon_shape_difference")


if __name__ == "__main__":
    unittest.main()
