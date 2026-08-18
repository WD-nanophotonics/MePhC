import unittest
from unittest.mock import patch

import meep as mp
import numpy as np

from mephc.band import Band
from mephc.berry import BerryCurvatureCalculator
from mephc.bravais import BravaisLattice2D
from mephc.response import R6_AMPLITUDES, benchmark_field


def make_calculator(**kwargs):
    return BerryCurvatureCalculator(
        geometry=[],
        geometry_lattice=mp.Lattice(size=mp.Vector3(1, 1, 1)),
        resolution=2,
        num_bands=1,
        **kwargs,
    )


def synthetic_fields():
    rng = np.random.default_rng(66)
    e = rng.normal(size=(1, 2, 2, 3)) + 1j * rng.normal(size=(1, 2, 2, 3))
    h = rng.normal(size=(1, 2, 2, 3)) + 1j * rng.normal(size=(1, 2, 2, 3))
    eps = np.full((2, 2), 3.0)
    return e, h, eps


class BerryHSpaceR66HTests(unittest.TestCase):
    def test_default_and_explicit_legacy_formulation_match(self):
        default = make_calculator()
        explicit = make_calculator(overlap_formulation="energy_eh")
        e1, h1, eps = synthetic_fields()
        e2, h2, _ = synthetic_fields()
        self.assertEqual(default.overlap_formulation, "energy_eh")
        self.assertTrue(np.allclose(
            default.link_overlap(e1, h1, e2, h2, eps=eps),
            explicit.link_overlap(e1, h1, e2, h2, eps=eps),
        ))

    def test_mpb_h_matches_manual_h_link(self):
        calculator = make_calculator(overlap_formulation="mpb_h")
        _, h1, _ = synthetic_fields()
        _, h2, _ = synthetic_fields()
        actual = calculator._h_link_overlap(h1, h2)
        raw = np.sum(np.conj(h1) * h2, axis=(1, 2, 3))
        self.assertTrue(np.allclose(actual, raw / np.abs(raw)))

    def test_mpb_h_closed_flux_is_gauge_invariant(self):
        calculator = make_calculator(overlap_formulation="mpb_h")
        rng = np.random.default_rng(67)
        fields = [rng.normal(size=(1, 2, 2, 3)) + 1j * rng.normal(size=(1, 2, 2, 3)) for _ in range(4)]
        links = [calculator._h_link_overlap(fields[i], fields[(i + 1) % 4])[0] for i in range(4)]
        phases = np.exp(1j * rng.uniform(-np.pi, np.pi, size=4))
        gauged = [fields[i] * phases[i] for i in range(4)]
        gauged_links = [calculator._h_link_overlap(gauged[i], gauged[(i + 1) % 4])[0] for i in range(4)]
        self.assertAlmostEqual(float(np.angle(np.prod(links))), float(np.angle(np.prod(gauged_links))), places=12)

    def test_mpb_h_fails_closed_for_invalid_h_data(self):
        calculator = make_calculator(overlap_formulation="mpb_h")
        _, h, _ = synthetic_fields()
        with self.assertRaises(ValueError):
            calculator.normalize_h_fields(np.zeros((1, 2, 2, 2)))
        nonfinite = h.copy()
        nonfinite[0, 0, 0, 0] = np.nan
        with self.assertRaises(ValueError):
            calculator.normalize_h_fields(nonfinite)
        with self.assertRaises(FloatingPointError):
            calculator.normalize_h_fields(np.zeros_like(h))
        orthogonal_a = np.zeros_like(h)
        orthogonal_b = np.zeros_like(h)
        orthogonal_a[0, 0, 0, 0] = 1.0
        orthogonal_b[0, 0, 0, 1] = 1.0
        with self.assertRaises(FloatingPointError):
            calculator._h_link_overlap(orthogonal_a, orthogonal_b)

    def test_unknown_formulation_fails_before_solver(self):
        with patch("mephc.berry.mpb.ModeSolver") as mode_solver:
            with self.assertRaises(ValueError):
                make_calculator(overlap_formulation="MPB_H")
        mode_solver.assert_not_called()
        for value in (True, False, None, 1):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    make_calculator(overlap_formulation=value)

    def test_mpb_h_calculate_does_not_use_epsilon_or_e(self):
        calculator = make_calculator(overlap_formulation="mpb_h")
        _, h, _ = synthetic_fields()

        def fields(_point):
            calculator.eps = np.full((2, 2), np.nan)
            return np.full_like(h, np.nan), h.copy()

        with patch.object(calculator, "calculate_fields", side_effect=fields):
            value = calculator.calculate(np.zeros(2), step=0.01, band_index=0)
        self.assertTrue(np.isfinite(value))

    def test_factory_forwards_formulation_and_shared_context(self):
        band = Band(resolution=8)
        field = benchmark_field(BravaisLattice2D.square(), R6_AMPLITUDES[0])
        context = band._prepare_supercell_geometry([], field)
        with patch.object(band, "_prepare_supercell_geometry", return_value=context) as prepare:
            with patch("mephc.band.BerryCurvatureCalculator", return_value=object()) as factory:
                band.build_supercell_berry_calculator(
                    [], field, num_bands=1, overlap_formulation="mpb_h",
                    eigensolver_tolerance=1e-11, deterministic=True,
                )
        prepare.assert_called_once_with([], field)
        self.assertEqual(factory.call_args.kwargs["overlap_formulation"], "mpb_h")
        self.assertEqual(factory.call_args.kwargs["eigensolver_tolerance"], 1e-11)
        self.assertIs(factory.call_args.kwargs["deterministic"], True)
        self.assertIs(factory.call_args.kwargs["geometry"], context.geometry)
        self.assertIs(factory.call_args.kwargs["geometry_lattice"], context.geometry_lattice)

    def test_dynamic_shape_and_primitive_guard_remain_intact(self):
        calculator = make_calculator(overlap_formulation="mpb_h")
        self.assertEqual(calculator._reshape_vector_field(np.zeros(12)).shape, (2, 2, 3))
        self.assertEqual(calculator._reshape_epsilon(np.ones(4)).shape, (2, 2))
        band = Band(deformation_field=benchmark_field(BravaisLattice2D.square(), R6_AMPLITUDES[0]))
        with self.assertRaises(Exception):
            band.berry_calculator(num_bands=1)


if __name__ == "__main__":
    unittest.main()
