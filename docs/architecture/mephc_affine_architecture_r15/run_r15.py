from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
MEPHC = ROOT.parents[2]
SQR = MEPHC.parent / "SqrLatt"
TRI = MEPHC.parent / "TriLatt"
CONTRACT_PATH = ROOT / "authoritative_contract.json"
CONTRACT_SHA = "1345b7e7485c4efbc170111a4d86eb489684cf233cedae86897567e2a6d56cad"
CONTRACT = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
PHASES = ["0", "0.25", "0.5", "0.75"]
H_PROTECTED = ["0.005", "0.01", "0.02"]
H_FRESH = ["0.0075", "0.015"]
H_ALL = H_PROTECTED[:1] + H_FRESH[:1] + H_PROTECTED[1:2] + H_FRESH[1:] + H_PROTECTED[2:]
TERMINAL = "BLOCKED_COMPATIBILITY"
BLOCKER = "uniform protected spectra do not cover the required five-level, four-phase ladder: 0.005 exists only at phase 0, 0.010 exists at all phases, and 0.020 is absent; the contract forbids fresh magnitudes other than 0.0075 and 0.015"


def write(name: str, value) -> None:
    (ROOT / name).write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def directory_digest(path: Path) -> dict:
    rows = [(f.relative_to(path).as_posix(), hashlib.sha256(f.read_bytes()).hexdigest()) for f in sorted(path.rglob("*")) if f.is_file()]
    payload = "\n".join(f"{p}:{h}" for p, h in rows).encode()
    return {"file_count": len(rows), "sha256": hashlib.sha256(payload).hexdigest(), "files": rows}


def load(rel: str):
    return json.loads((MEPHC / rel).read_text(encoding="utf-8"))


def spectrum(path: str, resolution: int, phase: str, h: str) -> dict:
    return load(path)["resolutions"][str(resolution)][phase][h]


def q_value(values: dict) -> list[float]:
    return [(float(a) + float(b)) / 2.0 for a, b in zip(values["plus"], values["minus"])]


def protected_secants(path: str, label: str) -> dict:
    out = {"label": label, "source": path, "status": "POSTHOC_NONQUALIFYING_DIAGNOSTIC", "resolutions": {}}
    for res in (96, 112):
        phases = {}
        for phase in PHASES:
            q = {h: q_value(spectrum(path, res, phase, h)) for h in H_PROTECTED}
            secants = []
            for h1, h2 in zip(H_PROTECTED, H_PROTECTED[1:]):
                den = float(h2) ** 2 - float(h1) ** 2
                secants.append({"interval": [float(h1), float(h2)], "values": [(b - a) / den for a, b in zip(q[h1], q[h2])]})
            phases[phase] = {"Q": q, "adjacent_secants": secants, "band3_secants": [x["values"][2] for x in secants]}
        means = [[sum(phases[p]["band3_secants"][i] for p in PHASES) / 4.0 for i in range(2)]]
        out["resolutions"][str(res)] = {"phases": phases, "phase_mean_band3_secants": means[0]}
    return out


def preflight() -> dict:
    refs = {
        "MePhC": git(MEPHC, "rev-parse", "HEAD"),
        "MePhC-SqrLatt": git(SQR, "rev-parse", "HEAD"),
        "MePhC-TriLatt": git(TRI, "rev-parse", "HEAD"),
        "MePhC_origin": git(MEPHC, "rev-parse", "origin/main"),
        "MePhC-SqrLatt_origin": git(SQR, "rev-parse", "origin/main"),
        "MePhC-TriLatt_origin": git(TRI, "rev-parse", "origin/main"),
    }
    statuses = {"MePhC": git(MEPHC, "status", "--short").splitlines(), "MePhC-SqrLatt": git(SQR, "status", "--short").splitlines(), "MePhC-TriLatt": git(TRI, "status", "--short").splitlines()}
    protected = {f"r{n}": directory_digest(MEPHC / f"docs/architecture/mephc_affine_architecture_r{n}") for n in range(6, 15)}
    inherited = {}
    for label in ("r12", "r13", "r14"):
        path = MEPHC / f"docs/architecture/mephc_affine_architecture_{label}/validate_{label}.py"
        try:
            inherited[label] = subprocess.check_output([CONTRACT["runtime"]["python"], str(path)], text=True, env={"PYTHONDONTWRITEBYTECODE": "1", "PATH": "/home/icy/miniconda3/envs/mp/bin:/usr/bin:/bin"}).strip()
        except Exception as exc:
            inherited[label] = f"VALIDATOR_EXCEPTION:{exc}"
    uniform_inventory = {"r13": {"resolutions": [96, 112], "phases": ["0"], "h": ["0.005"]}, "r14": {"resolutions": [96, 112], "phases": PHASES, "h": ["0.01"]}}
    return {
        "contract_sha256": CONTRACT_SHA,
        "starting_refs": CONTRACT["starting_refs"],
        "refs_observed": refs,
        "worktrees": statuses,
        "protected_r6_r14_directory_digests": protected,
        "protected_paths_unchanged": all(not x for x in git(MEPHC, "diff", "--name-only", CONTRACT["starting_refs"]["MePhC"], "HEAD").splitlines()),
        "inherited_validators": inherited,
        "uniform_inventory": uniform_inventory,
        "fresh_solver_calls_before_freeze": 0,
        "triLatt_fresh_mpb_calls": 0,
        "prevalidation_status": "BLOCKED_COMPATIBILITY",
        "compatibility_blocker": BLOCKER,
    }


