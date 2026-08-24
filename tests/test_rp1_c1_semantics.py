import copy
import json
from pathlib import Path

import pytest

from audit.e9f.rp1_policy import RP1ContractError, validate_policy_contract


ROOT = Path(__file__).parents[1]
PATH = ROOT / "audit/e9f/rp1_recovery_policy_contract.json"


def contract():
    return json.loads(PATH.read_text(encoding="utf-8"))


@pytest.mark.parametrize("mutation,code", [
    (lambda c: c["finite_stencil_policy"]["alternatives"][0].update(stencil="1/72"), "F1_STENCIL_MUTATED"),
    (lambda c: c["finite_stencil_policy"]["alternatives"][0].update(estimator_scope="only_11"), "F1_SCOPE_MUTATED"),
    (lambda c: c["finite_stencil_policy"].update(no_silent_mixing_of_11_fine_with_540_coarse=False), "F1_SILENT_MIXING_ALLOWED"),
    (lambda c: c["rp2_diagnostic_matrix"].update(fixed_resolutions=[64, 96, 128]), "RP2_RESOLUTION_MATRIX_MUTATED"),
    (lambda c: c["rp2_diagnostic_matrix"].update(fixed_plaquette_stencils=["1/72"]), "RP2_STENCIL_MATRIX_MUTATED"),
    (lambda c: c["rp2_diagnostic_matrix"].update(fixed_sample_ids=[]), "RP2_SAMPLE_SET_MUTATED"),
    (lambda c: c["reducer_firewall"].update(diagnostic_only_is_reducer_admissible=True), "REDUCER_FIREWALL_INVALID"),
    (lambda c: c["source_anchor_firewall"].update(source_anchor_available_to_diagnostic_runner=True), "SOURCE_ANCHOR_FIREWALL_INVALID"),
    (lambda c: c["l1_exact_shadow_contract"].update(area_normalized_estimator="raw_phase"), "L1_AREA_NORMALIZATION_MISSING"),
    (lambda c: c["l3_consistency_metric"].update(metric="CONSISTENCY_PASSED"), "L3_METRIC_UNDEFINED_OR_MUTATED"),
])
def test_policy_semantic_mutation_fails_closed(mutation, code):
    mutated = contract()
    mutation(mutated)
    with pytest.raises(RP1ContractError, match=code):
        validate_policy_contract(mutated, ROOT)


@pytest.mark.parametrize("field", [
    "band2_recovery_execution_authorized", "berry_calculation_authorized",
    "chern_calculation_authorized", "live_mpb_authorized", "main_push_authorized",
    "scientific_sample_solves_authorized", "three_band_aggregate_authorized",
    "threshold_change_authorized",
])
def test_every_execution_firewall_flag_is_fail_closed(field):
    mutated = contract()
    mutated["execution_authorization"][field] = True
    with pytest.raises(RP1ContractError, match=f"EXECUTION_FIREWALL_MUTATED:{field}"):
        validate_policy_contract(mutated, ROOT)


def test_fixed_matrix_has_no_optional_escalation():
    c = contract()
    assert c["rp2_diagnostic_matrix"]["optional_escalation_present"] is False
    assert "optional_higher_resolution" not in c["low_gap_policy"]["diagnostic_ladder"][0]
    assert "optional_stencil" not in c["low_gap_policy"]["diagnostic_ladder"][1]
    assert c["l1_exact_shadow_contract"]["area_normalized_estimator"] == "OMEGA_RANK1_SHADOW=PHI_RANK1_WRAPPED/h^2"
