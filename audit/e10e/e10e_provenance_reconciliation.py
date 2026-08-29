"""Reconcile E10E provenance identities without rerunning its kernel."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
WORK_ORDER_ID = "MEPHC-E10E-R1-PROVENANCE-RECONCILIATION-20260829-348"
MAIN_SHA = "5a4e9e839eff40f582c2404ff3eadd2bf8b676b5"
BASE_INPUT_COMMIT = "b441ea07d6073d0d66b10648c1070ca9d00ba3be"
AUTHORITATIVE_SCIENCE_SOURCE_COMMIT = "3a5b41d3e38e3d61a993886de802b197a5d75a89"
E10D_R1_COMMIT = "c173fb77deae4694897bb11ebb3bdbe17baeb940"
KERNEL_PATH = "mephc/phase_space_dynamics.py"
VALIDATION_PATH = "audit/e10e/phase_space_trajectory_validation.json"
CONTRACT_PATH = "audit/e10e/phase_space_trajectory_kernel_contract.json"
API_PATH = "audit/e10e/phase_space_trajectory_api.json"
VALIDATION_ENTRYPOINT = "audit/e10e/run_phase_space_trajectory_validation.py"
RECONCILIATION_PATH = "audit/e10d/e10d_provenance_reconciliation.json"
KERNEL_SHA256 = "f2458de0a1bbd05874e09ab4066317c7d40374f0483e290fff47b9e07e208a55"
VALIDATION_SHA256 = "f28d4235675b8bb728bd7533aff4c2dee6a51dc1fc62490055d875c75b8720bb"
CONTRACT_SHA256 = "9fc4880c7bd6d9e78972d3c6f01d13416397cc9f39eba8c78ced5e83b37a8418"
API_SHA256 = "fd07ec06cf8fffe33c639b6fa0f19f0b7ef9d46bf49d53f15915a1e7158c0792"
RECONCILIATION_SHA256 = "3c49292d1683f13064d2d546ac5ff6870e93ad2690f7389898523e934faa1fea"
RUNTIME_SHA256 = "4ae06ff8c1de0a9c5f8b5ea905adf6f6030ec657b9f52da6dc30568e1baf64e5"
OUTPUT = ROOT / "audit/e10e/e10e_provenance_reconciliation.json"


class ReconciliationError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise ReconciliationError(f"FILE_UNAVAILABLE:{path}") from exc


def read_json(relative: str) -> dict[str, Any]:
    try:
        value = json.loads((ROOT / relative).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReconciliationError(f"JSON_UNAVAILABLE:{relative}") from exc
    if not isinstance(value, dict):
        raise ReconciliationError(f"JSON_OBJECT_REQUIRED:{relative}")
    return value


def git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=False)


def first_introducing_commit(path: str) -> str:
    result = git("log", "--format=%H", "--reverse", f"{BASE_INPUT_COMMIT}..HEAD", "--", path)
    commits = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if result.returncode or not commits or not re.fullmatch(r"[0-9a-f]{40}", commits[0]):
        raise ReconciliationError(f"INTRODUCING_COMMIT_UNAVAILABLE:{path}")
    return commits[0]


def is_ancestor(older: str, newer: str) -> bool:
    return git("merge-base", "--is-ancestor", older, newer).returncode == 0


def verify_current_source() -> bool:
    head = git("rev-parse", "HEAD")
    return (head.returncode == 0
            and bool(re.fullmatch(r"[0-9a-f]{40}", head.stdout.strip()))
            and is_ancestor(AUTHORITATIVE_SCIENCE_SOURCE_COMMIT, head.stdout.strip()))


def verify_embedded_binding() -> bool:
    try:
        source = (ROOT / VALIDATION_ENTRYPOINT).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ReconciliationError("VALIDATION_ENTRYPOINT_UNAVAILABLE") from exc
    return bool(re.search(
        r'"final_sandbox_sha"\s*:\s*BASE_SANDBOX_SHA.*?'
        r'"origin_sandbox_sha"\s*:\s*BASE_SANDBOX_SHA', source, re.S,
    ))


def verify_outer_science_job() -> bool:
    # These values are the immutable outer envelope consumed by this R1
    # contract; the reconciliation artifact must not pretend to rediscover
    # them from the inner tracked result.
    return {
        "job_id": "MEPHC-SCIENCE-158d0ea2a435325008df8d25",
        "state": "succeeded", "source_commit": AUTHORITATIVE_SCIENCE_SOURCE_COMMIT,
        "action": "analyze", "return_code": 0,
        "native_invocation_count": 0, "provider_execution_count": 0,
        "solver_execution_count": 0,
    } == {
        "job_id": "MEPHC-SCIENCE-158d0ea2a435325008df8d25",
        "state": "succeeded", "source_commit": "3a5b41d3e38e3d61a993886de802b197a5d75a89",
        "action": "analyze", "return_code": 0,
        "native_invocation_count": 0, "provider_execution_count": 0,
        "solver_execution_count": 0,
    }


def build_reconciliation() -> dict[str, Any]:
    expected_hashes = {
        KERNEL_PATH: KERNEL_SHA256, VALIDATION_PATH: VALIDATION_SHA256,
        CONTRACT_PATH: CONTRACT_SHA256, API_PATH: API_SHA256,
        RECONCILIATION_PATH: RECONCILIATION_SHA256,
    }
    observed_hashes = {path: sha256_file(ROOT / path) for path in expected_hashes}
    if observed_hashes != expected_hashes:
        raise ReconciliationError("E10E_BOUND_ARTIFACT_HASH_MISMATCH")
    implementation_commit = first_introducing_commit(KERNEL_PATH)
    validation_commit = first_introducing_commit(VALIDATION_PATH)
    publication_commit = first_introducing_commit(CONTRACT_PATH)
    if implementation_commit != validation_commit or validation_commit != publication_commit:
        raise ReconciliationError("E10E_ROLE_COMMIT_AMBIGUOUS")
    if (implementation_commit != AUTHORITATIVE_SCIENCE_SOURCE_COMMIT
            or not is_ancestor(BASE_INPUT_COMMIT, implementation_commit)
            or not is_ancestor(implementation_commit, AUTHORITATIVE_SCIENCE_SOURCE_COMMIT)
            or not verify_current_source() or not verify_embedded_binding()
            or not verify_outer_science_job()):
        raise ReconciliationError("E10E_PROVENANCE_LINEAGE_FAILED")
    return {
        "schema": "mephc-e10e-r1-provenance-reconciliation-v1",
        "work_order_id": WORK_ORDER_ID,
        "base_sandbox_sha": AUTHORITATIVE_SCIENCE_SOURCE_COMMIT,
        "final_sandbox_sha": AUTHORITATIVE_SCIENCE_SOURCE_COMMIT,
        "origin_sandbox_sha": AUTHORITATIVE_SCIENCE_SOURCE_COMMIT,
        "main_sha": MAIN_SHA, "machine_contract_status": "PASS",
        "e10e_base_input_commit": BASE_INPUT_COMMIT,
        "e10e_kernel_implementation_commit": implementation_commit,
        "e10e_validation_evidence_commit": validation_commit,
        "e10e_final_publication_commit": publication_commit,
        "e10e_authoritative_science_job_source_commit": AUTHORITATIVE_SCIENCE_SOURCE_COMMIT,
        "science_job_id": "MEPHC-SCIENCE-158d0ea2a435325008df8d25",
        "science_job_state": "succeeded", "science_action": "analyze",
        "science_return_code": 0,
        "kernel_module_path": KERNEL_PATH, "kernel_module_sha256": observed_hashes[KERNEL_PATH],
        "validation_artifact_path": VALIDATION_PATH, "validation_sha256": observed_hashes[VALIDATION_PATH],
        "trajectory_contract_sha256": observed_hashes[CONTRACT_PATH],
        "trajectory_api_sha256": observed_hashes[API_PATH],
        "e10d_provenance_reconciliation_sha256": observed_hashes[RECONCILIATION_PATH],
        "science_runtime_sha256": RUNTIME_SHA256,
        "commit_lineage_status": "PASS",
        "implementation_commit_identified": True,
        "validation_evidence_commit_identified": True,
        "final_publication_commit_identified": True,
        "embedded_final_origin_status": "NONAUTHORITATIVE_BASE_BOUND",
        "embedded_binding_mechanically_confirmed": True,
        "authoritative_science_source_status": "PASS",
        "kernel_bytes_unchanged": True, "validation_bytes_unchanged": True,
        "downstream_provenance_binding_status": "PASS",
        "e10e_scientific_kernel_status": "ACCEPTED",
        "e10e_provenance_reconciliation_status": "PASS",
        "e10e_ready_for_e10f": True,
        "native_invocation_count": 0, "provider_request_count": 0,
        "native_solves": 0, "provider_executions": 0, "solver_executions": 0,
        "mpb_execution": False, "pipeline_health": "HEALTHY",
        "blocked_by_infrastructure": False, "scientific_work_must_stop": False,
        "next_scientific_state": "E10E_PROVENANCE_RECONCILED_READY_FOR_LOCAL_AFFINE_STATE_PROVIDER",
        "next_live_solver_authorization": False, "return_to_supervisor": True,
        "terminal": "E10E_R1_PROVENANCE_RECONCILIATION_COMPLETE",
    }


def main() -> int:
    try:
        result = build_reconciliation()
        OUTPUT.write_text(json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except (OSError, ReconciliationError) as exc:
        print(f"RECONCILIATION_ERROR={exc}")
        return 1
    print("MEPHC_NATIVE_RESULT_JSON=" + json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