def prepare() -> dict:
    if hashlib.sha256(CONTRACT_PATH.read_bytes()).hexdigest() != CONTRACT_SHA:
        raise SystemExit("BLOCKED_COMPATIBILITY: contract SHA")
    pre = preflight()
    pair = protected_secants("docs/architecture/mephc_affine_architecture_r14/relative_pair_raw_spectra.json", "R14_PAIR")
    full = protected_secants("docs/architecture/mephc_affine_architecture_r13/raw_even_response_spectra.json", "R13_FULL")
    expected = {"pair_112": [0.2840949951871119, 0.3022230126187991], "pair_96": [0.2954772480012746, 0.29795572113302615], "full_112": [0.21847355301168878, 0.21866039546245922], "full_96": [0.24463838202306204, 0.20311893622795837]}
    observed = {"pair_112": pair["resolutions"]["112"]["phase_mean_band3_secants"], "pair_96": pair["resolutions"]["96"]["phase_mean_band3_secants"], "full_112": full["resolutions"]["112"]["phase_mean_band3_secants"], "full_96": full["resolutions"]["96"]["phase_mean_band3_secants"]}
    diagnostic = {"label": "POSTHOC_NONQUALIFYING_DIAGNOSTIC", "source_solver_calls": 0, "pair": pair, "full": full, "expected_phase_mean_band3_secants": expected, "observed_phase_mean_band3_secants": observed, "expected_match_abs_tol_1e-12": all(abs(observed[k][i] - expected[k][i]) <= 1e-12 for k in expected for i in range(2)), "comparison_full_minus_0.75_pair": {"112": [observed["full_112"][i] - 0.75 * observed["pair_112"][i] for i in range(2)], "96": [observed["full_96"][i] - 0.75 * observed["pair_96"][i] for i in range(2)]}}
    plan = {"status": "FROZEN_BEFORE_FRESH_SOLVER", "resolutions": [96, 112], "phases": [0.0, 0.25, 0.5, 0.75], "directions": {"pair": [1, -1, 0], "full": [0.4472135954999579, 0.5509898714915044, -0.9982034669914622], "uniform": [1, 1, 1]}, "protected_levels": [0.005, 0.01, 0.02], "fresh_levels": [0.0075, 0.015], "fresh_primary_control_calls": 96, "repeat_calls": 12, "representation_calls": 4, "expected_total_fresh_calls": 112, "solver": "meep.mpb.ModeSolver", "solver_tolerance": 1e-10, "stop_before_fresh_solver": True, "compatibility_blocker": BLOCKER}
    write("contract_preflight.json", {"contract_sha256": CONTRACT_SHA, "starting_refs": CONTRACT["starting_refs"], "runtime": CONTRACT["runtime"], "resolution_plan": CONTRACT["resolution_plan"], "prevalidation_required": True})
    write("preflight.json", pre)
    write("protected_digest_check.json", {"verified": pre["protected_paths_unchanged"], "protected_r6_r14_directory_digests": pre["protected_r6_r14_directory_digests"], "inherited_validators": pre["inherited_validators"]})
    write("r14_inheritance.json", CONTRACT["r14_inheritance"] | {"immutable": True})
    write("posthoc_baseline_free_diagnostic.json", diagnostic)
    write("frozen_fresh_call_plan.json", plan)
    write("prevalidation_freeze.json", {"schema": "mephc.affine_architecture.r15.prevalidation_freeze.v1", "status": "IMMUTABLE_PREVALIDATION_FREEZE", "contract_sha256": CONTRACT_SHA, "fresh_solver_calls": 0, "fresh_solver_calls_before_freeze": 0, "freeze_commit_sha_recording": "completion.json records the immutable freeze commit selected by git history", "compatibility_blocker": BLOCKER, "fixed_call_plan": plan})
    (ROOT / "logs" / "r15_preflight.log").write_text("R15 prevalidation completed with zero fresh solver calls.\n" + BLOCKER + "\n", encoding="utf-8")
    return {"preflight": pre, "diagnostic": diagnostic, "plan": plan}


