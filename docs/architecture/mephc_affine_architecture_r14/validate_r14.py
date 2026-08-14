from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
MEPHC = ROOT.parents[2]
CONTRACT_SHA = "06049090c64cdfe362f6d694d748696b60d943959f88f9a4267fb4b767e8960a"
REFS = {
    "MePhC": "dbe2225232d34781bd40b6c2686206095948d3a0",
    "MePhC-SqrLatt": "da39f45de67e72b5ec79d9b04202af6d9c212380",
    "MePhC-TriLatt": "45891d075d3d5a00d2ee07f8719a94d32e0ae98b",
}
RES = [96, 112]
PHASES = ["0", "0.25", "0.5", "0.75"]
H = ["0.005", "0.01", "0.02"]
SIGNS = ["plus", "minus"]
TERMINALS = {
    "CLOSED_TRANSLATION_COVARIANT_QUADRATIC_NONZERO_SUPPORTED",
    "BLOCKED_TRANSLATION_COVARIANT_QUADRATIC_UNRESOLVED",
    "BLOCKED_QUADRATIC_HESSIAN_SYMMETRY_INCONSISTENCY",
    "BLOCKED_QUADRATIC_CANONICALIZATION",
    "BLOCKED_QUADRATIC_DISCRETE_COVARIANCE",
    "BLOCKED_BAND_IDENTITY_GUARD",
    "BLOCKED_COMPATIBILITY",
    "BLOCKED_RUNTIME",
    "BLOCKED_SCOPE_EXPANSION",
}
REQUIRED = {
    "README.md", "authoritative_contract.json", "contract_preflight.json", "preflight.json",
    "protected_digest_check.json", "r13_inheritance.json", "hessian_symmetry_derivation.md",
    "hessian_symmetry_derivation.json", "canonical_pair_definition.json", "canonical_pair_geometry.json",
    "canonical_pair_epsilon.json", "relative_pair_raw_spectra.json", "relative_pair_lambda_by_phase.json",
    "phase_averaged_lambda.json", "lambda_fit.json", "hessian_component_raw_spectra.json",
    "hessian_component_estimates.json", "uniform_translation_null.json", "same_input_repeat_floor.json",
    "representation_control.json", "band_identity_guard.json", "uncertainty_budget.json",
    "mechanism_adjudication.json", "solver_execution.json", "change_scope.json", "trilatt_hold.json",
    "test_coverage.csv", "validation_report.md", "known_limits.md", "run_r14.py", "validate_r14.py", "validator_negative_fixtures.py",
}
COMPONENTS = {
    "abs(lambda_112-lambda_96)",
    "leave_one_origin_phase_out_lambda_spread_112",
    "leave_one_h_out_lambda_spread_112",
    "same_input_repeat_band3_frequency_floor_over_hmin2",
    "representation_control_band3_frequency_difference_over_hmin2",
    "max_uniform_translation_K_over_phases_112",
    "phase_half_range_L_at_hmin_112",
    "phase_mean_abs_row_sum_fd_112",
    "phase_mean_abs_lambda_components_minus_pair_hstar_112",
}


def load(name: str):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def fail(message: str) -> None:
    raise AssertionError(message)


def eq(actual, expected, label: str) -> None:
    if actual != expected:
        fail(f"{label}: {actual!r} != {expected!r}")


def close(actual, expected, label: str, tol: float = 1e-10) -> None:
    if not math.isclose(float(actual), float(expected), rel_tol=tol, abs_tol=tol):
        fail(f"{label}: {actual!r} != {expected!r}")


def git_ref(path: Path) -> str:
    return subprocess.check_output(["git", "-C", str(path), "ls-remote", "origin", "refs/heads/main"], text=True).split()[0]


