from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MEPHC = ROOT.parents[2]
SHA = "cfd2bf0dee4d7c186e2c428cad3620ececdc7bde256b00dd97de33f5dcf34343"
REQ = [
    "README.md", "authoritative_contract.json", "contract_preflight.json", "preflight.json",
    "protected_digest_check.json", "r11_inheritance.json", "continuum_selection_rule_inheritance.json",
    "canonical_anchor_definition.json", "canonical_tangent_geometry.json", "canonical_tangent_epsilon.json",
    "canonical_tangent_spectra.json", "canonical_tangent_sensitivities.json",
    "legacy_vs_canonical_localization.json", "representation_artifact_adjudication.json",
    "origin_phase_definition.json", "origin_phase_geometry_controls.json", "origin_phase_raw_spectra.json",
    "origin_phase_derivatives.json", "origin_phase_c1.json", "same_input_repeat_floor.json",
    "representation_control.json", "uniform_translation_control.json", "band_identity_guard.json",
    "uncertainty_budget.json", "mechanism_adjudication.json", "change_scope.json", "trilatt_hold.json",
    "solver_execution.json", "test_coverage.csv", "validation_report.md", "known_limits.md",
    "run_r12.py", "validate_r12.py", "validator_negative_fixtures.py",
]
TERMINALS = {
    "CLOSED_TRANSLATION_COVARIANT_FIRST_ORDER_ZERO_SUPPORTED",
    "CLOSED_SELECTION_RULE_WITH_REPRESENTATION_ARTIFACT_IDENTIFIED",
    "BLOCKED_TRANSLATION_COVARIANT_CANONICALIZATION",
    "BLOCKED_DISCRETE_TRANSLATION_COVARIANCE",
    "BLOCKED_SELECTION_RULE_NUMERICAL_INCONSISTENCY",
    "BLOCKED_ORIGIN_PHASE_ESTIMATOR_UNRESOLVED",
    "BLOCKED_BAND_IDENTITY_GUARD",
    "BLOCKED_COMPATIBILITY",
    "BLOCKED_RUNTIME",
    "BLOCKED_SCOPE_EXPANSION",
}