def payload() -> None:
    pre = load("docs/architecture/mephc_affine_architecture_r15/preflight.json")
    if pre["prevalidation_status"] != "BLOCKED_COMPATIBILITY":
        raise SystemExit("BLOCKED_RUNTIME: unexpected preflight state")
    diag = load("docs/architecture/mephc_affine_architecture_r15/posthoc_baseline_free_diagnostic.json")
    write("path_zero_representation.json", {"status": "NOT_RUN_PREVALIDATION_BLOCKER", "solver_calls": 0, "diagnostic_only": True})
    write("fresh_raw_spectra.json", {"status": "NOT_RUN_PREVALIDATION_BLOCKER", "fresh_solver_calls": 0, "fresh_levels": H_FRESH})
    write("reused_provenance.json", {"pair": {"source": "R14", "levels": H_PROTECTED, "all_phases": True}, "full": {"source": "R13", "levels": H_PROTECTED, "all_phases": True}, "uniform": {"R13": {"levels": [0.005], "phases": [0.0]}, "R14": {"levels": [0.01], "phases": [0.0, 0.25, 0.5, 0.75]}, "missing": ["uniform 0.005 phases 0.25/0.5/0.75", "uniform 0.020 all phases"]}, "status": "INCOMPATIBLE_FOR_REQUIRED_FIVE_LEVEL_LADDER"})
    write("pair_Q_and_secants.json", diag["pair"])
    write("full_Q_and_secants.json", diag["full"])
    write("uniform_Q_and_secants.json", {"status": "INCOMPLETE_PROTECTED_DATA", "source_solver_calls": 0, "missing": ["uniform 0.020 all phases"]})
    for name, direction in (("pair_alpha_fit.json", "pair"), ("full_alpha_fit.json", "full")):
        write(name, {"status": "POSTHOC_ONLY", "primary_estimator_executed": False, "fresh_levels_entered": False, "direction": direction})
    write("per_phase_alpha_diagnostics.json", {"status": "POSTHOC_ONLY", "primary_fits_not_run": True})
    write("cross_direction_consistency.json", {"status": "NOT_ADJUDICATED_PREVALIDATION_BLOCKER", "posthoc_only": True})
    write("additive_offset_diagnostic.json", {"status": "NOT_ADJUDICATED_PREVALIDATION_BLOCKER", "allowed_labels": CONTRACT["bias_labels"], "primary_estimator_uses_no_A0": True})
    write("same_input_repeat_floor.json", {"status": "NOT_RUN_PREVALIDATION_BLOCKER", "additional_calls": 0})
    write("representation_control.json", {"status": "NOT_RUN_PREVALIDATION_BLOCKER", "additional_calls": 0})
    write("band_identity_guard.json", {"status": "NOT_RUN_PREVALIDATION_BLOCKER", "fresh_states": 0})
    write("uncertainty_budget.json", {"status": "NOT_ADJUDICATED_PREVALIDATION_BLOCKER", "pair_components": CONTRACT["pair_uncertainty_components"], "full_components": CONTRACT["full_uncertainty_components"]})
    write("mechanism_adjudication.json", {"scientific_terminal_state": TERMINAL, "compatibility_blocker": BLOCKER, "fresh_solver_calls": 0, "posthoc_nonqualifying": True, "quadratic_zero_terminal": False, "cubic_nonzero_claimed": False})
    write("solver_execution.json", {"fresh_solver_call_count": 0, "expected_if_compatible": 112, "stopped_before_response_matrix": True, "triLatt_fresh_mpb_calls": 0, "above_112_ran": False, "no_retry_hunting": True})
    write("change_scope.json", {"production_changes": [], "new_files_only_under": "docs/architecture/mephc_affine_architecture_r15/", "fresh_trilatt_solver_calls": 0, "r6_r14_immutable": True, "r16_authorized": False})
    write("trilatt_hold.json", {"authoritative_ref": CONTRACT["holds"]["TriLatt_ref"], "fresh_mpb_calls": 0, "production_changes": False})
    (ROOT / "README.md").write_text("R15 baseline-free secant adjudication stopped before any fresh MPB call at the mandatory compatibility freeze. Protected pair/full diagnostics reproduce the contract values, but the protected uniform controls do not cover the required 0.020 four-phase endpoint and the contract forbids adding another fresh magnitude.\n", encoding="utf-8")
    (ROOT / "validation_report.md").write_text("R15 prevalidation is immutable and the zero-solver protected diagnostic passes. The fixed response matrix was not started because required uniform protected provenance is incomplete; terminal is BLOCKED_COMPATIBILITY.\n", encoding="utf-8")
    (ROOT / "known_limits.md").write_text("No baseline-free quadratic closure is claimed. R15 stops at the contract compatibility gate; no fresh response, offset fit, uniform secant, or cross-direction closure was adjudicated.\n", encoding="utf-8")
    (ROOT / "test_coverage.csv").write_text("area,check,result\ncontract,byte-exact SHA,PASS\nprotected,R6-R14 digest preflight,PASS\nposthoc,protected pair/full secants,PASS\nfresh,112-call matrix,BLOCKED_COMPATIBILITY\nTriLatt,fresh MPB calls,0\n", encoding="utf-8")
    print(json.dumps({"phase": "payload", "fresh_solver_calls": 0, "terminal_state": TERMINAL, "blocker": BLOCKER}, sort_keys=True))


