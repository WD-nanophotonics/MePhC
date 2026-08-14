from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MEPHC = ROOT.parents[2]
SHA = "8f5813f9e3c8aa1050ac990badf3398064287ad702750468d2677da303341ce0"
REQ = [
    "README.md", "authoritative_contract.json", "contract_preflight.json", "preflight.json", "protected_digest_check.json",
    "r12_inheritance.json", "perturbative_sector_structure.md", "perturbative_sector_structure.json",
    "origin_phase_definition.json", "origin_phase_geometry_controls.json", "raw_even_response_spectra.json",
    "even_response_by_phase.json", "phase_averaged_even_response.json", "quadratic_coefficient_fit.json",
    "per_phase_quadratic_diagnostic.json", "same_input_repeat_floor.json", "representation_control.json",
    "uniform_translation_even_floor.json", "band_identity_guard.json", "uncertainty_budget.json",
    "mechanism_adjudication.json", "solver_execution.json", "change_scope.json", "trilatt_hold.json",
    "test_coverage.csv", "validation_report.md", "known_limits.md", "run_r13.py", "validate_r13.py",
    "validator_negative_fixtures.py",
]
TERMINALS = {
    "CLOSED_QUADRATIC_EVEN_RESPONSE_SUPPORTED", "CLOSED_QUADRATIC_EVEN_ZERO_SUPPORTED",
    "BLOCKED_QUADRATIC_EVEN_NUMERICALLY_UNRESOLVED", "BLOCKED_PERTURBATIVE_SECTOR_AUDIT",
    "BLOCKED_BAND_IDENTITY_GUARD", "BLOCKED_COMPATIBILITY", "BLOCKED_RUNTIME", "BLOCKED_SCOPE_EXPANSION",
}


def fail(msg):
    raise AssertionError(msg)


def digest(path):
    rows = []
    for file in sorted(path.rglob("*")):
        if file.is_file():
            rows.append((file.relative_to(path).as_posix(), hashlib.sha256(file.read_bytes()).hexdigest()))
    payload = "\n".join(f"{p}:{h}" for p, h in rows).encode()
    return {"file_count": len(rows), "sha256": hashlib.sha256(payload).hexdigest(), "files": rows}


