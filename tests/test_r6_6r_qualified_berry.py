import inspect
from unittest.mock import patch

import meep as mp
import numpy as np
import pytest

from mephc.band import Band
from mephc.berry import BerryCurvatureCalculator, BerryCurvatureResult
from mephc.bravais import BravaisLattice2D
from mephc.convergence import EigenmodeConvergenceProvenance, EigenmodePairEvidence, certify_eigenmode_convergence, NumericalConvergenceError
from mephc.deformation import PeriodicSupercellField
from mephc.qualified_berry import EigenmodeQualifiedSupercellBerryCalculator
from mephc.response import R6_AMPLITUDES, benchmark_field


def pattern():
    return [np.array([[0.1, 0.1], [0.2, 0.1], [0.1, 0.2]], dtype=float)]


def field():
    return benchmark_field(BravaisLattice2D.square(), R6_AMPLITUDES[0])


def certificate_for(context, *, target_band=0, num_bands=2, resolution=4, polarization="TE", deterministic=True, tolerance=1e-7, mesh_size=3):
    provenance = EigenmodeConvergenceProvenance(
        backend="mpb", geometry_digest=context.identity.digest,
        target_band=target_band, num_bands=num_bands, polarization=polarization,
        deterministic=deterministic, eigensolver_tolerance=tolerance,
        mesh_size=mesh_size, field_representation="periodic_h_bloch_envelope",
    )
    return certify_eigenmode_convergence([
        EigenmodePairEvidence(2, 3, 1e-8, 0.999999, 1e-4, 0.26),
        EigenmodePairEvidence(3, resolution, 1e-8, 0.999999, 1e-4, 0.26),
    ], provenance=provenance)


def make_pass_request(band=None, *, resolution=4, target_band=0, num_bands=2, **kwargs):
    band = band or Band(resolution=4, lattice_type="square")
    live_context = band._prepare_supercell_geometry(pattern(), field())
    certificate = certificate_for(
        live_context, target_band=target_band, num_bands=num_bands,
        resolution=resolution, **kwargs,
    )
    return band, certificate


def test_exact_live_pass_is_lazy_and_fixed_configuration():
    band, certificate = make_pass_request()
    with patch.object(band, "_prepare_supercell_geometry", wraps=band._prepare_supercell_geometry) as prepare:
        with patch("mephc.band.mpb.ModeSolver") as mode_solver:
            qualified = band.build_eigenmode_qualified_supercell_berry_calculator(
                pattern(), field(), certificate=certificate, target_band=0,
                num_bands=2, resolution=4,
            )
    assert prepare.call_count == 1
    mode_solver.assert_not_called()
    assert isinstance(qualified, EigenmodeQualifiedSupercellBerryCalculator)
    assert qualified.scope_binding.status == "PASS"
    assert qualified.scope_binding.certified_resolution == 4
    assert qualified.calculator.overlap_formulation == "mpb_h"
    assert qualified.calculator.mesh_size == 3
    assert qualified.expected_provenance.field_representation == "periodic_h_bloch_envelope"
    assert "Berry observable convergence" not in str(qualified.qualification_dict())
    assert "band_index" not in inspect.signature(qualified.calculate).parameters


@pytest.mark.parametrize("resolution", [3, 2, 5, 8])
def test_resolution_scope_replay_is_blocked(resolution):
    band, certificate = make_pass_request(resolution=4)
    with pytest.raises(NumericalConvergenceError):
        band.build_eigenmode_qualified_supercell_berry_calculator(
            pattern(), field(), certificate=certificate, target_band=0,
            num_bands=2, resolution=resolution,
        )


def test_geometry_and_band_replay_are_blocked():
    band, certificate = make_pass_request()
    with pytest.raises(NumericalConvergenceError):
        band.build_eigenmode_qualified_supercell_berry_calculator(
            [np.array([[0.11, 0.1], [0.2, 0.1], [0.1, 0.2]])], field(),
            certificate=certificate, target_band=0, num_bands=2, resolution=4,
        )
    with pytest.raises(NumericalConvergenceError):
        band.build_eigenmode_qualified_supercell_berry_calculator(
            pattern(), field(), certificate=certificate, target_band=1,
            num_bands=2, resolution=4,
        )
    with pytest.raises(NumericalConvergenceError):
        band.build_eigenmode_qualified_supercell_berry_calculator(
            pattern(), field(), certificate=certificate, target_band=0,
            num_bands=3, resolution=4,
        )


@pytest.mark.parametrize("kwargs", [
    {"polarization": "TM"},
    {"deterministic": False},
    {"eigensolver_tolerance": 1e-6},
    {"mesh_size": 5},
])
def test_solver_provenance_mismatch_fails_before_solver(kwargs):
    band, certificate = make_pass_request()
    with patch("mephc.band.mpb.ModeSolver") as mode_solver:
        with pytest.raises(NumericalConvergenceError):
            band.build_eigenmode_qualified_supercell_berry_calculator(
                pattern(), field(), certificate=certificate, target_band=0,
                num_bands=2, resolution=4, **kwargs,
            )
    mode_solver.assert_not_called()


def test_fixed_band_and_grid_delegation():
    band, certificate = make_pass_request(target_band=1, num_bands=2)
    qualified = band.build_eigenmode_qualified_supercell_berry_calculator(
        pattern(), field(), certificate=certificate, target_band=1,
        num_bands=2, resolution=4,
    )
    with patch.object(qualified.calculator, "calculate", return_value=0.25) as calculate:
        assert qualified.calculate((0.1, 0.2), 0.01) == 0.25
    calculate.assert_called_once_with((0.1, 0.2), step=0.01, band_index=1)
    result = BerryCurvatureResult(np.zeros((1, 2)), np.array([0.1]), 1, 0.01)
    with patch.object(qualified.calculator, "calculate_grid", return_value=result) as grid:
        assert qualified.calculate_grid([(0.1, 0.2)], 0.01) is result
    grid.assert_called_once_with([(0.1, 0.2)], step=0.01, band_index=1)


def test_mesh_state_is_explicit_and_legacy_default_remains_three():
    calculator = BerryCurvatureCalculator([], mp.Lattice(size=mp.Vector3(1, 1, 0)), 2, 1)
    assert calculator.mesh_size == 3
    explicit = BerryCurvatureCalculator([], mp.Lattice(size=mp.Vector3(1, 1, 0)), 2, 1, mesh_size=5)
    assert explicit.mesh_size == 5
    for value in (True, False, 0, -1, 1.5, "3"):
        with patch("mephc.berry.mpb.ModeSolver") as mode_solver:
            with pytest.raises(ValueError):
                BerryCurvatureCalculator([], mp.Lattice(size=mp.Vector3(1, 1, 0)), 2, 1, mesh_size=value)
        mode_solver.assert_not_called()
    with patch("mephc.berry.mpb.ModeSolver", return_value=object()) as mode_solver:
        explicit.build_solver(mp.Vector3())
    assert mode_solver.call_args.kwargs["mesh_size"] == 5
    band, certificate = make_pass_request()
    legacy = band.build_supercell_berry_calculator(
        pattern(), field(), num_bands=2, resolution=4, certificate=None
    ) if False else band.build_supercell_berry_calculator(
        pattern(), field(), num_bands=2, resolution=4
    )
    assert legacy.overlap_formulation == "energy_eh"
    assert legacy.mesh_size == 3