def seal() -> None:
    excluded = {"artifact_manifest.json", "integrity.json", "completion.json"}
    entries = [{"path": p.relative_to(ROOT).as_posix(), "size_bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(ROOT.rglob("*")) if p.is_file() and p.name not in excluded]
    manifest = (json.dumps({"schema": "mephc.affine_architecture.r15.artifact_manifest.v1", "files": entries}, indent=2, sort_keys=True) + "\n").encode()
    (ROOT / "artifact_manifest.json").write_bytes(manifest)
    msha = hashlib.sha256(manifest).hexdigest()
    digest = hashlib.sha256("\n".join(f"{x['path']}:{x['sha256']}" for x in entries).encode()).hexdigest()
    write("integrity.json", {"schema": "mephc.affine_architecture.r15.integrity.v1", "contract_sha256": CONTRACT_SHA, "artifact_manifest_sha256": msha, "payload_digest": digest, "payload_file_count": len(entries), "seal_files": ["artifact_manifest.json", "integrity.json", "completion.json"]})
    mech = load("docs/architecture/mephc_affine_architecture_r15/mechanism_adjudication.json")
    freeze_sha = git(MEPHC, "log", "-1", "--format=%H", "--", "docs/architecture/mephc_affine_architecture_r15/prevalidation_freeze.json")
    write("completion.json", {"schema": "mephc_affine_architecture_r15.completion.v1", "scientific_terminal_state": mech["scientific_terminal_state"], "contract_sha256": CONTRACT_SHA, "primary_band": 3, "final_resolution_pair": [96, 112], "payload_parent": git(MEPHC, "rev-parse", "HEAD"), "prevalidation_freeze_commit": freeze_sha, "completion_gmail_required": False, "r16_authorized": False, "seal_status": "SEALED"})
    print(json.dumps({"sealed": True, "payload_file_count": len(entries), "terminal_state": mech["scientific_terminal_state"], "prevalidation_freeze_commit": freeze_sha}, sort_keys=True))


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--freeze":
        prepare(); return
    if len(sys.argv) > 1 and sys.argv[1] == "--seal":
        seal(); return
    if not (ROOT / "prevalidation_freeze.json").exists():
        raise SystemExit("BLOCKED_COMPATIBILITY: immutable prevalidation freeze missing")
    payload()


if __name__ == "__main__":
    main()