def fail(message):
    raise AssertionError(message)


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
    if contract["starting_refs"]["MePhC"] != "b8304cb0050ee184929a217662a02dc05ae5e16c":
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
    for label, expected in protected["protected_r6_r11_directory_digests"].items():
        current = digest(MEPHC / f"docs/architecture/mephc_affine_architecture_{label}")
        if current["file_count"] != expected["file_count"] or current["sha256"] != expected["sha256"] or current["files"] != [tuple(x) for x in expected["files"]]:
            fail("protected digest " + label)
    inh = json.loads((ROOT / "r11_inheritance.json").read_text())
    if inh["terminal_state"] != "BLOCKED_FIRST_ORDER_ZERO_NUMERICALLY_UNRESOLVED" or not inh["immutable"]:
        fail("R11 inheritance")
    rule = json.loads((ROOT / "continuum_selection_rule_inheritance.json").read_text())
    if rule["label"] != "NONDEGENERATE_ZERO_MEAN_FIRST_ORDER_SELECTION_RULE_DERIVED" or not rule["coefficient_sum_zero"]:
        fail("selection rule")
    anchor = json.loads((ROOT / "canonical_anchor_definition.json").read_text())
    if anchor["anchor_site"] != 1 or anchor["sites"] != [0, 1, 2] or anchor["h_levels"] != [0.0005, 0.001]:
        fail("anchor")
    if anchor["fixed_mapping"] != {"0": [1.0, 0.0], "1": [0.0, 0.0], "2": [-1.0, 0.0]}:
        fail("fixed mapping")
    geometry = json.loads((ROOT / "canonical_tangent_geometry.json").read_text())
    epsilon = json.loads((ROOT / "canonical_tangent_epsilon.json").read_text())
    for res in ("96", "112"):
        for h in ("0.0005", "0.001"):
            for sign in ("plus", "minus"):
                rows = geometry[res][h][sign]
                if set(rows) != {"0", "1", "2"} or not all(x["full_typed_geometry"]["equivalent"] for x in rows.values()):
                    fail("canonical geometry")
                erows = epsilon["resolutions"][res][h][sign]
                hashes = [erows[str(site)]["normalized_byte_sha256"] for site in (0, 1, 2)]
                if len(set(hashes)) != 1:
                    fail("epsilon equivalence")
                if any(erows[str(site)]["array_shape"] != ([288, 96] if res == "96" else [336, 112]) for site in (0, 1, 2)):
                    fail("epsilon shape")
    if not epsilon["direct_site_comparison"]["bit_identical_after_mapping"]:
        fail("epsilon direct comparison")
    spectra = json.loads((ROOT / "canonical_tangent_spectra.json").read_text())
    if spectra["q_point"] != "q2" or spectra["bands"] != [1, 2, 3, 4, 5, 6] or spectra["h_levels"] != [0.0005, 0.001]:
        fail("canonical spectrum scope")
    for res in ("96", "112"):
        for h in ("0.0005", "0.001"):
            for sign in ("plus", "minus"):
                if set(spectra["resolutions"][res][h][sign]) != {"0", "1", "2"}:
                    fail("missing canonical site")
    origin = json.loads((ROOT / "origin_phase_definition.json").read_text())
    if origin["phases"] != [0.0, 0.25, 0.5, 0.75] or origin["amplitudes"] != [0.0005, 0.001, 0.002]:
        fail("origin phase scope")
    derivatives = json.loads((ROOT / "origin_phase_derivatives.json").read_text())
    for res in ("96", "112"):
        if set(derivatives["resolutions"][res]) != {"0", "0.25", "0.5", "0.75"}:
            fail("origin phases")
        for phase in ("0", "0.25", "0.5", "0.75"):
            if set(derivatives["resolutions"][res][phase]) != {"0.0005", "0.001", "0.002"}:
                fail("origin amplitudes")
    solver = json.loads((ROOT / "solver_execution.json").read_text())
    if solver["fresh_solver_call_count"] != 92 or solver["resolutions_used"] != [96, 112]:
        fail("solver count/resolution")
    if solver["above_112_ran"] or solver["triLatt_fresh_mpb_calls"] != 0 or not solver["no_retry_hunting"]:
        fail("solver scope")
    for call in solver["fresh_solver_calls"]:
        if call["q_point"] != "q2" or call["resolution"] not in (96, 112) or call["solver_tolerance"] != 1e-10:
            fail("solver ledger")
        if call["solver"] != "meep.mpb.ModeSolver" or call["polarization"] != "TE" or call["response_bands"] != [1, 2, 3, 4, 5, 6]:
            fail("solver identity")
    repeats = json.loads((ROOT / "same_input_repeat_floor.json").read_text())
    for res in ("96", "112"):
        if not all(repeats[res]["exactly_two_repeats"].values()) or repeats[res]["retry_hunting"]:
            fail("repeat controls")
    guard = json.loads((ROOT / "band_identity_guard.json").read_text())
    if not guard["pass"]:
        fail("band identity")
    c1 = json.loads((ROOT / "origin_phase_c1.json").read_text())
    if not c1["origin_phase_zero_closed"]:
        fail("origin zero closure")
    mech = json.loads((ROOT / "mechanism_adjudication.json").read_text())
    if mech["scientific_terminal_state"] not in TERMINALS:
        fail("terminal")
    unc = json.loads((ROOT / "uncertainty_budget.json").read_text())
    if not all(x in unc["origin_phase_uncertainty_components"] for x in (
        "abs_c1bar_112_minus_c1bar_96", "leave_one_origin_phase_out_spread_112",
        "leave_one_amplitude_out_spread_112", "same_input_repeat_over_smallest_A",
        "canonical_representation_difference_over_smallest_A", "phase_half_range_D_at_smallest_A"
    )):
        fail("uncertainty components")
    scope = json.loads((ROOT / "change_scope.json").read_text())
    if scope["production_changes"] != [] or scope["fresh_trilatt_solver_calls"] != 0 or scope["r13_authorized"]:
        fail("scope")
    if seal:
        for name in ("artifact_manifest.json", "integrity.json", "completion.json"):
            if not (ROOT / name).exists():
                fail("seal " + name)
        manifest = json.loads((ROOT / "artifact_manifest.json").read_text())
        for row in manifest["files"]:
            file = ROOT / row["path"]
            if not file.exists() or file.stat().st_size != row["size_bytes"]:
                fail("manifest file")
            if hashlib.sha256(file.read_bytes()).hexdigest() != row["sha256"]:
                fail("manifest digest")
        integrity = json.loads((ROOT / "integrity.json").read_text())
        if integrity["contract_sha256"] != SHA or integrity["payload_file_count"] != len(manifest["files"]):
            fail("integrity")
        if json.loads((ROOT / "completion.json").read_text())["seal_status"] != "SEALED":
            fail("completion")
    return "PASS_R12_EVIDENCE_VALIDATOR"


if __name__ == "__main__":
    try:
        print(audit("--preseal" not in sys.argv))
    except Exception as exc:
        print("FAIL_R12_EVIDENCE_VALIDATOR:", exc)
        raise SystemExit(1)