def check_contract(contract: dict) -> None:
    actual = hashlib.sha256((ROOT / "authoritative_contract.json").read_bytes()).hexdigest()
    eq(actual, CONTRACT_SHA, "contract SHA")
    eq(contract["starting_refs"], REFS, "starting refs")
    eq(contract["resolution_plan"]["exact"], RES, "resolutions")
    eq(contract["resolution_plan"]["above_112_forbidden"], True, "resolution ceiling")
    eq(contract["origin_phases"]["grid_cell_fractions"], [0.0, 0.25, 0.5, 0.75], "origin phases")
    eq(contract["relative_pair"]["h_levels"], [0.005, 0.01, 0.02], "h levels")
    eq(contract["relative_pair"]["cyclic_variants"], [[1, -1, 0], [0, 1, -1], [-1, 0, 1]], "cyclic variants")
    eq(contract["relative_pair"]["canonical_anchor"], [1, -1, 0], "canonical anchor")
    close(contract["relative_pair"]["typed_geometry_tolerance"], 1e-10, "geometry tolerance")
    close(contract["relative_pair"]["epsilon_tolerance"], 1e-12, "epsilon tolerance")
    eq(contract["benchmark"]["q2"], [-0.09, 0.14], "q2")
    eq(contract["benchmark"]["bands"], [1, 2, 3, 4, 5, 6], "bands")
    eq(contract["benchmark"]["primary_band"], 3, "primary band")
    close(sum(contract["benchmark"]["d"]), 0.0, "d sum", 1e-12)
    close(sum(x * x for x in contract["benchmark"]["d"]), 1.5, "d norm", 1e-12)
    eq(contract["runtime"]["solver"], "meep.mpb.ModeSolver", "solver")
    close(contract["runtime"]["solver_tolerance"], 1e-10, "solver tolerance")
    eq(contract["delivery"]["completion_gmail_required"], False, "completion email")
    eq(contract["delivery"]["r15_authorized"], False, "R15 authorization")
    eq(contract["hessian_theory"]["form"], "H=[[a,b,b],[b,a,b],[b,b,a]]", "H form")
    eq(contract["hessian_theory"]["uniform_translation_null"], "a+2b=0", "uniform null")
    eq(contract["hessian_theory"]["zero_mean_eigenvalue"], "lambda=a-b", "lambda definition")
    eq(contract["hessian_crosscheck"]["h_star"], 0.01, "h star")
    eq(len(contract["scientific_terminal_states"]), 9, "terminal count")
    if any("QUADRATIC_ZERO_SUPPORTED" in x and "NONZERO" not in x for x in contract["scientific_terminal_states"]):
        fail("forbidden quadratic-zero terminal")


def check_preflight(contract: dict) -> None:
    pre = load("contract_preflight.json")
    eq(pre["contract_sha256"], CONTRACT_SHA, "preflight contract SHA")
    eq(pre["starting_refs"], REFS, "preflight refs")
    eq(pre["resolution_plan"]["exact"], RES, "preflight resolutions")
    eq(pre["call_count_expected"], 120, "expected call count")
    eq(load("preflight.json")["contract_sha256"], CONTRACT_SHA, "full preflight contract SHA")
    protected = load("protected_digest_check.json")
    eq(protected["verified"], True, "protected paths")
    eq(protected.get("inherited_validators", {}).get("r12"), "PASS_R12_EVIDENCE_VALIDATOR", "R12 validator")
    eq(protected.get("inherited_validators", {}).get("r13"), "PASS_R13_EVIDENCE_VALIDATOR", "R13 validator")
    inh = load("r13_inheritance.json")
    eq(inh["terminal_state"], "CLOSED_QUADRATIC_EVEN_ZERO_SUPPORTED", "R13 terminal")
    close(inh["c2_96"], -0.45640248675509176, "R13 c2_96")
    close(inh["c2_112"], -0.3436627735984702, "R13 c2_112")
    close(inh["uncertainty"], 3.298360946693002, "R13 uncertainty")
    eq(load("trilatt_hold.json")["fresh_mpb_calls"], 0, "TriLatt hold")


def check_geometry() -> None:
    definition = load("canonical_pair_definition.json")
    eq(definition["vectors"], [[1.0, -1.0, 0.0], [0.0, 1.0, -1.0], [-1.0, 0.0, 1.0]], "pair vectors")
    eq(definition["anchor"], [1.0, -1.0, 0.0], "pair anchor")
    eq(definition["h_levels"], [0.005, 0.01, 0.02], "pair definition h")
    geom, eps = load("canonical_pair_geometry.json"), load("canonical_pair_epsilon.json")
    for res in map(str, RES):
        for phase in PHASES:
            for h in H:
                for sign in SIGNS:
                    row = geom[res][phase][h][sign]
                    if not row["geometry_pass"] or not row["epsilon_covariance_pass"]:
                        fail(f"canonical covariance failed: {res}/{phase}/{h}/{sign}")
                    eq(eps[res][phase][h][sign]["epsilon_covariance_pass"], True, "epsilon covariance")


