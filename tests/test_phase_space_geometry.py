from __future__ import annotations

from dataclasses import replace
import numpy as np
import pytest

from mephc.phase_space_geometry import (
    DiamondGeometryMismatchError,
    FixedQDerivativeMismatchError,
    HState,
    InvalidNormalizationError,
    MU1_NONMAGNETIC,
    ReferenceCellIdentity,
    ReferenceCellMismatchError,
    REPRESENTATION,
    h_state_from_normalized_vectors,
    make_mixed_diamond,
    rank1_mixed_curvature,
    rankN_trace_mixed_curvature,
    reverse_mixed_curvature,
)


def ref(**kwargs):
    values = dict(representation=REPRESENTATION, bloch_phase_excluded=True, resolution=8, spatial_shape=(1, 1), lattice_size=(1.0, 1.0), component_order="supplied final axis order", component_basis="LAB_CARTESIAN", mu_contract=MU1_NONMAGNETIC, orientation_sign=1, fractional_material_indexing_identity="same fractional (ix,iy) material coordinates", reference_cell_identity="test-cell")
    values.update(kwargs)
    return ReferenceCellIdentity(**values)


def state(q, s, vector, reference, frequency=1.0, bands=(0,)):
    F = ((float(np.exp(s)), 0.0), (0.0, float(np.exp(-s))))
    identity = __import__("mephc.phase_space_geometry", fromlist=["PhaseSpaceStateIdentity"]).PhaseSpaceStateIdentity(q, s, q, F, F, "test-geometry", reference, "test-settings")
    return h_state_from_normalized_vectors(identity, vector if len(bands) == 1 else tuple(vector), frequencies=(frequency,) if len(bands) == 1 else tuple(frequency + i for i in range(len(bands))), band_indices=bands)


def vertices(reference, hq=0.1, hs=0.08):
    q = (0.4, 0.2); s = 0.3
    values = {
        "plus_q": (q[0] + hq, q[1], s), "plus_s": (q[0], q[1], s + hs),
        "minus_q": (q[0] - hq, q[1], s), "minus_s": (q[0], q[1], s - hs),
    }
    result = {}
    for role, (qx, qy, sv) in values.items():
        angle = 0.4 * qx
        result[role] = state((qx, qy), sv, np.array([np.cos(angle), np.exp(0.7j * sv) * np.sin(angle)]), reference)
    return result, q, s


def diamond(reference, hq=0.1, hs=0.08):
    values, q, s = vertices(reference, hq, hs)
    return make_mixed_diamond(**values, axis=0, h_q=hq, h_s=hs, q_center=q, s_center=s)


def test_rank1_and_reverse_are_signed_and_rankn_is_trace_only():
    d = diamond(ref())
    rank1 = rank1_mixed_curvature(d)
    reverse = reverse_mixed_curvature(d)
    assert rank1.rank == 1
    assert reverse.omega_qs == pytest.approx(-rank1.omega_qs, abs=1e-12)
    assert rankN_trace_mixed_curvature(d).interpretation == "TRACE_OR_U1_SUBSPACE_GEOMETRY_ONLY"


def test_mismatched_reference_metadata_fails_before_overlap():
    reference = ref()
    values, q, s = vertices(reference)
    altered = replace(reference, resolution=9)
    values["minus_s"] = state((q[0], q[1]), s - 0.08, np.array([1.0, 0.0]), altered)
    with pytest.raises(ReferenceCellMismatchError):
        make_mixed_diamond(**values, axis=0, h_q=0.1, h_s=0.08, q_center=q, s_center=s)


def test_centered_geometry_and_fixed_q_derivative_are_explicit():
    reference = ref()
    d = diamond(reference)
    assert d.signed_area_qs == pytest.approx(2 * 0.1 * 0.08)
    with pytest.raises(DiamondGeometryMismatchError):
        make_mixed_diamond(plus_q=d.plus_q, plus_s=d.plus_s, minus_q=d.minus_q, minus_s=d.minus_s, axis=0, h_q=0.2, h_s=0.08, q_center=d.q_center, s_center=d.s_center)
    with pytest.raises(FixedQDerivativeMismatchError):
        __import__("mephc.phase_space_geometry", fromlist=["fixed_q_frequency_derivative"]).fixed_q_frequency_derivative(d.plus_s, state((0.41, 0.2), d.minus_s.identity.s, d.minus_s.h_vectors[0], reference), band_index=0, h_s=0.08)


def test_normalized_vectors_are_consumed_without_silent_rescaling():
    reference = ref()
    identity = vertices(reference)[0]["plus_q"].identity
    with pytest.raises(InvalidNormalizationError):
        h_state_from_normalized_vectors(identity, [np.array([2.0, 0.0])])


def test_independent_steps_are_retained():
    d = diamond(ref(), hq=0.07, hs=0.013)
    assert d.h_q == pytest.approx(0.07)
    assert d.h_s == pytest.approx(0.013)
