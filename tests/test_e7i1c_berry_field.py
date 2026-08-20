import json
import math

import numpy as np
import pytest

from mephc.berry_field import (
    D2K_PHYSICAL,
    D2Q,
    EXPLICIT_SUBDOMAIN,
    MASKED,
    MaskedFieldError,
    QUALIFIED_VALUE,
    QualifiedBerryField,
    QualifiedBerryFieldPoint,
    STRICT_FAIL_CLOSED,
    BerryFieldModelError,
    CoordinateMeasureContract,
    integrate_qualified_field,
)
from mephc.berry_units import OMEGA_PHYS_OVER_A2, OMEGA_Q


CONTRACT = CoordinateMeasureContract(lattice_scale_a=2.5)


def point(x, y, fn, *, masked=False):
    value = None if masked else float(fn(x, y))
    physical = None if value is None else CONTRACT.omega_q_to_phys_over_a2(value)
    return QualifiedBerryFieldPoint(
        q_coordinate=(x, y),
        omega_q=value,
        omega_phys_over_a2=physical,
        selected_bands_one_based=(1,),
        rank=1,
        production_decision=MASKED if masked else QUALIFIED_VALUE,
        mask_reason="UNQUALIFIED_TRANSPORT" if masked else None,
        evidence_axes={"transport_quality": {"status": "FAIL" if masked else "PASS"}},
        resolution=64,
        plaquette_h=0.001,
        representation="synthetic-field-v1",
        geometry_identity="synthetic-geometry",
        provenance={"fixture": True},
    )


def make_field(xs, ys, fn, *, masked=None):
    masked = set(masked or ())
    return QualifiedBerryField(
        tuple(xs), tuple(ys),
        tuple(point(x, y, fn, masked=(x, y) in masked) for x in xs for y in ys),
        CONTRACT,
        geometry_identity="synthetic-geometry",
        representation="synthetic-field-v1",
    )


def test_constant_field_and_dual_measure_are_identical():
    field = make_field((-1.0, 0.0, 1.0), (-1.0, 0.0, 1.0), lambda _x, _y: 2.0)
    q_result = integrate_qualified_field(field, curvature_unit=OMEGA_Q, measure=D2Q)
    k_result = integrate_qualified_field(field, curvature_unit=OMEGA_PHYS_OVER_A2, measure=D2K_PHYSICAL)
    assert q_result.value == pytest.approx(8.0)
    assert k_result.value == pytest.approx(q_result.value, abs=1e-12)
    assert field.to_dict()["measure_contract"]["q_to_k_jacobian"] == pytest.approx((2 * math.pi / 2.5) ** 2)


def test_linear_and_sign_changing_fields_have_signed_integrals():
    field = make_field((-1.0, 0.0, 1.0), (-1.0, 0.0, 1.0), lambda x, y: x + 2 * y)
    assert integrate_qualified_field(field).value == pytest.approx(0.0, abs=1e-14)
    sign_changing = make_field((-1.0, 0.0, 1.0), (-1.0, 0.0, 1.0), lambda x, y: x * y)
    assert integrate_qualified_field(sign_changing).value == pytest.approx(0.0, abs=1e-14)


def test_separable_quadratic_converges_to_known_exact_integral():
    exact = 8.0 / 3.0
    coarse = np.linspace(-1.0, 1.0, 21)
    fine = np.linspace(-1.0, 1.0, 81)
    coarse_value = integrate_qualified_field(make_field(coarse, coarse, lambda x, y: x * x + y * y)).value
    fine_value = integrate_qualified_field(make_field(fine, fine, lambda x, y: x * x + y * y)).value
    assert abs(fine_value - exact) < abs(coarse_value - exact)
    assert fine_value == pytest.approx(exact, abs=1e-3)


