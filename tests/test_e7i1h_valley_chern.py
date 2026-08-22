import json
import math
from pathlib import Path

import pytest

from mephc.valley_chern import (
    E7I1G_UPSTREAM_SEAL,
    SEALED_REFINED_FLUX,
    audit_from_c9_report,
    build_valley_chern_audit,
    coordinate_flux_invariance,
    inherited_paper_convention,
    inversion_control_audit,
    time_reversal_theory,
)


def _root():
    return Path(__file__).parents[1]


def _report():
    return json.loads((_root() / "audit/e7i1g_c1/fixtures/c9_source_bound_report.json").read_text())


def _controls():
    return json.loads((_root() / "audit/e7i1g_c1/fixtures/control_evidence.json").read_text())


def test_upstream_seal_is_required_and_mismatch_fails():
    missing = build_valley_chern_audit(SEALED_REFINED_FLUX, paper_convention=inherited_paper_convention())
    assert missing["E7I1G_UPSTREAM_SEAL_STATUS"] == "FAILED"
    invalid = dict(E7I1G_UPSTREAM_SEAL)
    invalid["domain_id"] = "WRONG_DOMAIN"
    failed = build_valley_chern_audit(SEALED_REFINED_FLUX, upstream_seal=invalid, paper_convention=inherited_paper_convention())
    assert failed["E7I1G_UPSTREAM_SEAL_STATUS"] == "FAILED"
    assert failed["SEALED_INPUT_DEPENDENCY"] == "FAILED"


def test_raw_unavailable_does_not_invalidate_upstream_seal():
    result = audit_from_c9_report(_report(), existing_controls=_controls(), paper_convention=inherited_paper_convention())
    assert result["E7I1G_UPSTREAM_SEAL_STATUS"] == "SUPERVISOR_SEALED"
    assert result["SEALED_INPUT_DEPENDENCY"] == "EXPLICIT_AND_FAIL_CLOSED"
    assert result["C9_CURRENT_RAW_REPLAY_AVAILABILITY"] == "UNAVAILABLE_CURRENT_WORKSPACE"
    assert result["C9_HARDENING_CURRENT_REPLAY_STATUS"] == "RAW_SOURCE_CURRENTLY_UNAVAILABLE"
    assert result["VALLEY_CHERN"]["band1"] == pytest.approx(-0.8672556366262376 / (2 * math.pi))
    assert result["VALLEY_CHERN"]["band2"] == pytest.approx(0.39539937924821406 / (2 * math.pi))


def test_inversion_gate_recomputes_existing_compact_controls():
    result = inversion_control_audit(_controls())
    assert result["status"] == "SIGN_REVERSAL_SUPPORTED"
    assert result["evidence_level"] == "LOCAL_MATCHED_CONTROLS"
    assert result["matched_control_count"] == 8
    assert result["inversion_hybrid_p90_band1"] <= 0.05
    assert result["inversion_hybrid_p90_band2"] <= 0.05
    assert result["source_digest"]
    assert result["reducer_code_digest"]


def test_tr_theory_is_separate_from_unavailable_kp_numeric_replay():
    result = audit_from_c9_report(_report(), existing_controls=_controls(), paper_convention=inherited_paper_convention())
    assert result["TR_VALLEY_RELATION_THEORY"] == "DERIVED"
    assert result["TR_VALLEY_RELATION_NUMERIC_STATUS"] == "UNRESOLVED"
    assert result["TR_CONTROL_RECOVERY"] == "NO_EXISTING_CONTROLS_FOUND"
    assert result["TR_THEORY"]["TR_AREA_JACOBIAN"] == "det(-I_2)=+1"


def test_paper_provenance_is_explicit_supervisor_inheritance_without_fake_hashes():
    result = inherited_paper_convention()
    assert result["provenance_mode"] == "INHERITED_FROM_SUPERVISOR_SEALED_REF6_1_CONVENTION"
    assert "source_digest" not in result
    assert "reducer_code_digest" not in result
    audit = audit_from_c9_report(_report(), existing_controls=_controls(), paper_convention=result)
    assert audit["PAPER_CONVENTION_PROVENANCE"] == "SUPERVISOR_SEALED_INHERITANCE"
    assert audit["PAPER_MAPPING_ORIENTATION"] == "ORIENTATION_PRESERVING_VALLEY_LABEL_SWAP"
    assert audit["SIGN_HACK"] == "NONE"


def test_normalization_and_coordinate_invariance_are_unchanged():
    assert coordinate_flux_invariance(1.2, 0.7, 2.5)["equal"]
    result = audit_from_c9_report(_report(), existing_controls=_controls(), paper_convention=inherited_paper_convention())
    assert result["VALLEY_CHERN_NORMALIZATION"] == "PHI_OVER_2PI_CONFIRMED"
    assert result["VALLEY_FLUX_COORDINATE_INVARIANCE"] == "DERIVED_AND_VALIDATED"
    assert result["COORDINATE_INVARIANCE_CHECK"]["equal"]


