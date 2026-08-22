import json
import math
from pathlib import Path

import pytest

from mephc.valley_chern import (
    V_K_AREA,
    audit_from_c9_report,
    build_valley_chern_audit,
    coordinate_flux_invariance,
    valley_chern_from_flux,
)


def test_phi_over_two_pi_and_orientation_sign():
    assert valley_chern_from_flux(2.0 * math.pi) == pytest.approx(1.0)
    assert valley_chern_from_flux(2.0 * math.pi, orientation_sign=-1) == pytest.approx(-1.0)
    with pytest.raises(ValueError):
        valley_chern_from_flux(1.0, orientation_sign=0)


def test_q_and_physical_k_flux_are_invariant_without_extra_two_pi_factor():
    check = coordinate_flux_invariance(3.5, V_K_AREA, 2.5)
    assert check["equal"] is True
    assert check["restored_physical_flux"] == pytest.approx(check["q_flux"], abs=1e-14)


def test_audit_separates_primary_bands_from_diagnostics_and_preserves_domain():
    result = build_valley_chern_audit(
        {"band1": -2.0, "band2": 1.0, "anti": -3.0, "common": -1.0},
        flux_error_bound={"band1": 0.02, "band2": 0.03, "anti": 0.04, "common": 0.01},
        control_status={"BERRY_TORUS_PERIODICITY": "CONFIRMED", "VORONOI_DOMAIN_INVERSION": "CONFIRMED"},
    )
    assert result["VALLEY_CHERN"]["band1"] == pytest.approx(-2.0 / (2.0 * math.pi))
    assert result["VALLEY_CHERN_ERROR_BOUND"]["band2"] == pytest.approx(0.03 / (2.0 * math.pi))
    assert result["DOMAIN"]["id"] == "PERIODIC_RECIPROCAL_METRIC_VORONOI_BASIN_K"
    assert result["NONQUANTIZED_VALLEY_CHERN_INTERPRETATION"] == "MATHEMATICALLY_CLOSED"
    assert result["VALLEY_CHERN_DOMAIN_INVERSION"] == "SIGN_REVERSAL_SUPPORTED"
    assert result["TIME_REVERSAL_VALLEY_RELATION"] == "SUPPORTED_BY_EXISTING_CONTROLS"
    assert result["VALLEY_CHERN_MULTIBAND_INTERPRETATION"].startswith("INDIVIDUAL_BANDS_PRIMARY")


def test_committed_c9_flux_maps_to_expected_e7i1h_values():
    root = Path(__file__).parents[1]
    report = json.loads((root / "audit/e7i1g_c1/fixtures/c9_source_bound_report.json").read_text())
    result = audit_from_c9_report(report)
    assert result["VALLEY_CHERN_NORMALIZATION"] == "PHI_OVER_2PI_CONFIRMED"
    assert result["VALLEY_FLUX_COORDINATE_INVARIANCE"] == "DERIVED_AND_VALIDATED"
    assert result["VALLEY_CHERN"]["band1"] == pytest.approx(-0.8672556366262376 / (2.0 * math.pi))
    assert result["VALLEY_CHERN"]["band2"] == pytest.approx(0.39539937924821406 / (2.0 * math.pi))
    assert result["VALLEY_CHERN"]["anti"] == pytest.approx(-0.6313275079372258 / (2.0 * math.pi))
    assert result["VALLEY_CHERN"]["common"] == pytest.approx(-0.23592812868901175 / (2.0 * math.pi))
    assert result["PAPER_GEOMETRY_EQUIVALENCE"] == "UNRESOLVED"
    assert result["PAPER_VALLEY_CHERN_CONVENTION"] == "CONSISTENT_AFTER_BLOCH_K_MAPPING"
    assert result["SIGN_HACK"] == "NONE"
    assert len(result["detail_digest"]) == 64
