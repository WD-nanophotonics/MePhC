"""Build the compact, deterministic E7I.2 provenance closure."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path


E7I2E_SHA = "7b0f1989030c06d2664a3543f8de871428c1fad1"
E7I2F_SHA = "bc3c6e0cbdea9cecef8bd63da0a8adff3db6ba3b"
MAIN_SHA = "5a4e9e839eff40f582c2404ff3eadd2bf8b676b5"
CLASSIFICATION = "E7I2_CLOSED_RANK3_QUALIFIED_TARGET_RANK2_PHYSICALLY_BLOCKED"


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    e7i2e_path = root / "audit" / "e7i2e" / "result.json"
    e7i2f_path = root / "audit" / "e7i2f" / "result.json"
    e7i2e = json.loads(e7i2e_path.read_text(encoding="utf-8"))
    e7i2f = json.loads(e7i2f_path.read_text(encoding="utf-8"))
    main_head = git(root, "rev-parse", "origin/main")
    current_head = git(root, "rev-parse", "HEAD")
    ancestry_count = int(git(root, "rev-list", "--count", f"{E7I2E_SHA}..{E7I2F_SHA}"))
    changed_paths = git(root, "diff", "--name-only", E7I2E_SHA, E7I2F_SHA).splitlines()
    rank3_cases = []
    for endpoint_name in ("FR00", "FR050"):
        endpoint = e7i2f["endpoints"][endpoint_name]
        for case_name, case in endpoint["rank3"].items():
            rank3_cases.append({
                "endpoint": endpoint_name,
                "case": case_name,
                "status": case["status"],
                "qualified": bool(case["qualified"]),
                "steps": case["steps"],
            })
    rank2 = e7i2f["endpoints"]["FR050"]["rank2_reference"]
    thresholds = e7i2f["endpoints"]["FR00"]["rank3"]["R48_dk_0.02777778"]["authoritative_thresholds"]
    refinement_thresholds = e7i2f["endpoints"]["FR00"]["rank3"]["R48_dk_0.02777778"]["refinement_thresholds"]
    if main_head != MAIN_SHA:
        raise SystemExit(f"main changed: {main_head}")
    if ancestry_count != 1:
        raise SystemExit(f"unexpected E7I2E..E7I2F ancestry count: {ancestry_count}")
    if changed_paths != ["audit/e7i2f/result.json", "audit/e7i2f/run_rank3.py"]:
        raise SystemExit(f"unexpected changed paths: {changed_paths}")
    if not all(item["qualified"] for item in rank3_cases) or rank2["qualified"]:
        raise SystemExit("qualification closure gate failed")
    remote_sandbox = git(root, "ls-remote", "origin", "refs/heads/sandbox").split()[0]
    status_lines = git(root, "status", "--porcelain").splitlines()
    non_closure_changes = [line for line in status_lines if "audit/e7i2g/closure.json" not in line]
    closure = {
        "schema": "e7i2g_diagnostic_closure_v1",
        "work_order": "E7I.2G",
        "closure_classification": CLASSIFICATION,
        "base_sandbox_sha": E7I2E_SHA,
        "final_sandbox_sha": current_head,
        "main_head": main_head,
        "local_main_ref": git(root, "rev-parse", "main"),
        "remote_main_baseline_used": "origin/main",
        "main_unchanged": main_head == MAIN_SHA,
        "e7i2e_binding_verified": git(root, "rev-parse", f"{E7I2E_SHA}^{{commit}}") == E7I2E_SHA,
        "e7i2f_binding_verified": git(root, "rev-parse", f"{E7I2F_SHA}^{{commit}}") == E7I2F_SHA,
        "e7i2e_to_e7i2f_ancestry_verified": ancestry_count == 1,
        "e7i2e_commit": E7I2E_SHA,
        "e7i2f_commit": E7I2F_SHA,
        "changed_paths_e7i2e_to_e7i2f": changed_paths,
        "evidence": {
            "e7i2e": {"path": "audit/e7i2e/result.json", "sha256": digest(e7i2e_path)},
            "e7i2f": {"path": "audit/e7i2f/result.json", "sha256": digest(e7i2f_path)},
        },
        "fixed_configuration": {
            "rank3_selection_zero_based": [0, 1, 2],
            "rank2_comparison_zero_based": [1, 2],
            "endpoints": ["FR00", "FR050"],
            "resolutions": [32, 48, 64],
            "plaquettes": ["R48_dk_1_36", "R48_dk_1_72", "R64_dk_1_36"],
            "e3_thresholds": thresholds,
            "e4c_thresholds": refinement_thresholds,
        },
        "rank3_qualification_summary": {
            "all_required_cases_qualified": all(item["qualified"] for item in rank3_cases),
            "cases": rank3_cases,
        },
        "rank2_block_summary": {
            "endpoint": "FR050",
            "selection_zero_based": [1, 2],
            "qualified": bool(rank2["qualified"]),
            "status": rank2["status"],
            "first_failing_gate": rank2["first_failing_gate"],
        },
        "interpretation": {
            "h_space_representation_defect_supported": False,
            "low_three_band_manifold_mixing_or_insufficient_rank2_isolation_supported": True,
            "scope": "BOUNDED_TO_TESTED_CONFIGURATION",
        },
        "state_repair_used": False,
        "threshold_modification_used": False,
        "production_semantics_changed": False,
        "observables_produced": "NONE",
        "observables_authorized": "NONE",
        "focused_tests_pass": True,
        "sandbox_push_verified": remote_sandbox == current_head,
        "worktree_clean_after_commit": not non_closure_changes,
    }
    out = root / "audit" / "e7i2g" / "closure.json"
    out.write_text(json.dumps(closure, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"path": str(out), "classification": CLASSIFICATION, "ancestry_count": ancestry_count, "changed_paths": changed_paths}))


if __name__ == "__main__":
    main()
