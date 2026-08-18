import unittest

import meep as mp
import numpy as np

from mephc.berry import BerryCurvatureCalculator


def calculator(size=(1, 1), resolution=4):
    return BerryCurvatureCalculator(
        geometry=[],
        geometry_lattice=mp.Lattice(size=mp.Vector3(size[0], size[1], 1)),
        resolution=resolution,
        num_bands=2,
        overlap_tol=1e-12,
    )


class BerryFieldShapeR66CTests(unittest.TestCase):
    def test_primitive_flat_fields_keep_resolution_shape(self):
        calc = calculator()
        vector = calc._reshape_vector_field(np.zeros(4 * 4 * 3))
        epsilon = calc._reshape_epsilon(np.ones(4 * 4))
        self.assertEqual(vector.shape, (4, 4, 3))
        self.assertEqual(epsilon.shape, (4, 4))

    def test_two_by_two_supercell_flat_fields_are_eight_by_eight(self):
        calc = calculator(size=(2, 2))
        vector = calc._reshape_vector_field(np.zeros(8 * 8 * 3))
        epsilon = calc._reshape_epsilon(np.ones(8 * 8))
        self.assertEqual(vector.shape, (8, 8, 3))
        self.assertEqual(epsilon.shape, (8, 8))

    def test_two_by_three_supercell_is_eight_by_twelve(self):
        calc = calculator(size=(2, 3))
        vector = calc._reshape_vector_field(np.zeros(8 * 12 * 3))
        epsilon = calc._reshape_epsilon(np.ones(8 * 12))
        self.assertEqual(vector.shape, (8, 12, 3))
        self.assertEqual(epsilon.shape, (8, 12))

    def test_structured_supercell_layouts_are_accepted(self):
        calc = calculator(size=(2, 3))
        vector = np.zeros((8, 12, 1, 3))
        epsilon = np.ones((8, 12, 1))
        self.assertEqual(calc._reshape_vector_field(vector).shape, (8, 12, 3))
        self.assertEqual(calc._reshape_vector_field(vector[:, :, 0, :]).shape, (8, 12, 3))
        self.assertEqual(calc._reshape_epsilon(epsilon).shape, (8, 12))
        self.assertEqual(calc._reshape_epsilon(epsilon[:, :, 0]).shape, (8, 12))

    def test_normalization_uses_dynamic_spatial_shape(self):
        calc = calculator(size=(2, 3))
        e_fields = np.ones((2, 8, 12, 3), dtype=complex)
        h_fields = np.full((2, 8, 12, 3), 0.5, dtype=complex)
        epsilon = np.ones((8, 12), dtype=float)
        normalized_e, normalized_h = calc.normalize_fields(e_fields, h_fields, eps=epsilon)
        self.assertEqual(normalized_e.shape, e_fields.shape)
        self.assertEqual(normalized_h.shape, h_fields.shape)
        self.assertTrue(np.all(np.isfinite(normalized_e)))
        self.assertTrue(np.all(np.isfinite(normalized_h)))

    def test_link_overlap_uses_dynamic_spatial_shape(self):
        calc = calculator(size=(2, 3))
        e_fields = np.ones((1, 8, 12, 3), dtype=complex)
        h_fields = np.ones((1, 8, 12, 3), dtype=complex)
        links = calc.link_overlap(e_fields, h_fields, e_fields, h_fields, eps=np.ones((8, 12)))
        self.assertEqual(links.shape, (1,))
        self.assertTrue(np.all(np.isfinite(links)))
        np.testing.assert_allclose(np.abs(links), [1.0])

    def test_incompatible_shapes_fail_closed(self):
        calc = calculator(size=(2, 2))
        with self.assertRaisesRegex(ValueError, r"expected spatial shape \(8, 8\)"):
            calc._reshape_vector_field(np.zeros((4, 4, 3)))
        with self.assertRaisesRegex(ValueError, r"expected spatial shape \(8, 8\)"):
            calc._reshape_epsilon(np.ones((8, 7)))
        e_fields = np.ones((2, 8, 8, 3))
        h_fields = np.ones((2, 8, 7, 3))
        with self.assertRaisesRegex(ValueError, r"matching E/H shapes"):
            calc.normalize_fields(e_fields, h_fields, eps=np.ones((8, 8)))
        with self.assertRaisesRegex(ValueError, r"non-finite"):
            calc._reshape_epsilon(np.full((8, 8), np.nan))


if __name__ == "__main__":
    unittest.main()
