from __future__ import annotations
import hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
SHA="9ae0c4262451827c7ae559ea9a635b2304316b0a880d462ee4b217241b56a219"
TERMINALS={"CLOSED_EXACT_DEGENERATE_FIRST_ORDER_SPLITTING_SUPPORTED","CLOSED_NONDEGENERATE_FIRST_ORDER_VANISHING_SUPPORTED","CLOSED_NEAR_DEGENERATE_FINITE_AMPLITUDE_CROSSOVER_SUPPORTED","CLOSED_FINITE_RESOLUTION_ODD_ARTIFACT_SUPPORTED","BLOCKED_FIRST_ORDER_MECHANISM_UNRESOLVED","BLOCKED_TRANSLATION_SECTOR_DIAGNOSTIC","BLOCKED_BAND_IDENTITY_GUARD","BLOCKED_COMPATIBILITY","BLOCKED_RUNTIME","BLOCKED_SCOPE_EXPANSION"}
REQ=["README.md","authoritative_contract.json","contract_preflight.json","preflight.json","protected_digest_check.json","r9_inheritance.json","primitive_translation_sector_method.md","primitive_translation_sector_data.json","a0_12band_spectrum.json","coupled_sector_gap_audit.json","geometry_controls.json","solver_execution.json","raw_q2_response_spectra.json","same_input_repeat_floor.json","uniform_translation_floor.json","representation_control.json","band_identity_guard.json","central_derivatives.json","c1_extrapolation.json","mechanism_adjudication.json","zero_mean_rule_interpretation.json","change_scope.json","trilatt_hold.json","test_coverage.csv","validation_report.md","known_limits.md","run_r10.py","validate_r10.py","validator_negative_fixtures.py"]
def fail(x): raise AssertionError(x)
def audit(seal=True):
    if hashlib.sha256((ROOT/"authoritative_contract.json").read_bytes()).hexdigest()!=SHA: fail("contract SHA")
    for x in REQ:
        if not (ROOT/x).exists(): fail("missing "+x)
    if not any((ROOT/"logs").iterdir()): fail("logs")
    J={x.removesuffix(".json"):json.loads((ROOT/x).read_text()) for x in ("contract_preflight.json","preflight.json","protected_digest_check.json","r9_inheritance.json","primitive_translation_sector_data.json","a0_12band_spectrum.json","coupled_sector_gap_audit.json","geometry_controls.json","solver_execution.json","raw_q2_response_spectra.json","same_input_repeat_floor.json","uniform_translation_floor.json","representation_control.json","band_identity_guard.json","central_derivatives.json","c1_extrapolation.json","mechanism_adjudication.json","zero_mean_rule_interpretation.json","change_scope.json","trilatt_hold.json")}
    if J["contract_preflight"]["contract_sha256"]!=SHA: fail("preflight SHA")
    inh=J["r9_inheritance"]
    if inh["terminal_state"]!="BLOCKED_ODD_RESPONSE_ORDER_UNRESOLVED" or inh["channel_count"]!=18 or inh["eligible_odd_channels"]!=1 or inh["linear_support_count"]!=1 or inh["cubic_support_count"]!=0 or inh["sole_linear_channel"]!=["q2",3] or not inh["immutable"]: fail("R9 inheritance")
    s=J["primitive_translation_sector_data"]
    if not all(s[x] for x in ("all_actual_eigenfields_retrieved","all_t3_controls_pass","all_gauge_controls_pass","all_repeatability_controls_pass")): fail("field controls")
    raw=J["raw_q2_response_spectra"]
    if raw["q_point"]!="q2" or raw["bands"]!=[1,2,3,4,5,6] or raw["signed_ladder"]!=[-0.01,-0.005,-0.0025,-0.00125,0.0,0.00125,0.0025,0.005,0.01]: fail("response scope")
    resolutions=sorted(int(x) for x in raw["resolutions"])
    if resolutions[:2]!=[48,64] or any(x>80 for x in resolutions) or resolutions.count(80)>1: fail("resolution policy")
    solver=J["solver_execution"]
    if solver["trilatt_fresh_solver_calls"]!=0 or solver["above_80_ran"] or not solver["no_retry_hunting"]: fail("solver scope")
    for call in solver["fresh_solver_calls"]:
        if call["solver"]!="meep.mpb.ModeSolver" or call["solver_tolerance"]!=1e-7 or call["q_point"]!="q2" or call["response_bands"]!=[1,2,3,4,5,6] or call["resolution"]>80: fail("ledger")
        if call["amplitude"] in (0.02,-0.02): fail("forbidden amplitude")
    for r in resolutions:
        if not J["same_input_repeat_floor"][str(r)]["exactly_two_repeats_A0"] or not J["same_input_repeat_floor"][str(r)]["exactly_two_repeats_A_plus_0.005"]: fail("repeat count")
    if not J["band_identity_guard"]["pass"]: fail("band identity")
    scope=J["change_scope"]
    if scope["production_changes"]!=[] or scope["fresh_trilatt_solver_calls"]!=0 or scope["r11_authorized"]: fail("scope")
    if J["trilatt_hold"]["fresh_mpb_solver_calls"]!=0: fail("TriLatt hold")
    if J["mechanism_adjudication"]["scientific_terminal_state"] not in TERMINALS: fail("terminal")
    if seal:
        for x in ("artifact_manifest.json","integrity.json","completion.json"):
            if not (ROOT/x).exists(): fail("seal "+x)
        if json.loads((ROOT/"integrity.json").read_text())["contract_sha256"]!=SHA: fail("integrity")
        if json.loads((ROOT/"completion.json").read_text())["seal_status"]!="SEALED": fail("completion")
    return "PASS_R10_EVIDENCE_VALIDATOR"
if __name__=="__main__":
    try: print(audit("--preseal" not in sys.argv))
    except Exception as e: print("FAIL_R10_EVIDENCE_VALIDATOR:",e); raise SystemExit(1)
