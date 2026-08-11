"""Focused R2 tests for the canonical affine/lattice/BZ kernel."""

from __future__ import annotations

import unittest

import numpy as np

from mephc.affine import AffineTransform2D
from mephc.bravais import BravaisLattice2D
from mephc.bz import first_brillouin_zone
from mephc.band import Band
from mephc.kspace import TriangularKSpace, triangular_gkm_path
from mephc.lattice import maketriangularlattice


class R2KernelTests(unittest.TestCase):
    def test_transform_validation_application_composition_and_metadata(self):
        identity = AffineTransform2D.identity()
        self.assertTrue(np.allclose(identity.apply([[1.0, 2.0]]), [[1.0, 2.0]]))
        self.assertEqual(identity.metadata()["type"], "AffineTransform2D")
        self.assertFalse(identity.matrix.flags.writeable)
        with self.assertRaises(ValueError):
            AffineTransform2D([[1, 0], [0, 0]])
        with self.assertRaises(ValueError):
            identity.apply([1, 2, 3])
        with self.assertRaises(ValueError):
            AffineTransform2D.uniaxial(0)
        left = AffineTransform2D([[1, 1], [0, 1]])
        right = AffineTransform2D([[1, 0], [2, 1]])
        point = np.array([0.2, 0.7])
        self.assertFalse(np.allclose(left.compose(right).apply(point), right.compose(left).apply(point)))
        self.assertTrue(np.allclose(left.inverse().apply(left.apply(point)), point))

    def test_direct_reciprocal_duality_and_affine_contragredient_law(self):
        lattice = BravaisLattice2D.triangular()
        self.assertTrue(np.allclose(lattice.direct_basis.T @ lattice.reciprocal_basis, np.eye(2)))
        transform = AffineTransform2D([[1.2, 0.25], [0.0, 0.8]])
        transformed = lattice.transformed(transform)
        expected_reciprocal = np.linalg.inv(transform.matrix).T @ lattice.reciprocal_basis
        self.assertTrue(np.allclose(transformed.reciprocal_basis, expected_reciprocal))

    def test_coordinate_round_trips_and_named_basis_parity(self):
        for lattice in (BravaisLattice2D.triangular(), BravaisLattice2D.square()):
            fractional = np.array([[0.1, 0.2], [-0.3, 0.7]])
            cartesian = lattice.fractional_to_cartesian(fractional)
            self.assertTrue(np.allclose(lattice.cartesian_to_fractional(cartesian), fractional))
            reciprocal = lattice.reciprocal_to_cartesian(fractional)
            self.assertTrue(np.allclose(lattice.cartesian_to_reciprocal(reciprocal), fractional))

    def test_generic_bz_identity_and_nonidentity_families(self):
        triangular = first_brillouin_zone(BravaisLattice2D.triangular())
        expected = np.array(
            [[2 / 3, 0], [1 / 3, np.sqrt(3) / 3], [-1 / 3, np.sqrt(3) / 3],
             [-2 / 3, 0], [-1 / 3, -np.sqrt(3) / 3], [1 / 3, -np.sqrt(3) / 3]]
        )
        self.assertTrue(np.allclose(triangular.vertices, expected, atol=1e-10))
        self.assertTrue(np.isclose(triangular.area, triangular.reciprocal_cell_area))
        square = first_brillouin_zone(BravaisLattice2D.square())
        self.assertEqual(square.vertices.shape, (4, 2))
        transforms = [
            AffineTransform2D([[1.8, 0], [0, 0.7]]),
            AffineTransform2D.uniaxial(1.3, 27),
            AffineTransform2D([[1.0, 0.35], [0.15, 1.0]]),
            AffineTransform2D([[1.0, 0.2], [0.0, 0.12]]),
        ]
        for transform in transforms:
            zone = first_brillouin_zone(BravaisLattice2D.triangular().transformed(transform))
            self.assertTrue(np.all(np.isfinite(zone.vertices)))
            self.assertGreater(zone.area, 0)
            self.assertTrue(np.isclose(zone.area, zone.reciprocal_cell_area, rtol=1e-8, atol=1e-10))

    def test_solver_and_real_space_adapters_share_identity_basis(self):
        lattice = BravaisLattice2D.triangular()
        band = Band(a=400, r1=100, n_eff=2.7, h=1, resolution=1, lattice_model=lattice)
        solver_basis = np.array(
            [[band.geo_latt.basis1.x, band.geo_latt.basis2.x],
             [band.geo_latt.basis1.y, band.geo_latt.basis2.y]]
        )
        self.assertTrue(np.allclose(solver_basis, lattice.direct_basis))
        sites = maketriangularlattice(period=1, size=4)
        rows = np.unique(np.round(sites[:, 1], 12))
        row0 = sites[np.isclose(sites[:, 1], rows[0]), 0]
        row1 = sites[np.isclose(sites[:, 1], rows[1]), 0]
        self.assertTrue(np.isclose(np.mean(row1) - np.mean(row0), 0.5))

    def test_legacy_path_remains_named_and_stable(self):
        self.assertEqual(triangular_gkm_path().labels, ("Gamma", "K", "M", "Gamma"))
        self.assertTrue(np.allclose(triangular_gkm_path().points[1], (2 / 3, 0)))


if __name__ == "__main__":
    unittest.main()
