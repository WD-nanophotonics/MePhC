"""Reconcile E10D provenance without rerunning any scientific calculation."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
WORK_ORDER_ID = "MEPHC-E10D-R1-PROVENANCE-RECONCILIATION-20260829-346"
MAIN_SHA = "5a4e9e839eff40f582c2404ff3eadd2bf8b676b5"
BASE_SANDBOX_SHA = "c173fb77deae4694897bb11ebb3bdbe17baeb940"
E10D_BASE_INPUT_COMMIT = "35818629f9947cf7455d364ea2ebfb0f111bcd48"
E10D_KERNEL_IMPLEMENTATION_COMMIT = "b5e40fa08b27075fda08b821ab927a292d3d21f4"
E10D_VALIDATION_EVIDENCE_COMMIT = "06db5defaf1c3c892927089fa2cac18532440298"
E10D_FINAL_PUBLICATION_COMMIT = BASE_SANDBOX_SHA
E10D_AUTHORITATIVE_SCIENCE_SOURCE_COMMIT = BASE_SANDBOX_SHA
KERNEL_SHA256 = "e19683d6765163cc49cfd4ce1c35d5ddf6835c44ec9a65ab2ec400ad940ac2a6"
VALIDATION_SHA256 = "8274d1ef6d58581d1f163e90f1fbd4509e2d665de2cdaaa88498b42f050b03e8"
API_SHA256 = "1406ac2d3007774faafc09239d16a2ce22725964d15f17f6af62b8aa2f244d6f"
CONTRACT_SHA256 = "e28cb0ea316f182d94bc944f674ece71cc847e776c2bf0b8e1be4437f0f9c453"
RUNTIME_SHA256 = "4ae06ff8c1de0a9c5f8b5ea905adf6f6030ec657b9f52da6dc30568e1baf64e5"
VALIDATION_ENTRYPOINT = "audit/e10d/run_phase_space_geometry_validation.py"
OUTPUT = ROOT / "audit/e10d/e10d_provenance_reconciliation.json"


class ReconciliationError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise ReconciliationError(f"FILE_UNAVAILABLE:{path}") from exc


def git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=False,
    )


def current_source_is_descendant() -> bool:
    head = git("rev-parse", "HEAD")
    if head.returncode or not re.fullmatch(r"[0-9a-f]{40}", head.stdout.strip()):
        return False
    return git("merge-base", "--is-ancestor", E10D_FINAL_PUBLICATION_COMMIT, "HEAD").returncode == 0


def verify_lineage() -> bool:
    links = (
        (E10D_BASE_INPUT_COMMIT, E10D_KERNEL_IMPLEMENTATION_COMMIT),
        (E10D_KERNEL_IMPLEMENTATION_COMMIT, E10D_VALIDATION_EVIDENCE_COMMIT),
        (E10D_VALIDATION_EVIDENCE_COMMIT, E10D_FINAL_PUBLICATION_COMMIT),
    )
    return all(git("merge-base", "--is-ancestor", older, newer).returncode == 0 for older, newer in links)


def verify_embedded_source_binding() -> bool:
    try:
        source = (ROOT / VALIDATION_ENTRYPOINT).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ReconciliationError("VALIDATION_ENTRYPOINT_UNAVAILABLE") from exc
    marker = "def current_source_commit() -> str:"
    if marker not in source:
        return False
    body = source.split(marker, 1)[1].split("def verify_inputs", 1)[0]
    return "return BASE_SANDBOX_SHA" in body


def verify_bound_artifacts() -> dict[str, str]:
    expected = {
        "mephc/phase_space_geometry.py": KERNEL_SHA256,
        "audit/e10d/phase_space_geometry_validation.json": VALIDATION_SHA256,
        "audit/e10d/phase_space_geometry_api.json": API_SHA256,
        "audit/e10d/phase_space_geometry_kernel_contract.json": CONTRACT_SHA256,
    }
    observed = {path: sha256_file(ROOT / path) for path in expected}
    if observed != expected:
        raise ReconciliationError("BOUND_ARTIFACT_HASH_MISMATCH")
    return observed


def build_reconciliation() -> dict[str, Any]:
    hashes = verify_bound_artifacts()
    lineage = verify_lineage()
    source_descendant = current_source_is_descendant()
    embedded_binding = verify_embedded_source_binding()
    if not lineage or not source_descendant or not embedded_binding:
        raise ReconciliationError("PROVENANCE_RECONCILIATION_FAILED")
    return {
        "schema": "mephc-e10d-r1-provenance-reconciliation-v1",
        "work_order_id": WORK_ORDER_ID,
        "base_sandbox_sha": BASE_SANDBOX_SHA,
        "final_sandbox_sha": E10D_FINAL_PUBLICATION_COMMIT,
        "origin_sandbox_sha": E10D_FINAL_PUBLICATION_COMMIT,
        "main_sha": MAIN_SHA,
        "machine_contract_status": "PASS",
        "e10d_base_input_commit": E10D_BASE_INPUT_COMMIT,
        "e10d_kernel_implementation_commit": E10D_KERNEL_IMPLEMENTATION_COMMIT,
        "e10d_validation_evidence_commit": E10D_VALIDATION_EVIDENCE_COMMIT,
        "e10d_final_publication_commit": E10D_FINAL_PUBLICATION_COMMIT,
        "e10d_authoritative_science_job_source_commit": E10D_AUTHORITATIVE_SCIENCE_SOURCE_COMMIT,
        "kernel_module_path": "mephc/phase_space_geometry.py",
        "kernel_module_sha256": hashes["mephc/phase_space_geometry.py"],
        "validation_artifact_path": "audit/e10d/phase_space_geometry_validation.json",
        "validation_sha256": hashes["audit/e10d/phase_space_geometry_validation.json"],
        "api_sha256": hashes["audit/e10d/phase_space_geometry_api.json"],
        "contract_sha256": hashes["audit/e10d/phase_space_geometry_kernel_contract.json"],
        "science_runtime_sha256": RUNTIME_SHA256,
        "commit_lineage_status": "PASS",
        "embedded_final_origin_status": "NONAUTHORITATIVE_LEGACY_BASE_BOUND",
        "embedded_binding_mechanically_confirmed": True,
        "authoritative_science_source_status": "PASS",
        "kernel_bytes_unchanged": True,
        "validation_bytes_unchanged": True,
        "downstream_provenance_binding_status": "PASS",
        "e10d_scientific_kernel_status": "ACCEPTED",
        "e10d_provenance_reconciliation_status": "PASS",
        "e10d_ready_for_e10e": True,
        "native_invocation_count": 0,
        "provider_request_count": 0,
        "native_solves": 0,
        "provider_executions": 0,
        "solver_executions": 0,
        "mpb_execution": False,
        "pipeline_health": "HEALTHY",
        "blocked_by_infrastructure": False,
        "scientific_work_must_stop": False,
        "next_scientific_state": "E10D_PROVENANCE_RECONCILED_READY_FOR_SOLVER_FREE_TRAJECTORY_DYNAMICS",
        "return_to_supervisor": True,
        "terminal": "E10D_R1_PROVENANCE_RECONCILIATION_COMPLETE",
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
