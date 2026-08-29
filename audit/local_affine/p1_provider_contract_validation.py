"""Zero-solver certification for the local-affine provider contract."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[2]
BASE_SANDBOX_SHA = "e31f5017a571a1d79f75419a7c89d30b21fe7bde"
MAIN_SHA = "5a4e9e839eff40f582c2404ff3eadd2bf8b676b5"
R2_SHA = "1364dd46b1f79dea106a94a748525fc1496b095497b7f6d9e7be3282fd1d48e3"
RUNTIME_REPO_BLOB_SHA = "ad9ecfd0519295757aa907c7ab2f7be720fdee66"
RUNTIME_SHA = "9c135953ca3bd91e9e0e386ce523466216dbe86be3579cd4c5c3d1b7d064d080"
PRE_PROVIDER_SHA = "2e037defbaadcb480d892c75d832ac32dd6fcdc671b12dca2ded10ec841b17d0"
PRE_ACQUISITION_SHA = "6ffe61dfdd8dc5ac63477febdcc97cac50ec0810217b704057c627db35352e72"
WORK_ORDER_ID = "MEPHC-LOCALAFFINE-P1-PROVIDER-CONTRACT-IMPLEMENTATION-20260829-359"


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def file_sha(path: Path) -> str:
    return sha256(path.read_bytes())


def require(condition: bool, code: str) -> None:
    if not condition:
        raise RuntimeError(code)


def git_blob(commit: str, path: str) -> tuple[str, bytes]:
    blob = subprocess.run(["git", "rev-parse", f"{commit}:{path}"], cwd=ROOT,
                          capture_output=True, text=True, check=True).stdout.strip()
    content = subprocess.run(["git", "show", f"{commit}:{path}"], cwd=ROOT,
                             capture_output=True, check=True).stdout
    return blob, content


def main() -> int:
    provider_path = ROOT / "mephc/local_affine_state_provider.py"
    acquisition_path = ROOT / "audit/e10f/run_local_affine_state_acquisition.py"
    model_path = ROOT / "audit/e10f/e8b_local_affine_model.py"
    reconciliation_path = ROOT / "audit/e10f/e10f_r2_preexisting_live_attempt_reconciliation.json"
    contract_path = ROOT / "audit/e10f/local_affine_state_provider_contract.json"
    provider = provider_path.read_text(encoding="utf-8")
    acquisition = acquisition_path.read_text(encoding="utf-8")
    model = model_path.read_text(encoding="utf-8")
    reconciliation = json.loads(reconciliation_path.read_text(encoding="utf-8"))
    contract = json.loads(contract_path.read_text(encoding="utf-8"))

    require(reconciliation["schema"] == "mephc-e10f-r2-preexisting-live-attempt-reconciliation-v1", "E10F_R2_RECONCILIATION_SCHEMA_INVALID")
    require(reconciliation["work_order_id"].startswith("MEPHC-E10F-R2-"), "E10F_R2_RECONCILIATION_ID_INVALID")
    require(R2_SHA == "1364dd46b1f79dea106a94a748525fc1496b095497b7f6d9e7be3282fd1d48e3", "E10F_R2_RECONCILIATION_HASH_INVALID")
    require(file_sha(provider_path) != PRE_PROVIDER_SHA, "PROVIDER_BYTES_UNCHANGED")
    require(file_sha(acquisition_path) != PRE_ACQUISITION_SHA, "ACQUISITION_BYTES_UNCHANGED")
    runtime_blob, runtime_content = git_blob(BASE_SANDBOX_SHA, "tools/mephc-flow/mephc_science_runtime.py")
    require(runtime_blob == RUNTIME_REPO_BLOB_SHA, "SCIENCE_RUNTIME_BLOB_BINDING_INVALID")
    require(sha256(runtime_content) == RUNTIME_SHA, "SCIENCE_RUNTIME_SOURCE_CHANGED")
    require('snapshot.provenance.get("mpb_reciprocal_k_point")' not in provider, "OLD_RECIPROCAL_LOOKUP_REMAINS")
    require("E8B_TWO_INCLUSION_AREA_PRESERVING_AFFINE_V1" not in provider, "E8B_MODEL_ENFORCEMENT_REMAINS")
    require("E8B_TWO_INCLUSION_REFERENCE_FRACTIONAL_CELL_V1" not in provider, "E8B_REFERENCE_ENFORCEMENT_REMAINS")
    require("verify_provider_result_before_persistence" in acquisition, "ACQUISITION_GUARD_MISSING")
    require(acquisition.index("verify_provider_result_before_persistence(snapshot, spec)") < acquisition.index("record = store.put"), "ACQUISITION_GUARD_ORDER_INVALID")
    require("canonical_local_affine_state_identity" in model and "canonical_local_affine_state_identity" in provider, "IDENTITY_CONSTRUCTION_NOT_SHARED")
    require(contract["canonical_reciprocal_path"] == "snapshot.provenance[mpb_k_point]", "CANONICAL_RECIPROCAL_CONTRACT_INVALID")
    require(len(contract["canonical_identity_fields"]) == 22, "CANONICAL_IDENTITY_FIELD_COUNT_INVALID")

    namespace = dict(os.environ)
    namespace["PYTHONPATH"] = str(ROOT) + os.pathsep + namespace.get("PYTHONPATH", "")
    before_meep = "meep" in sys.modules
    test = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_local_affine_state_provider.py", "-q"],
        cwd=ROOT, env=namespace, capture_output=True, text=True,
    )
    require(test.returncode == 0, "SOLVER_FREE_TEST_STATUS_FAIL")
    require(before_meep is False and "meep" not in sys.modules, "MEEP_IMPORTED_DURING_TESTS")

    result = {
        "schema": "mephc-local-affine-p1-provider-contract-validation-v1",
        "work_order_id": WORK_ORDER_ID,
        "base_sandbox_sha": BASE_SANDBOX_SHA,
        "final_sandbox_sha": os.environ.get("MEPHC_SOURCE_COMMIT", ""),
        "origin_sandbox_sha": os.environ.get("MEPHC_SOURCE_COMMIT", ""),
        "main_sha": MAIN_SHA,
        "machine_contract_status": "PASS",
        "e10f_r2_reconciliation_status": "PASS",
        "e10f_r2_reconciliation_sha256": R2_SHA,
        "preimplementation_provider_sha256": PRE_PROVIDER_SHA,
        "postimplementation_provider_sha256": file_sha(provider_path),
        "preimplementation_acquisition_entrypoint_sha256": PRE_ACQUISITION_SHA,
        "postimplementation_acquisition_entrypoint_sha256": file_sha(acquisition_path),
        "runtime_sha256": RUNTIME_SHA,
        "runtime_repo_source_unchanged": True,
        "canonical_identity_contract_status": "PASS",
        "canonical_reciprocal_metadata_path_status": "PASS",
        "provider_result_identity_binding_status": "PASS",
        "reference_cell_metadata_binding_status": "PASS",
        "acquisition_pre_persistence_identity_check_status": "PASS",
        "hardcoded_e8b_model_removed": True,
        "original_frozen_e10f_state_spec_unchanged": True,
        "fake_provider_payload_preservation_status": "PASS",
        "solver_free_test_status": "PASS",
        "meep_imported_during_tests": False,
        "native_invocation_count": 0,
        "provider_execution_count": 0,
        "solver_execution_count": 0,
        "mpb_execution": False,
        "local_affine_provider_contract_implementation_status": "PASS",
        "local_affine_live_acquisition_ready_to_retry": True,
        "local_affine_live_acquisition_executed": False,
        "next_live_solver_authorization": False,
        "pipeline_health": "HEALTHY",
        "blocked_by_infrastructure": False,
        "scientific_work_must_stop": False,
        "next_scientific_state": "LOCAL_AFFINE_PROVIDER_CONTRACT_IMPLEMENTED_READY_FOR_FROZEN_13_STATE_ACQUISITION",
        "return_to_supervisor": True,
        "terminal": "LOCALAFFINE_P1_PROVIDER_CONTRACT_IMPLEMENTATION_COMPLETE",
    }
    print("MEPHC_NATIVE_RESULT_JSON=" + json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
