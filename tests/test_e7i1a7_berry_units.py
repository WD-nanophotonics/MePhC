import math

import pytest

from mephc.berry_units import (
    OMEGA_PHYS_OVER_A2,
    OMEGA_Q,
    Q_COORDINATE_SPACE,
    convert_curvature,
    curvature_unit_provenance,
    omega_phys_over_a2_to_q,
    omega_q_to_phys_over_a2,
)
from mephc.plaquette_semantics import CENTERED_CCW, build_local_plaquette, polygon_signed_area


def test_exact_q_to_physical_a2_conversion_round_trip_and_sign_preservation():
    assert omega_q_to_phys_over_a2(4 * math.pi**2) == pytest.approx(1.0)
    for value in (-12.1426, -1.0, 0.0, 3.25):
        physical = omega_q_to_phys_over_a2(value)
        assert omega_phys_over_a2_to_q(physical) == pytest.approx(value)
        assert convert_curvature(value, OMEGA_Q, OMEGA_PHYS_OVER_A2) == pytest.approx(physical)
        assert math.copysign(1.0, physical) == math.copysign(1.0, value)


@pytest.mark.parametrize("bad", (True, float("nan"), float("inf"), "12"))
def test_conversion_rejects_invalid_values(bad):
    with pytest.raises(ValueError):
        omega_q_to_phys_over_a2(bad)


def test_unit_provenance_is_structured_and_json_safe():
    provenance = curvature_unit_provenance(
        unit_space=OMEGA_PHYS_OVER_A2,
        requested_k_space=Q_COORDINATE_SPACE,
        plaquette_vertex_space=Q_COORDINATE_SPACE,
        signed_area_space=Q_COORDINATE_SPACE,
        plaquette_convention=CENTERED_CCW,
        orientation="CCW",
        representation="test",
        wilson_phase=0.25,
    )
    assert provenance["curvature_unit_space"] == OMEGA_PHYS_OVER_A2
    assert provenance["two_pi_squared_conversion_applied"] is True
    assert provenance["signed_area_coordinate_space"] == Q_COORDINATE_SPACE
    assert provenance["wilson_phase"] == 0.25


def test_centered_and_reversed_synthetic_plaquettes_preserve_the_two_form():
    geometry = build_local_plaquette((0.2, -0.1), 0.04, convention=CENTERED_CCW)
    omega_q = 2.5
    phase = -omega_q * geometry.signed_area
    reversed_vertices = tuple(reversed(geometry.ordered_vertices))
    reversed_area = polygon_signed_area(reversed_vertices)
    reversed_phase = -phase
    assert -phase / geometry.signed_area == pytest.approx(omega_q)
    assert -reversed_phase / reversed_area == pytest.approx(omega_q)
    assert omega_q_to_phys_over_a2(-phase / geometry.signed_area) == pytest.approx(
        omega_q_to_phys_over_a2(-reversed_phase / reversed_area)
    )


def test_historical_e7i_d0500_value_is_q_space_and_maps_explicitly():
    historical_q = -12.1426
    assert omega_q_to_phys_over_a2(historical_q) == pytest.approx(-0.3075756511, rel=1e-8)