def test_domain_band_and_nonquantized_semantics_are_explicit():
    result = audit_from_c9_report(_report(), existing_controls=_controls(), paper_convention=inherited_paper_convention())
    assert result["DOMAIN"]["id"] == "PERIODIC_RECIPROCAL_METRIC_VORONOI_BASIN_K"
    assert result["DOMAIN"]["boundary_convention"] == "zero_measure_boundary_inherited_from_E7I1G"
    assert result["NONQUANTIZED_VALLEY_CHERN_INTERPRETATION"] == "MATHEMATICALLY_CLOSED"
    assert result["BAND_INTERPRETATION"]["band1"] == "PRIMARY_PHYSICAL_VALLEY_OBSERVABLE"
    assert result["BAND_INTERPRETATION"]["anti"] == "DIAGNOSTIC_LINEAR_COMBINATION"


def test_candidate_seal_does_not_depend_on_full_kp_or_current_raw_file():
    result = audit_from_c9_report(_report(), existing_controls=_controls(), paper_convention=inherited_paper_convention())
    assert result["VALLEY_CHERN_DOMAIN_INVERSION"] == "SIGN_REVERSAL_SUPPORTED"
    assert result["VALLEY_CHERN_SEAL"] == "CANDIDATE_FOR_SUPERVISOR_SEAL"
    assert result["E7I1H_C3_OVERALL"] == "FINAL_PROVENANCE_STATE_READY_FOR_SUPERVISOR_SEAL"
    assert result["E7I1H_REMOTE_AUDITABILITY"] == "COMPLETE"


def test_missing_inversion_controls_remains_unresolved_not_fabricated():
    result = audit_from_c9_report(_report(), paper_convention=inherited_paper_convention())
    assert result["VALLEY_CHERN_DOMAIN_INVERSION"] == "UNRESOLVED"
    assert result["VALLEY_CHERN_SEAL"] == "PARTIALLY_VALIDATED"


def test_time_reversal_theory_has_no_numeric_claim():
    theory = time_reversal_theory()
    assert theory["TR_BERRY_RELATION"] == "Omega_n(k)=-Omega_n(-k)"
    assert theory["TR_NUMERICAL_SCOPE"].startswith("theory_only")


def test_immutable_seal_identity_is_independent_of_raw_replay_state():
    for available in (False, True):
        seal = dict(E7I1G_UPSTREAM_SEAL)
        seal["raw_artifact_currently_available"] = available
        result = build_valley_chern_audit(SEALED_REFINED_FLUX, upstream_seal=seal, paper_convention=inherited_paper_convention())
        assert result["E7I1G_UPSTREAM_SEAL_STATUS"] == "SUPERVISOR_SEALED"
        assert result["UPSTREAM_SEAL_IDENTITY"] == "IMMUTABLE_SCIENTIFIC_PROVENANCE"


def test_c3_final_state_and_uncertainty_provenance_are_explicit():
    result = audit_from_c9_report(_report(), existing_controls=_controls(), paper_convention=inherited_paper_convention())
    assert result["UPSTREAM_SEAL_REPLAY_SEPARATION"] == "COMPLETE"
    assert result["C9_RAW_REPLAY_STATE"]["availability"] == "UNAVAILABLE_CURRENT_WORKSPACE"
    assert result["E7I1H_REMOTE_AUDITABILITY"] == "COMPLETE"
    assert result["VALLEY_CHERN_UNCERTAINTY_PROVENANCE"] == "INHERITED_FROM_SEALED_E7I1G_PERTURBED_NODE_BOUND"
    assert result["VALLEY_CHERN_ERROR_BOUND"]["band1"] == pytest.approx(2.9476777143580646e-11)


@pytest.mark.parametrize("field", ["sealed_sandbox_sha", "source_evidence_sha256", "domain_id", "orientation"])
def test_wrong_immutable_seal_identity_fails(field):
    seal = dict(E7I1G_UPSTREAM_SEAL)
    seal[field] = "WRONG"
    result = build_valley_chern_audit(SEALED_REFINED_FLUX, upstream_seal=seal, paper_convention=inherited_paper_convention())
    assert result["E7I1G_UPSTREAM_SEAL_STATUS"] == "FAILED"


def test_wrong_sealed_flux_fails_closed():
    flux = dict(SEALED_REFINED_FLUX)
    flux["band1"] += 1e-6
    result = build_valley_chern_audit(flux, upstream_seal=E7I1G_UPSTREAM_SEAL, paper_convention=inherited_paper_convention())
    assert result["E7I1G_UPSTREAM_SEAL_STATUS"] == "FAILED"


def test_unsupported_positive_tr_claim_without_evidence_fails():
    with pytest.raises(ValueError):
        audit_from_c9_report(_report(), existing_controls=_controls(), tr_evidence={"status": "SUPPORTED_BY_EXISTING_CONTROLS"}, paper_convention=inherited_paper_convention())
