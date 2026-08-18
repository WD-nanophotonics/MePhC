import unittest
from unittest.mock import patch

import meep as mp
import numpy as np

from mephc.band import Band
from mephc.berry import BerryCurvatureCalculator
from mephc.bravais import BravaisLattice2D
from mephc.deformation import ZeroDeformationField
from mephc.response import R6_AMPLITUDES, benchmark_field


def make_field():
    return benchmark_field(BravaisLattice2D.square(), R6_AMPLITUDES[0])


def make_calculator(**kwargs):
    return BerryCurvatureCalculator(
        geometry=[],
        geometry_lattice=mp.Lattice(size=mp.Vector3(1, 1, 1)),
        resolution=4,
        num_bands=2,
        **kwargs,
    )


class BerryEigensolverControlsR66FTests(unittest.TestCase):
    def test_defaults_forward_current_mpb_behavior(self):
        calculator = make_calculator()
        with patch("mephc.berry.mpb.ModeSolver", return_value=object()) as mode_solver:
            calculator.build_solver(mp.Vector3())
        self.assertEqual(calculator.eigensolver_tolerance, 1e-7)
        self.assertIs(calculator.deterministic, False)
        self.assertEqual(mode_solver.call_args.kwargs["tolerance"], 1e-7)
        self.assertIs(mode_solver.call_args.kwargs["deterministic"], False)

    def test_explicit_controls_forward_exactly(self):
        calculator = make_calculator(eigensolver_tolerance=1e-10, deterministic=True)
        with patch("mephc.berry.mpb.ModeSolver", return_value=object()) as mode_solver:
            calculator.build_solver(mp.Vector3())
        self.assertEqual(calculator.eigensolver_tolerance, 1e-10)
        self.assertIs(calculator.deterministic, True)
        self.assertEqual(mode_solver.call_args.kwargs["tolerance"], 1e-10)
        self.assertIs(mode_solver.call_args.kwargs["deterministic"], True)

    def test_invalid_tolerance_fails_before_solver_construction(self):
        for value in (0, -1, float("nan"), float("inf"), True, "1e-7", None):
            with self.subTest(value=value):
                with patch("mephc.berry.mpb.ModeSolver") as mode_solver:
                    with self.assertRaises(ValueError):
                        make_calculator(eigensolver_tolerance=value)
                mode_solver.assert_not_called()

    def test_non_bool_deterministic_fails_before_solver_construction(self):
        for value in (0, 1, "true", np.bool_(True), None):
            with self.subTest(value=value):
                with patch("mephc.berry.mpb.ModeSolver") as mode_solver:
                    with self.assertRaises(ValueError):
                        make_calculator(deterministic=value)
                mode_solver.assert_not_called()

    def test_supercell_factory_forwards_controls_and_shared_context(self):
        band = Band(resolution=8)
        field = make_field()
        context = band._prepare_supercell_geometry([], field)
        with patch.object(band, "_prepare_supercell_geometry", return_value=context) as prepare:
            with patch("mephc.band.BerryCurvatureCalculator", return_value=object()) as factory:
                band.build_supercell_berry_calculator(
                    [], field, num_bands=2, eigensolver_tolerance=1e-11, deterministic=True
                )
        prepare.assert_called_once_with([], field)
        self.assertIs(factory.call_args.kwargs["geometry"], context.geometry)
        self.assertIs(factory.call_args.kwargs["geometry_lattice"], context.geometry_lattice)
        self.assertEqual(factory.call_args.kwargs["eigensolver_tolerance"], 1e-11)
        self.assertIs(factory.call_args.kwargs["deterministic"], True)

    def test_factory_defaults_are_explicit_without_changing_geometry_authority(self):
        band = Band(resolution=8)
        field = make_field()
        context = band._prepare_supercell_geometry([], field)
        with patch.object(band, "_prepare_supercell_geometry", return_value=context):
            with patch("mephc.band.BerryCurvatureCalculator", return_value=object()) as factory:
                band.build_supercell_berry_calculator([], field, num_bands=2)
        self.assertEqual(factory.call_args.kwargs["eigensolver_tolerance"], 1e-7)
        self.assertIs(factory.call_args.kwargs["deterministic"], False)

    def test_primitive_guard_remains_intact(self):
        band = Band(deformation_field=make_field())
        with self.assertRaises(Exception):
            band.berry_calculator(num_bands=1)
        with self.assertRaises(Exception):
            band.compute_berry_grid([], np.zeros((1, 2)), step=0.01, num_bands=1)

    def test_r66c_shape_api_remains_available(self):
        calculator = make_calculator()
        vector = calculator._reshape_vector_field(np.zeros(4 * 4 * 3))
        epsilon = calculator._reshape_epsilon(np.ones(4 * 4))
        self.assertEqual(vector.shape, (4, 4, 3))
        self.assertEqual(epsilon.shape, (4, 4))


if __name__ == "__main__":
    unittest.main()
