"""Independent executable coverage for the R5 deformation foundation."""

from __future__ import annotations

import unittest

import numpy as np

from mephc.affine import AffineTransform2D
from mephc.bravais import BravaisLattice2D
from mephc.deformation import (
    AnalyticDeformationField,
    DeformationCapability,
    PeriodicityError,
    canonicalize_field,
    periodic_supercell_field,
    sampled_field,
    validate_jacobian,
)
from mephc.r5 import primitive_guard, record_identity, supercell_metadata


class R5KernelTests(unittest.TestCase):
    def test_zero_and_constant_affine_canonicalization(self):
        zero = canonicalize_field(None)
        self.assertEqual(zero.capability, DeformationCapability.GLOBAL_AFFINE_PERIODIC)
        points = np.array([[0.2, -0.1], [1.0, 0.5]])
        np.testing.assert_allclose(zero.map_points(points), points)
        for factor, angle in ((1.0, 0.0), (1.1, 0.0), (0.9, 30.0), (1.08, 17.0)):
            transform = AffineTransform2D.uniaxial(factor, angle)
            field = canonicalize_field(transform)
            np.testing.assert_allclose(field.map_points(points), transform.apply(points), atol=1e-12)
            if transform.is_identity:
                self.assertEqual(field.metadata()["kind"], "zero")

    def test_analytic_gradient_jacobian_and_sign_reversal(self):
        def value(points):
            return np.column_stack((0.1 * np.sin(points[:, 0]), 0.05 * np.cos(points[:, 1])))

        def gradient(points):
            return np.stack(
                (
                    np.stack((0.1 * np.cos(points[:, 0]), np.zeros(len(points))), axis=1),
                    np.stack((np.zeros(len(points)), -0.05 * np.sin(points[:, 1])), axis=1),
                ),
                axis=1,
            )

        field = AnalyticDeformationField(value, gradient=gradient, stable_id="smooth-v1")
        probe = np.array([[0.2, 0.3]])
        np.testing.assert_allclose(field.gradient(probe)[0], gradient(probe)[0])
        validate_jacobian(field, [[0.2, 0.3], [0.4, 0.5]])
        reverse = AnalyticDeformationField(lambda p: -value(p), gradient=lambda p: -gradient(p), stable_id="smooth-v1-reverse")
        np.testing.assert_allclose(reverse.displacement(probe), -field.displacement(probe))

    def test_sampled_interpolation_is_deterministic(self):
        x = np.linspace(0.0, 2.0, 5)
        y = np.linspace(0.0, 2.0, 5)
        xx, yy = np.meshgrid(x, y)
        samples = np.stack((0.1 * np.sin(np.pi * xx), 0.05 * np.cos(np.pi * yy)), axis=2)
        one = sampled_field((0.0, 0.0), (0.5, 0.5), samples)
        two = sampled_field((0.0, 0.0), (0.5, 0.5), samples.copy())
        np.testing.assert_allclose(one.displacement([[0.25, 0.75]]), two.displacement([[0.25, 0.75]]))
        self.assertEqual(one.fingerprint(), two.fingerprint())

    def test_supercell_boundary_pass_and_fail(self):
        square = BravaisLattice2D.square()
        periodic = AnalyticDeformationField(
            lambda p: np.column_stack((0.1 * np.sin(2 * np.pi * p[:, 0] / 2.0), np.zeros(len(p)))),
            stable_id="sinusoid-period-2",
        )
        field = periodic_supercell_field(periodic, square, (2, 1))
        self.assertTrue(field.verified)
        self.assertEqual(supercell_metadata(field)["semantic_label"], "supercell")
        with self.assertRaises(PeriodicityError):
            periodic_supercell_field(
                AnalyticDeformationField(lambda p: np.column_stack((0.01 * p[:, 0], np.zeros(len(p)))), stable_id="nonperiodic"),
                square,
                (2, 1),
            )

    def test_guards_and_record_identity(self):
        local = AnalyticDeformationField(lambda p: np.zeros_like(p), stable_id=None)
        with self.assertRaisesRegex(RuntimeError, "E_R5_PRIMITIVE_SEMANTICS"):
            primitive_guard(local, "primitive Band")
        with self.assertRaisesRegex(ValueError, "E_R5_UNSTABLE_CALLABLE"):
            record_identity(local, reference_lattice=BravaisLattice2D.square())
        identity = record_identity(canonicalize_field(None), reference_lattice=BravaisLattice2D.square())
        self.assertTrue(identity["legacy_identity_collapse"])


if __name__ == "__main__":
    unittest.main()
