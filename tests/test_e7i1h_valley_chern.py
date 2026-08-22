import json
import math
from pathlib import Path

import pytest

from mephc.valley_chern import (
    V_K_AREA,
    audit_from_c9_report,
    build_valley_chern_audit,
    coordinate_flux_invariance,
    inherited_paper_convention,
    time_reversal_theory,
    valley_chern_from_flux,
)


def fluxes():
    return {"band1": -2.0, "band2": 1.0, "anti": -3.0, "common": -1.0}


def controls():
    return {"BERRY_TORUS_PERIODICITY": "CONFIRMED"}


def domain_inversion():
    return {
        "status": "SIGN_REVERSAL_SUPPORTED",
        "evidence_level": "LOCAL_MATCHED_CONTROLS",
        "source_digest": "a" * 64,
        "reducer_code_digest": "b" * 64,
        "provenance_mode": "INHERITED_FROM_SEALED_REDUCER_OUTPUT",
    }


def tr_controls():
    return {
        "status": "SUPPORTED_BY_EXISTING_CONTROLS",
        "evidence_level": "LOCAL_MATCHED_CONTROLS",
        "matched_control_count": 3,
        "band1_sign_antisymmetry_residual": 1e-9,
        "band2_sign_antisymmetry_residual": 2e-9,
        "spectral_correspondence": True,
        "qualification_compatibility": True,
        "full_kp_integration": False,
        "source_digest": "c" * 64,
        "reducer_code_digest": "d" * 64,
    }


def test_normalization_and_orientation_sign():
    assert valley_chern_from_flux(2 * math.pi) == pytest.approx(1.0)
    assert valley_chern_from_flux(2 * math.pi, orientation_sign=-1) == pytest.approx(-1.0)
    with pytest.raises(ValueError):
        valley_chern_from_flux(1.0, orientation_sign=0)


def test_coordinate_invariance_has_no_extra_two_pi_factor():
    check = coordinate_flux_invariance(3.5, V_K_AREA, 2.5)
    assert check["equal"] is True
    assert check["restored_physical_flux"] == pytest.approx(check["q_flux"], abs=1e-14)


def test_tr_theory_is_separate_from_periodicity_and_inversion():
    theory = time_reversal_theory()
    assert theory["TR_BERRY_RELATION"] == "Omega_n(k)=-Omega_n(-k)"
    result = build_valley_chern_audit(fluxes(), control_status=controls(), domain_inversion_evidence=domain_inversion())
    assert result["TR_VALLEY_RELATION_THEORY"] == "DERIVED"
    assert result["TR_VALLEY_RELATION_NUMERIC_STATUS"] == "UNRESOLVED"
    assert result["VALLEY_CHERN_DOMAIN_INVERSION"] == "SIGN_REVERSAL_SUPPORTED"


def test_dedicated_kp_controls_support_tr_without_claiming_full_integration():
    result = build_valley_chern_audit(
        fluxes(), tr_evidence=tr_controls(), domain_inversion_evidence=domain_inversion()
    )
    assert result["TR_VALLEY_RELATION_NUMERIC_STATUS"] == "SUPPORTED_BY_EXISTING_CONTROLS"
    assert result["TR_KP_CONTROL_EVIDENCE"]["matched_control_count"] == 3
    assert result["TR_KP_CONTROL_EVIDENCE"]["full_kp_integration"] is False


def test_paper_mapping_is_explicit_and_has_no_sign_hack():
    result = build_valley_chern_audit(
        fluxes(), paper_convention=inherited_paper_convention()
    )
    assert result["PAPER_VALLEY_CHERN_CONVENTION"] == "CONSISTENT_AFTER_BLOCH_K_MAPPING"
    assert result["PAPER_GEOMETRY_EQUIVALENCE"] == "UNRESOLVED"
    assert result["SIGN_HACK"] == "NONE"
    assert result["PAPER_CONVENTION_AUDIT"]["mapping_validated"] is True


def test_missing_paper_and_tr_evidence_fail_to_unresolved():
    result = build_valley_chern_audit(fluxes())
    assert result["TR_VALLEY_RELATION_NUMERIC_STATUS"] == "UNRESOLVED"
    assert result["PAPER_VALLEY_CHERN_CONVENTION"] == "UNRESOLVED"
    assert result["VALLEY_CHERN_DOMAIN_INVERSION"] == "UNRESOLVED"


def test_domain_and_band_provenance_are_explicit():
    result = build_valley_chern_audit(fluxes(), domain_inversion_evidence=domain_inversion())
    assert result["DOMAIN"]["id"] == "PERIODIC_RECIPROCAL_METRIC_VORONOI_BASIN_K"
    assert result["DOMAIN"]["boundary_convention"].startswith("zero_measure")
    assert result["DOMAIN"]["orientation"] == "POSITIVE_PUBLIC_CARTESIAN_QX_QY"
    assert result["BAND_INTERPRETATION"]["band1"] == "PRIMARY_PHYSICAL_VALLEY_OBSERVABLE"
    assert result["BAND_INTERPRETATION"]["anti"] == "DIAGNOSTIC_LINEAR_COMBINATION"
    assert result["NONQUANTIZED_VALLEY_CHERN_INTERPRETATION"] == "MATHEMATICALLY_CLOSED"
    assert result["VALLEY_CHERN_DOMAIN_SEMANTICS"] == "EXPLICIT_AND_BOUNDARY_AWARE"


def test_committed_c9_report_preserves_accepted_normalization_but_not_unproven_semantics():
    root = Path(__file__).parents[1]
    report = json.loads((root / "audit/e7i1g_c1/fixtures/c9_source_bound_report.json").read_text())
    result = audit_from_c9_report(report, paper_convention=inherited_paper_convention())
    assert result["VALLEY_CHERN"]["band1"] == pytest.approx(-0.8672556366262376 / (2 * math.pi))
    assert result["VALLEY_CHERN"]["band2"] == pytest.approx(0.39539937924821406 / (2 * math.pi))
    assert result["TR_VALLEY_RELATION_NUMERIC_STATUS"] == "UNRESOLVED"
    assert result["PAPER_VALLEY_CHERN_CONVENTION"] == "CONSISTENT_AFTER_BLOCH_K_MAPPING"
    assert result["C9_HARDENED_ARTIFACT_REPLAY"] == "FAILED"
