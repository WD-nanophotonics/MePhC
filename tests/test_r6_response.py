import numpy as np
import unittest

from mephc.bravais import BravaisLattice2D
from mephc.deformation import AnalyticDeformationField
from mephc.response import R6_AMPLITUDES, benchmark_field, q_points, sign_reversal, verify_q_points


def test_r6_benchmark_field_is_verified_and_periodic():
    lattice = BravaisLattice2D.square()
    fields = [benchmark_field(lattice, amplitude) for amplitude in R6_AMPLITUDES]
    assert all(field.verified for field in fields)
    assert np.allclose(fields[1].displacement([[.31, .42]]) + fields[2].displacement([[.31, .42]]), 0.0, atol=1e-12)
    assert np.allclose(fields[0].displacement([[.31, .42]]), 0.0)


def test_r6_q_points_are_generic_and_inside_supercell_bz():
    points = q_points()
    assert tuple(point.point_id for point in points) == ("q0", "q1", "q2")
    membership = verify_q_points(BravaisLattice2D(np.diag([2.0, 2.0])), points)
    assert all(item["inside"] for item in membership["points"].values())


def test_r6_sign_algebra_and_complete_band_guard():
    raw = {
        0.0: np.array([.10, .30, .80]), 0.005: np.array([.10, .31, .81]),
        -0.005: np.array([.10, .29, .79]), 0.0025: np.array([.10, .305, .805]),
        -0.0025: np.array([.10, .295, .795]),
    }
    result = sign_reversal("q1", 1, raw, 1e-4, baseline_spectrum=raw[0.0],
                           perturbed_spectra=np.max(np.vstack(list(raw.values())[1:]), axis=0))
    assert np.isclose(result.odd_a, .01)
    assert np.isclose(result.even_a, 0.0)
    assert np.isclose(result.odd_half, .005)
    assert np.isclose(result.even_half, 0.0)
    assert result.eligibility.eligible


def test_band_supercell_adapter_rejects_unverified_local_field():
    from mephc.band import Band
    field = AnalyticDeformationField(lambda points: np.zeros_like(points), stable_id="local")
    with unittest.TestCase().assertRaisesRegex(Exception, "SUPERCELL"):
        Band().build_supercell_solver([], field, q_points=q_points(), num_bands=6, resolution=8)


if __name__ == "__main__":
    test_r6_benchmark_field_is_verified_and_periodic()
    test_r6_q_points_are_generic_and_inside_supercell_bz()
    test_r6_sign_algebra_and_complete_band_guard()
    test_band_supercell_adapter_rejects_unverified_local_field()