def check_spectra() -> None:
    raw = load("relative_pair_raw_spectra.json")
    eq(raw["q_point"], "q2", "raw q point")
    eq(raw["bands"], [1, 2, 3, 4, 5, 6], "raw bands")
    for res in map(str, RES):
        eq(sorted(raw["resolutions"][res]), PHASES, f"raw phases {res}")
        for phase in PHASES:
            eq(sorted(raw["resolutions"][res][phase]), H, f"raw h {res}/{phase}")
            for h in H:
                eq(sorted(raw["resolutions"][res][phase][h]), sorted(SIGNS), f"raw signs {res}/{phase}/{h}")
                for sign in SIGNS:
                    eq(len(raw["resolutions"][res][phase][h][sign]), 6, "spectrum band count")
    fit = load("lambda_fit.json")
    eq(sorted(fit["resolutions"]), ["112", "96"], "fit resolutions")
    for res in map(str, RES):
        for key in ("lambda", "mu", "max_abs_residual"):
            if not math.isfinite(fit["resolutions"][res][key]): fail(f"nonfinite fit {res}/{key}")
    close(fit["c2_field"]["96"], 0.75 * fit["resolutions"]["96"]["lambda"], "c2 96")
    close(fit["c2_field"]["112"], 0.75 * fit["resolutions"]["112"]["lambda"], "c2 112")
    avg, by_phase = load("phase_averaged_lambda.json"), load("relative_pair_lambda_by_phase.json")
    for res in map(str, RES):
        for phase in PHASES:
            for h in H:
                if not math.isfinite(by_phase[res][phase][h]["L"][2]): fail("nonfinite L")
        for h in H:
            eq(len(avg[res][h]["phase_values_L_band3"]), 4, "phase average coverage")


def check_hessian() -> None:
    data = load("hessian_component_estimates.json")["resolutions"]
    eq(sorted(data), ["112", "96"], "Hessian resolutions")
    for res in map(str, RES):
        eq(len(data[res]), 4, f"Hessian phase count {res}")
        for row in data[res]:
            for key in ("a_fd_band3", "b_fd_band3", "row_sum_fd_band3", "lambda_components_band3", "lambda_pair_hstar_band3", "lambda_component_minus_pair"):
                if not math.isfinite(row[key]): fail(f"nonfinite Hessian {res}/{key}")
    raw = load("hessian_component_raw_spectra.json")
    for res in map(str, RES):
        eq(sorted(raw[res]["diagonal"]), PHASES, "diagonal phases")
        eq(sorted(raw[res]["mixed"]), PHASES, "mixed phases")
    theory = load("hessian_symmetry_derivation.json")
    eq(theory["H_form"], "[[a,b,b],[b,a,b],[b,b,a]]", "derived H form")
    eq(theory["pair_vector"], [1, -1, 0], "derived pair vector")
    close(theory["d_sum"], 0.0, "derived d sum", 1e-12)
    close(theory["d_norm_squared"], 1.5, "derived d norm", 1e-12)


def check_controls_and_guard() -> None:
    uniform = load("uniform_translation_null.json")
    for res in map(str, RES):
        eq(sorted(uniform[res]), PHASES, "uniform phase coverage")
        for phase in PHASES: eq(sorted(uniform[res][phase]), sorted(SIGNS), "uniform sign coverage")
    repeats = load("same_input_repeat_floor.json")
    for res in map(str, RES):
        eq(sorted(repeats[res]), ["baseline_A0", "pair_minus_hstar", "pair_plus_hstar"], "repeat cases")
        for item in repeats[res].values(): eq(item["exactly_two_additional"], True, "repeat count")
    controls = load("representation_control.json")
    for res in map(str, RES):
        eq(sorted(controls[res]), ["pair_plus_hstar", "single_e0_plus_hstar"], "representation controls")
        for item in controls[res].values():
            eq(item["canonical_geometry"]["equivalent"], True, "representation geometry")
            eq(item["epsilon_identity"], True, "representation epsilon")
            eq(len(item["spectral_difference"]), 6, "representation spectrum")
    guard = load("band_identity_guard.json")
    eq(guard["pass"], True, "band identity")
    eq(len(guard["rows"]), 672, "band guard row count")
    if any(not row["pass"] for row in guard["rows"]): fail("band identity failure")


