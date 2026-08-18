from unittest.mock import patch

import meep as mp
from meep import mpb
import numpy as np
import pytest

from mephc.band import Band
from mephc.berry import BerryCurvatureCalculator
from mephc.bravais import BravaisLattice2D
from mephc.deformation import (
    AnalyticDeformationField,
    PeriodicSupercellField,
    ZeroDeformationField,
)
from mephc.response import R6_AMPLITUDES, benchmark_field


def make_field(replication=(2, 2)):
    field = benchmark_field(BravaisLattice2D.square(), R6_AMPLITUDES[0])
    if tuple(replication) == (2, 2):
        return field
    base = ZeroDeformationField()
    return PeriodicSupercellField(
        base,
        BravaisLattice2D.square(),
        replication_matrix=((replication[0], 0), (0, replication[1])),
    )


def test_solver_and_factory_consume_one_shared_geometry_context():
    band = Band(resolution=8)
    field = make_field()
    context = band._prepare_supercell_geometry([], field)
    with patch.object(band, "_prepare_supercell_geometry", return_value=context) as prepare:
        with patch("mephc.band.mpb.ModeSolver", return_value=object()) as mode_solver:
            band.build_supercell_solver([], field, q_points=[(0.0, 0.0)], num_bands=2, resolution=9)
            calculator = band.build_supercell_berry_calculator([], field, num_bands=2, resolution=9)
    assert prepare.call_count == 2
    assert mode_solver.call_args.kwargs["geometry_lattice"] is context.geometry_lattice
    assert mode_solver.call_args.kwargs["geometry"] is context.geometry
    assert calculator.geometry_lattice is context.geometry_lattice
    assert calculator.geometry is context.geometry


def test_replication_is_owned_by_verified_field():
    band = Band()
    context = band._prepare_supercell_geometry([], make_field((2, 3)))
    assert context.replication == (2, 3)
    assert context.geometry_lattice.size.x == 2
    assert context.geometry_lattice.size.y == 3


@pytest.mark.parametrize(
    "field",
    [
        AnalyticDeformationField(lambda points: np.zeros_like(points), stable_id="local"),
        PeriodicSupercellField(ZeroDeformationField(), BravaisLattice2D.square(), (2, 2), verify=False),
        PeriodicSupercellField(ZeroDeformationField(), BravaisLattice2D.square(), ((1, 1), (0, 1))),
    ],
)
def test_factory_rejects_invalid_supercell_fields_before_calculator(field):
    with patch("mephc.band.BerryCurvatureCalculator") as calculator:
        with pytest.raises(Exception):
            Band().build_supercell_berry_calculator([], field, num_bands=1)
        calculator.assert_not_called()


def test_factory_forwards_configuration_without_running_mpb():
    band = Band(resolution=8, polarization="TE")
    field = make_field()
    callback = lambda solver: solver
    with patch("mephc.band.mpb.ModeSolver") as mode_solver:
        calculator = band.build_supercell_berry_calculator(
            [],
            field,
            num_bands=4,
            resolution=11,
            overlap_tol=2e-9,
            run_band_func=callback,
            polarization="TM",
        )
    assert isinstance(calculator, BerryCurvatureCalculator)
    assert calculator.num_bands == 4
    assert calculator.resolution == 11
    assert calculator.overlap_tol == 2e-9
    assert calculator.run_band_func is callback
    assert calculator.polarization == mp.TM
    assert calculator.default_material is mp.air
    mode_solver.assert_not_called()


def test_primitive_berry_guards_remain_intact_for_supercell_field():
    band = Band(deformation_field=make_field())
    with pytest.raises(Exception):
        band.berry_calculator(num_bands=1)
    with pytest.raises(Exception):
        band.compute_berry_grid([], np.zeros((1, 2)), step=0.01, num_bands=1)


def test_supercell_q_point_high_symmetry_ids_still_fail_before_mode_solver():
    class NamedPoint:
        point_id = "Gamma"
        fractional = (0.0, 0.0)

    with patch("mephc.band.mpb.ModeSolver") as mode_solver:
        with pytest.raises(ValueError, match="q-point IDs"):
            Band().build_supercell_solver(
                [], make_field(), q_points=[NamedPoint()], num_bands=1
            )
    mode_solver.assert_not_called()