def test_orientation_is_signed_and_reversing_both_axes_restores_sign():
    increasing = make_field((-1.0, 0.0, 1.0), (-1.0, 0.0, 1.0), lambda x, y: 1.0 + x + 2 * y)
    reverse_x = make_field((1.0, 0.0, -1.0), (-1.0, 0.0, 1.0), lambda x, y: 1.0 + x + 2 * y)
    reverse_y = make_field((-1.0, 0.0, 1.0), (1.0, 0.0, -1.0), lambda x, y: 1.0 + x + 2 * y)
    reverse_both = make_field((1.0, 0.0, -1.0), (1.0, 0.0, -1.0), lambda x, y: 1.0 + x + 2 * y)
    base = integrate_qualified_field(increasing).value
    assert integrate_qualified_field(reverse_x).value == pytest.approx(-base)
    assert integrate_qualified_field(reverse_y).value == pytest.approx(-base)
    assert integrate_qualified_field(reverse_both).value == pytest.approx(base)
    assert integrate_qualified_field(reverse_x, subdomain=(-1.0, 1.0, -1.0, 1.0)).value == pytest.approx(-base)
    assert integrate_qualified_field(reverse_y, subdomain=(-1.0, 1.0, -1.0, 1.0)).value == pytest.approx(-base)
    assert integrate_qualified_field(reverse_both, subdomain=(-1.0, 1.0, -1.0, 1.0)).value == pytest.approx(base)


def test_masked_points_fail_closed_and_explicit_subdomain_is_still_explicit():
    field = make_field((-1.0, 0.0, 1.0), (-1.0, 0.0, 1.0), lambda _x, _y: 1.0, masked={(-1.0, -1.0)})
    with pytest.raises(MaskedFieldError):
        integrate_qualified_field(field, mask_policy=STRICT_FAIL_CLOSED)
    result = integrate_qualified_field(
        field,
        mask_policy=EXPLICIT_SUBDOMAIN,
        subdomain=(0.0, 1.0, 0.0, 1.0),
    )
    assert result.value == pytest.approx(1.0)
    with pytest.raises(BerryFieldModelError):
        integrate_qualified_field(field, mask_policy="MASK_AS_ZERO")


def test_missing_duplicate_nonmonotonic_and_incompatible_grid_fail_closed():
    valid = make_field((-1.0, 0.0, 1.0), (-1.0, 0.0, 1.0), lambda _x, _y: 1.0)
    with pytest.raises(BerryFieldModelError):
        QualifiedBerryField((-1.0, 0.0, 1.0), (-1.0, 0.0, 1.0), valid.points[:-1], CONTRACT)
    with pytest.raises(BerryFieldModelError):
        QualifiedBerryField((-1.0, 0.0, 1.0), (-1.0, 0.0, 1.0), valid.points + (valid.points[0],), CONTRACT)
    with pytest.raises(BerryFieldModelError):
        make_field((-1.0, 0.0, 1.0), (-1.0, 1.0, 0.0), lambda _x, _y: 1.0)
    incompatible = point(-1.0, -1.0, lambda _x, _y: 1.0)
    incompatible = QualifiedBerryFieldPoint.from_mapping(
        {**incompatible.to_dict(), "geometry_identity": "different-geometry"}
    )
    with pytest.raises(BerryFieldModelError):
        QualifiedBerryField(valid.q_x, valid.q_y, valid.points[:-1] + (incompatible,), CONTRACT)


def test_serialization_round_trip_preserves_semantics_and_rejects_fake_mask_value():
    field = make_field((-1.0, 0.0, 1.0), (-1.0, 0.0, 1.0), lambda x, y: x - y)
    encoded = json.dumps(field.to_dict())
    restored = QualifiedBerryField.from_dict(json.loads(encoded))
    assert restored.to_dict() == field.to_dict()
    masked = point(0.0, 0.0, lambda _x, _y: 1.0, masked=True)
    bad = masked.to_dict()
    bad["omega_q"] = 0.0
    with pytest.raises(BerryFieldModelError):
        QualifiedBerryFieldPoint.from_mapping(bad)


def test_measure_mismatch_cannot_be_labeled_as_a_physical_k_integral():
    field = make_field((-1.0, 0.0, 1.0), (-1.0, 0.0, 1.0), lambda _x, _y: 1.0)
    with pytest.raises(BerryFieldModelError):
        integrate_qualified_field(field, curvature_unit=OMEGA_PHYS_OVER_A2, measure=D2Q)
    with pytest.raises(BerryFieldModelError):
        integrate_qualified_field(field, curvature_unit=OMEGA_Q, measure=D2K_PHYSICAL)