def check_ledger() -> None:
    data = load("solver_execution.json")
    eq(data["fresh_solver_call_count"], 120, "fresh solver count")
    eq(len(data["fresh_solver_calls"]), 120, "ledger rows")
    eq(data["resolutions_used"], RES, "ledger resolutions")
    eq(data["above_112_ran"], False, "resolution ceiling")
    eq(data["triLatt_fresh_mpb_calls"], 0, "Tri solver count")
    eq({k: data[k] for k in ("primary_pair_call_count", "hessian_component_call_count", "uniform_translation_call_count", "repeat_call_count", "representation_call_count")}, {"primary_pair_call_count": 56, "hessian_component_call_count": 32, "uniform_translation_call_count": 16, "repeat_call_count": 12, "representation_call_count": 4}, "ledger category counts")
    for i, row in enumerate(data["fresh_solver_calls"], 1):
        eq(row["call_index"], i, "call index")
        eq(row["q_point"], "q2", "ledger q point")
        eq(row["q_fractional"], [-0.09, 0.14], "ledger q")
        eq(row["response_bands"], [1, 2, 3, 4, 5, 6], "ledger bands")
        eq(row["polarization"], "TE", "ledger polarization")
        eq(row["solver"], "meep.mpb.ModeSolver", "ledger solver")
        close(row["solver_tolerance"], 1e-10, "ledger tolerance")
        if row["resolution"] not in RES: fail("ledger resolution")
        if row["kind"] == "primary_relative_pair" and (row["h"] not in [0.005, 0.01, 0.02] or row["sign"] not in SIGNS): fail("primary ledger fields")
    eq(data["repeat_convention"], "two_additional_calls_per_case", "repeat convention")


def check_adjudication() -> str:
    u = load("uncertainty_budget.json")
    eq(set(u["lambda_components"]), COMPONENTS, "uncertainty components")
    close(u["c2_uncertainty"], 0.75 * u["lambda_uncertainty"], "c2 uncertainty")
    m = load("mechanism_adjudication.json")
    terminal = m["scientific_terminal_state"]
    if terminal not in TERMINALS: fail(f"invalid terminal {terminal}")
    if "QUADRATIC_ZERO_SUPPORTED" in terminal and "NONZERO" not in terminal: fail("forbidden zero terminal")
    eq(m["cubic_nonzero_claimed"], False, "cubic claim")
    eq(m["r13_medium_K_used_as_pass_criterion"], False, "R13 K misuse")
    if terminal == "CLOSED_TRANSLATION_COVARIANT_QUADRATIC_NONZERO_SUPPORTED":
        if abs(m["primary_lambda_112"]) < 5 * u["lambda_uncertainty"]: fail("nonzero closure below uncertainty gate")
    else:
        if terminal != "BLOCKED_TRANSLATION_COVARIANT_QUADRATIC_UNRESOLVED" and m["canonical_gates"] and m["hessian_crosscheck_pass"]:
            fail("unexpected blocked terminal")
    return terminal


def main() -> None:
    contract = load("authoritative_contract.json")
    missing = sorted(REQUIRED - {p.name for p in ROOT.iterdir() if p.is_file()})
    if missing or not (ROOT / "logs" / "mpb_stdout.log").is_file(): fail(f"missing R14 artifacts: {missing}")
    check_contract(contract)
    check_preflight(contract)
    check_geometry()
    check_spectra()
    check_hessian()
    check_controls_and_guard()
    check_ledger()
    terminal = check_adjudication()
    print(json.dumps({"validator": "r14", "status": "PASS", "terminal_state": terminal, "contract_sha256": CONTRACT_SHA}, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (AssertionError, KeyError, IndexError, ValueError) as exc:
        print(f"R14_VALIDATION_FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
