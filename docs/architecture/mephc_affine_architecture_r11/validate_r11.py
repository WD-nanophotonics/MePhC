from __future__ import annotations
import hashlib, json, sys
from pathlib import Path

ROOT=Path(__file__).resolve().parent
SHA="c06f22d8b01fd3c3a6809553bb94ff6577501dfd540bdcf4275076209481e1ab"
REQ=["README.md","authoritative_contract.json","contract_preflight.json","preflight.json","protected_digest_check.json","r10_inheritance.json","primary_gap_clarification.json","first_order_selection_rule.md","first_order_selection_rule.json","tangent_geometry_equivalence.json","tangent_raw_spectra.json","tangent_sensitivities.json","full_pattern_raw_spectra.json","full_pattern_c1.json","same_input_repeat_floor.json","representation_control.json","uniform_translation_floor.json","band_identity_guard.json","uncertainty_budget.json","mechanism_adjudication.json","change_scope.json","trilatt_hold.json","solver_execution.json","test_coverage.csv","validation_report.md","known_limits.md","run_r11.py","validate_r11.py","validator_negative_fixtures.py"]
TERMINALS={"CLOSED_NONDEGENERATE_FIRST_ORDER_ZERO_SUPPORTED","CLOSED_ANALYTIC_FIRST_ORDER_ZERO_NUMERICAL_RESIDUAL_BOUNDED","BLOCKED_SELECTION_RULE_NUMERICAL_INCONSISTENCY","BLOCKED_FIRST_ORDER_ZERO_NUMERICALLY_UNRESOLVED","BLOCKED_PRIMARY_GAP_AUDIT","BLOCKED_BAND_IDENTITY_GUARD","BLOCKED_COMPATIBILITY","BLOCKED_RUNTIME","BLOCKED_SCOPE_EXPANSION"}

def fail(x): raise AssertionError(x)
def audit(seal=True):
    if hashlib.sha256((ROOT/"authoritative_contract.json").read_bytes()).hexdigest()!=SHA: fail("contract SHA")
    contract=json.loads((ROOT/"authoritative_contract.json").read_text())
    if contract["runtime"]["solver_tolerance"]!=1e-10 or contract["starting_refs"]["MePhC"]!="fe2ecd8ade61fcb6cd4d23a4b26c363c3dd04961": fail("contract expectations")
    for x in REQ:
        if not (ROOT/x).exists(): fail("missing "+x)
    if not any((ROOT/"logs").iterdir()): fail("logs")
    names=["contract_preflight","preflight","protected_digest_check","r10_inheritance","primary_gap_clarification","first_order_selection_rule","tangent_geometry_equivalence","tangent_raw_spectra","tangent_sensitivities","full_pattern_raw_spectra","full_pattern_c1","same_input_repeat_floor","representation_control","uniform_translation_floor","band_identity_guard","uncertainty_budget","mechanism_adjudication","change_scope","trilatt_hold","solver_execution"]
    J={n:json.loads((ROOT/(n+".json")).read_text()) for n in names}
    if J["r10_inheritance"]["terminal_state"]!="BLOCKED_FIRST_ORDER_MECHANISM_UNRESOLVED" or not J["r10_inheritance"]["immutable"]: fail("R10 inheritance")
    rule=J["first_order_selection_rule"]
    if rule["label"]!="NONDEGENERATE_ZERO_MEAN_FIRST_ORDER_SELECTION_RULE_DERIVED" or not rule["coefficient_sum_zero"] or "T^j V0 T^-j" not in rule["generator"]: fail("selection rule")
    raw=J["tangent_raw_spectra"]
    if raw["q_point"]!="q2" or raw["h_levels"]!=[0.0005,0.001] or raw["sites"]!=[0,1,2]: fail("tangent scope")
    full=J["full_pattern_raw_spectra"]
    if full["signed_levels"]!=[-0.002,-0.001,-0.0005,0.0,0.0005,0.001,0.002]: fail("full scope")
    resolutions=sorted(int(x) for x in full["resolutions"])
    if resolutions[:2]!=[80,96] or any(x>112 for x in resolutions) or resolutions.count(112)>1: fail("resolution policy")
    gap=J["primary_gap_clarification"]
    if not gap["global_as_primary_forbidden"]: fail("gap clarification")
    for row in gap["rows"]:
        if "global_minimum_coupled_sector_gap" not in row or "primary_band3_minimum_coupled_sector_gap" not in row or "primary_nearest_allowed_partner_band" not in row: fail("primary gap audit")
        if row["primary_gap_class"]!="NONDEGENERATE": fail("primary gap")
    solver=J["solver_execution"]
    if solver["triLatt_fresh_mpb_calls"]!=0 or solver["above_112_ran"] or solver["solver_tolerance_all_calls"]!=1e-10 or not solver["no_retry_hunting"]: fail("solver scope")
    for c in solver["fresh_solver_calls"]:
        if c["solver"]!="meep.mpb.ModeSolver" or c["solver_tolerance"]!=1e-10 or c["q_point"]!="q2" or c["response_bands"]!=[1,2,3,4,5,6]: fail("solver ledger")
    for r in resolutions:
        repeats=J["same_input_repeat_floor"][str(r)]
        if not all(repeats["exactly_three_repeats"].values()) or repeats["retry_hunting"]: fail("repeat schedule")
        if not J["tangent_geometry_equivalence"][str(r)]["all_pass"]: fail("tangent geometry")
    if not J["band_identity_guard"]["pass"]: fail("band identity")
    if not J["representation_control"][str(resolutions[-1])]["geometry_equivalent"]["equivalent"]: fail("representation")
    if not all(x["geometry_equivalent"] for x in J["uniform_translation_floor"].values()): fail("translation")
    unc=J["uncertainty_budget"]
    for key in ("tangent_components","direct_c1_components"):
        if not unc[key]: fail("uncertainty components")
    if J["change_scope"]["fresh_trilatt_solver_calls"]!=0 or J["change_scope"]["production_changes"]!=[] or J["change_scope"]["r12_authorized"]: fail("scope")
    if J["trilatt_hold"]["fresh_mpb_calls"]!=0: fail("TriLatt")
    mech=J["mechanism_adjudication"]
    if mech["scientific_terminal_state"] not in TERMINALS: fail("terminal")
    if seal:
        for x in ("artifact_manifest.json","integrity.json","completion.json"):
            if not (ROOT/x).exists(): fail("seal "+x)
        if json.loads((ROOT/"integrity.json").read_text())["contract_sha256"]!=SHA: fail("integrity")
        if json.loads((ROOT/"completion.json").read_text())["seal_status"]!="SEALED": fail("completion")
    return "PASS_R11_EVIDENCE_VALIDATOR"
if __name__=="__main__":
    try: print(audit("--preseal" not in sys.argv))
    except Exception as e: print("FAIL_R11_EVIDENCE_VALIDATOR:",e); raise SystemExit(1)
