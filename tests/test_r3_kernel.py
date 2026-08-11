"""Focused R3 kernel tests for affine semantics and current-BZ consumers."""

from __future__ import annotations

import unittest

import numpy as np

from meep import mpb

from mephc.affine import AffineTransform2D
from mephc.band import Band
from mephc.bravais import BravaisLattice2D
from mephc.bz import BrillouinZone2D, first_brillouin_zone
from mephc.kspace import TriangularKSpace, generic_bz_path


class R3KernelTests(unittest.TestCase):
    def test_identity_angle_is_canonical_and_uniaxial_matrix(self):
        self.assertTrue(AffineTransform2D.uniaxial(1.0, 37.0).is_identity)
        transform = AffineTransform2D.uniaxial(1.2, 30.0)
        direction = np.array([np.cos(np.pi / 6), np.sin(np.pi / 6)])
        expected = np.eye(2) + 0.2 * np.outer(direction, direction)
        np.testing.assert_allclose(transform.matrix, expected)
        np.testing.assert_allclose(transform.compose(transform.inverse()).matrix, np.eye(2), atol=1e-12)

    def test_reference_family_does_not_authorize_c3_after_deformation(self):
        model = BravaisLattice2D.triangular().transformed(AffineTransform2D.uniaxial(1.15, 45.0))
        self.assertEqual(model.reference_family, "triangular")
        self.assertEqual(model.current_symmetry, "generic_affine")
        self.assertFalse(model.supports_legacy("c3"))
        self.assertFalse(model.supports_legacy("gkm"))
        with self.assertRaises(ValueError):
            TriangularKSpace(4, lattice_model=model).mini_space()
        self.assertEqual(generic_bz_path(model).labels[1][:2], "BZ")

    def test_bz_is_open_convex_origin_containing_and_area_matched(self):
        model = BravaisLattice2D.triangular().transformed(AffineTransform2D.uniaxial(1.2, 30.0))
        zone = first_brillouin_zone(model)
        vertices = zone.vertices
        self.assertFalse(np.allclose(vertices[0], vertices[-1]))
        self.assertAlmostEqual(zone.area, zone.reciprocal_cell_area, places=7)
        with self.assertRaises(ValueError):
            BrillouinZone2D(np.eye(2) * 0.1, np.eye(2), 1, 1e-10)

    def test_nonidentity_reciprocal_grid_uses_current_basis(self):
        model = BravaisLattice2D.triangular().transformed(AffineTransform2D.uniaxial(1.1, 0.0))
        points = np.asarray(TriangularKSpace(8, lattice_model=model).full_bz(), dtype=float)
        self.assertGreater(len(points), 0)
        self.assertTrue(np.max(np.abs(points[:, 0])) > 0.5)

    def test_nonidentity_band_berry_efs_smoke(self):
        model = BravaisLattice2D.triangular().transformed(AffineTransform2D.uniaxial(1.05, 30.0))
        band = Band(a=400, r1=0.2, r2=0.0, n_eff=2.0, h=1.0,
                    resolution=2, lattice_model=model)
        pattern = np.array([[0.0, 0.2], [-0.17, -0.1], [0.17, -0.1]])
        efs = band.compute_efs(pattern, [(0.0, 0.0)], num_bands=1)
        self.assertEqual(efs.freqs.shape, (1, 1))
        berry = band.compute_berry_grid(pattern, [(0.1, 0.1)], step=0.02, num_bands=1)
        self.assertEqual(np.asarray(berry["bcs"]).shape, (1, 1))


if __name__ == "__main__":
    unittest.main()
