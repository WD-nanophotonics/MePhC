import unittest

import numpy as np

from mephc.bravais import BravaisLattice2D
from mephc.bz import first_brillouin_zone, tracked_landmark


class R31KernelTests(unittest.TestCase):
    def test_transform_cartesian_uses_column_vector_convention(self):
        lattice = BravaisLattice2D.triangular()
        transformed = lattice.transformed(
            __import__("mephc.affine", fromlist=["AffineTransform2D"])
            .AffineTransform2D.uniaxial(1.1, 0.0)
        )
        point = np.array([0.5, 0.25])
        np.testing.assert_allclose(
            transformed.transform_cartesian(point),
            transformed.deformation_matrix @ point,
        )

    def test_tracked_landmark_identity_preserves_legacy_k(self):
        lattice = BravaisLattice2D.triangular()
        result = tracked_landmark(lattice)
        self.assertEqual(result["landmark_kind"], "legacy_K")
        self.assertEqual(result["display_label"], "K")
        np.testing.assert_allclose(result["cartesian"], (2.0 / 3.0, 0.0), atol=1e-12)

    def test_tracked_landmark_is_current_bz_vertex_and_deterministic(self):
        for factor, angle in ((1.1, 0.0), (0.9, 30.0), (1.08, 17.0)):
            lattice = BravaisLattice2D.triangular().transformed(
                __import__("mephc.affine", fromlist=["AffineTransform2D"])
                .AffineTransform2D.uniaxial(factor, angle)
            )
            first = tracked_landmark(lattice)
            second = tracked_landmark(lattice)
            self.assertEqual(first["landmark_kind"], "tracked_K1")
            np.testing.assert_allclose(first["cartesian"], first["selected_vertex"])
            np.testing.assert_allclose(first["cartesian"], second["cartesian"])
            bz = first_brillouin_zone(lattice)
            self.assertTrue(any(np.allclose(first["cartesian"], vertex) for vertex in bz.vertices))
            predictor = np.linalg.inv(lattice.deformation_matrix).T @ np.array([2.0 / 3.0, 0.0])
            distances = np.linalg.norm(bz.vertices - predictor, axis=1)
            self.assertEqual(first["selected_vertex_index"], int(np.argmin(distances)))

    def test_coordinate_round_trip(self):
        lattice = BravaisLattice2D.triangular().transformed(
            __import__("mephc.affine", fromlist=["AffineTransform2D"])
            .AffineTransform2D.uniaxial(1.08, 17.0)
        )
        point = tracked_landmark(lattice)["cartesian"]
        fractional = lattice.cartesian_to_reciprocal(point)
        np.testing.assert_allclose(lattice.reciprocal_to_cartesian(fractional), point)


if __name__ == "__main__":
    unittest.main()