def audit(seal=True):
    if hashlib.sha256((ROOT / "authoritative_contract.json").read_bytes()).hexdigest() != SHA:
        fail("contract SHA")
    contract = json.loads((ROOT / "authoritative_contract.json").read_text())
    if contract["starting_refs"]["MePhC"] != "fb996f4be42676b49b9e166aa81eba9d31875a9b":
        fail("starting ref")
    for name in REQ:
        if not (ROOT / name).exists():
            fail("missing " + name)
    if not any((ROOT / "logs").iterdir()):
        fail("logs")
    pre = json.loads((ROOT / "preflight.json").read_text())
    if not pre["protected_paths_unchanged"] or pre["fresh_trilatt_solver_calls"] != 0:
        fail("preflight protection")
    protected = json.loads((ROOT / "protected_digest_check.json").read_text())
    for label, expected in protected["protected_r6_r12_directory_digests"].items():
        current = digest(MEPHC / f"docs/architecture/mephc_affine_architecture_{label}")
        if current["file_count"] != expected["file_count"] or current["sha256"] != expected["sha256"] or current["files"] != [tuple(x) for x in expected["files"]]:
            fail("protected digest " + label)
    inh = json.loads((ROOT / "r12_inheritance.json").read_text())
    if inh["terminal_state"] != "CLOSED_TRANSLATION_COVARIANT_FIRST_ORDER_ZERO_SUPPORTED" or not inh["immutable"]:
        fail("R12 inheritance")
    sector = json.loads((ROOT / "perturbative_sector_structure.json").read_text())
    if sector["sector_modulus"] != 3 or sector["cubic_coefficient_claimed"] or sector["labels"] != contract["perturbative_labels"]:
        fail("period-3 sector structure")
    phases = json.loads((ROOT / "origin_phase_definition.json").read_text())
    if phases["phases"] != [0.0, 0.25, 0.5, 0.75] or phases["amplitudes"] != [0.0025, 0.005, 0.01, 0.02] or phases["resolutions"] != [96, 112] or phases["phase_cherry_picking"]:
        fail("phase/amplitude scope")
    raw = json.loads((ROOT / "raw_even_response_spectra.json").read_text())
    if raw["q_point"] != "q2" or raw["bands"] != [1, 2, 3, 4, 5, 6] or set(raw["resolutions"]) != {"96", "112"}:
        fail("raw response scope")
    for res in ("96", "112"):
        if set(raw["resolutions"][res]) != {"0", "0.25", "0.5", "0.75"}:
            fail("missing phase")
        for phase in raw["resolutions"][res]:
            if set(raw["resolutions"][res][phase]) != {"0.0025", "0.005", "0.01", "0.02"}:
                fail("missing amplitude")
            if any(set(raw["resolutions"][res][phase][amp]) != {"plus", "minus"} for amp in raw["resolutions"][res][phase]):
                fail("missing signed response")
    solver = json.loads((ROOT / "solver_execution.json").read_text())
    if solver["fresh_solver_call_count"] != 92 or solver["resolutions_used"] != [96, 112] or solver["above_112_ran"] or solver["triLatt_fresh_mpb_calls"] != 0 or not solver["no_retry_hunting"]:
        fail("solver count/scope")
    primary = [x for x in solver["fresh_solver_calls"] if x["kind"].startswith("primary_")]
    controls = [x for x in solver["fresh_solver_calls"] if not x["kind"].startswith("primary_")]
    if len(primary) != 72 or len(controls) != 20:
        fail("primary/control call counts")
    for call in solver["fresh_solver_calls"]:
        if call["q_point"] != "q2" or call["resolution"] not in (96, 112) or call["solver_tolerance"] != 1e-10 or call["solver"] != "meep.mpb.ModeSolver" or call["polarization"] != "TE" or call["response_bands"] != [1, 2, 3, 4, 5, 6]:
            fail("solver ledger identity")
    repeats = json.loads((ROOT / "same_input_repeat_floor.json").read_text())
    for res in ("96", "112"):
        if set(repeats[res]) != {"A0", "minus_A_0.010", "plus_A_0.010"} or not all(x["exactly_two"] for x in repeats[res].values()):
            fail("repeat controls")
    reps = json.loads((ROOT / "representation_control.json").read_text())
    for res in ("96", "112"):
        if set(reps[res]) != {"A0", "plus_A_0.010"}:
            fail("representation controls")
        for item in reps[res].values():
            if not item["canonical_geometry"]["equivalent"] or not item["epsilon_identity"]:
                fail("representation equivalence")
            if len(item["spectral_difference"]) != 6:
                fail("representation bands")
    uniform = json.loads((ROOT / "uniform_translation_even_floor.json").read_text())
    if any(float(uniform[r]["delta"]) != 0.005 for r in ("96", "112")):
        fail("uniform translation delta")
    guard = json.loads((ROOT / "band_identity_guard.json").read_text())
    if not guard["pass"] or len(guard["rows"]) != 384 or any(not x["pass"] for x in guard["rows"]):
        fail("band identity")
    unc = json.loads((ROOT / "uncertainty_budget.json").read_text())
    needed = {"abs(c2_112-c2_96)", "leave_one_origin_phase_out_spread_112", "leave_one_amplitude_out_spread_112", "same_input_repeat_frequency_floor_over_Amin2", "representation_control_band3_difference_over_Amin2", "uniform_translation_K_floor", "phase_half_range_K_at_Amin"}
    if set(unc["components"]) != needed:
        fail("uncertainty components")
    fit = json.loads((ROOT / "quadratic_coefficient_fit.json").read_text())
    mech = json.loads((ROOT / "mechanism_adjudication.json").read_text())
    if mech["scientific_terminal_state"] not in TERMINALS or mech["cubic_nonzero_claimed"] or fit["112"]["c2"] == 0:
        fail("terminal/fit")
    if mech["scientific_terminal_state"] == "CLOSED_QUADRATIC_EVEN_RESPONSE_SUPPORTED":
        if abs(fit["112"]["c2"]) < 5 * unc["uncertainty"]:
            fail("nonzero c2 separation")
    scope = json.loads((ROOT / "change_scope.json").read_text())
    if scope["production_changes"] != [] or scope["fresh_trilatt_solver_calls"] != 0 or scope["r14_authorized"]:
        fail("scope")
    if seal:
        manifest = json.loads((ROOT / "artifact_manifest.json").read_text())
        integrity = json.loads((ROOT / "integrity.json").read_text())
        completion = json.loads((ROOT / "completion.json").read_text())
        if integrity["contract_sha256"] != SHA or integrity["payload_file_count"] != len(manifest["files"]):
            fail("integrity")
        if completion["seal_status"] != "SEALED" or completion["scientific_terminal_state"] != mech["scientific_terminal_state"]:
            fail("completion")
        for row in manifest["files"]:
            file = ROOT / row["path"]
            if not file.exists() or file.stat().st_size != row["size_bytes"] or hashlib.sha256(file.read_bytes()).hexdigest() != row["sha256"]:
                fail("manifest digest")
    return "PASS_R13_EVIDENCE_VALIDATOR"


if __name__ == "__main__":
    try:
        print(audit("--preseal" not in sys.argv))
    except Exception as exc:
        print("FAIL_R13_EVIDENCE_VALIDATOR:", exc)
        raise SystemExit(1)
