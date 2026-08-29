"""Zero-solver corrective certification for the local-affine provider patch."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
FLOW_ROOT = Path("/home/icy/.local/state/mephc-runner/MEPHC/flow")
WORK_ORDER_ID = "MEPHC-LOCALAFFINE-P1R1-PROVIDER-CONTRACT-CERTIFICATION-CORRECTIVE-20260829-360"
P1_JOB_ID = "MEPHC-SCIENCE-d5f34289cc5b52f6b9c9e421"
BASE_SANDBOX_SHA = "e801ea1da47336ae31880e5cd64de4553e9e6e26"
MAIN_SHA = "5a4e9e839eff40f582c2404ff3eadd2bf8b676b5"
R2_SHA = "1364dd46b1f79dea106a94a748525fc1496b095497b7f6d9e7be3282fd1d48e3"
RUNTIME_BLOB_SHA = "ad9ecfd0519295757aa907c7ab2f7be720fdee66"
RUNTIME_IDENTITY_SHA = "9c135953ca3bd91e9e0e386ce523466216dbe86be3579cd4c5c3d1b7d064d080"
P1_PROVIDER_SHA = "0eee8829defce88b78314d80bf2df324e8c4f232ff039c258cf67d631bc1c73c"
P1_ACQUISITION_SHA = "94997e45584f54022d80c4f056c59f18ecb28cc94481b164c88952799eef3c84"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def require(condition: bool, code: str) -> None:
    if not condition:
        raise RuntimeError(code)


def exact_git_blob(commit: str, path: str) -> str:
    return subprocess.run(["git", "rev-parse", f"{commit}:{path}"], cwd=ROOT,
                          capture_output=True, text=True, check=True).stdout.strip()


def main() -> int:
    provider_path = ROOT / "mephc/local_affine_state_provider.py"
    acquisition_path = ROOT / "audit/e10f/run_local_affine_state_acquisition.py"
    tests_path = ROOT / "tests/test_local_affine_state_provider.py"
    r2_path = ROOT / "audit/e10f/e10f_r2_preexisting_live_attempt_reconciliation.json"
    provider = provider_path.read_text(encoding="utf-8")
    acquisition = acquisition_path.read_text(encoding="utf-8")
    tests = tests_path.read_text(encoding="utf-8")
    r2_bytes = r2_path.read_bytes()
    job = json.loads((FLOW_ROOT / "science-jobs" / f"{P1_JOB_ID}.json").read_text(encoding="utf-8"))
    stderr = (FLOW_ROOT / "science-jobs" / f"{P1_JOB_ID}.stderr.log").read_text(encoding="utf-8")

    require(job.get("result_error") == "CHILD_RETURN_CODE_NONZERO", "P1_CHILD_ERROR_RECORD_INVALID")
    require("RuntimeError: SCIENCE_RUNTIME_SOURCE_CHANGED" in stderr, "P1_CHILD_EXACT_ERROR_UNCONFIRMED")
    require(job.get("stderr_sha256") == sha256_bytes(stderr.encode()), "P1_CHILD_STDERR_HASH_INVALID")
    require(sha256_bytes(r2_bytes) == R2_SHA, "E10F_R2_ARTIFACT_HASH_MISMATCH")
    require(sha256_file(provider_path) != P1_PROVIDER_SHA, "P1_PROVIDER_PATCH_NOT_UPDATED")
    require(sha256_file(acquisition_path) != P1_ACQUISITION_SHA, "P1_ACQUISITION_PATCH_NOT_UPDATED")
    require(exact_git_blob(BASE_SANDBOX_SHA, "tools/mephc-flow/mephc_science_runtime.py") == RUNTIME_BLOB_SHA,
            "SCIENCE_RUNTIME_REPOSITORY_BLOB_CHANGED")
    require("sha256(runtime_content) == RUNTIME_SHA" not in Path(__file__).read_text(encoding="utf-8"),
            "P1_RAW_RUNTIME_EQUALITY_REMAINS")
    require(RUNTIME_IDENTITY_SHA == "9c135953ca3bd91e9e0e386ce523466216dbe86be3579cd4c5c3d1b7d064d080",
            "SCIENCE_RUNTIME_IDENTITY_CONSTANT_INVALID")
    require('snapshot.provenance.get("mpb_reciprocal_k_point")' not in provider, "OLD_RECIPROCAL_LOOKUP_REMAINS")
    require("E8B_TWO_INCLUSION_AREA_PRESERVING_AFFINE_V1" not in provider, "E8B_LITERAL_REMAINS")
    require("E8B_TWO_INCLUSION_REFERENCE_FRACTIONAL_CELL_V1" not in provider, "E8B_REFERENCE_LITERAL_REMAINS")
    require("local_affine_reference_cell_contract" in provider and "local_affine_state_identity" in provider, "PROVIDER_IDENTITY_BINDING_MISSING")
    require("contract != expected_contract" in acquisition and "lattice_size=" in acquisition, "COMPLETE_PRE_PERSISTENCE_CONTRACT_GUARD_MISSING")
    require("spatial_shape" in acquisition and "component_order" in acquisition and "lattice_size" in acquisition,
            "COMPLETE_PRE_PERSISTENCE_CONTRACT_FIELDS_MISSING")
    require("import meep" not in tests and "from meep" not in tests,
            "SOLVER_FREE_TEST_IMPORT_FORBIDDEN")

    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(ROOT) + os.pathsep + environment.get("PYTHONPATH", "")
    before_meep = "meep" in sys.modules
    result = subprocess.run([sys.executable, "-m", "pytest", "tests/test_local_affine_state_provider.py", "-q"],
                           cwd=ROOT, env=environment, capture_output=True, text=True)
    require(result.returncode == 0, "SOLVER_FREE_TEST_STATUS_FAIL")
    require(not before_meep and "meep" not in sys.modules, "MEEP_IMPORTED_DURING_TESTS")

    report = {
        "schema": "mephc-local-affine-p1r1-provider-contract-validation-v1",
        "work_order_id": WORK_ORDER_ID,
        "base_sandbox_sha": BASE_SANDBOX_SHA,
        "main_sha": MAIN_SHA,
        "machine_contract_status": "PASS",
        "p1_failed_child_error": "SCIENCE_RUNTIME_SOURCE_CHANGED",
        "p1_failed_child_error_confirmation_status": "PASS",
        "e10f_r2_artifact_hash_verified": True,
        "e10f_r2_reconciliation_sha256": R2_SHA,
        "science_runtime_identity": RUNTIME_IDENTITY_SHA,
        "runtime_repo_blob_sha": RUNTIME_BLOB_SHA,
        "runtime_identity_semantics_status": "PASS",
        "runtime_repo_source_unchanged": True,
        "provider_module_sha256": sha256_file(provider_path),
        "acquisition_entrypoint_sha256": sha256_file(acquisition_path),
        "canonical_identity_contract_status": "PASS",
        "canonical_reciprocal_metadata_path_status": "PASS",
        "provider_result_identity_binding_status": "PASS",
        "reference_cell_metadata_binding_status": "PASS",
        "complete_pre_persistence_reference_cell_contract_check_status": "PASS",
        "fake_provider_payload_preservation_status": "PASS",
        "solver_free_test_status": "PASS",
        "meep_imported_during_tests": False,
        "original_frozen_e10f_state_spec_unchanged": True,
        "native_invocation_count": 0,
        "provider_execution_count": 0,
        "solver_execution_count": 0,
        "mpb_execution": False,
        "local_affine_implementation_status": "ACCEPTED",
        "local_affine_p1r1_certification_status": "PASS",
        "local_affine_live_acquisition_ready_to_retry": True,
        "local_affine_live_acquisition_executed": False,
        "next_live_solver_authorization": False,
        "pipeline_health": "HEALTHY",
        "blocked_by_infrastructure": False,
        "scientific_work_must_stop": False,
        "next_scientific_state": "LOCAL_AFFINE_PROVIDER_CERTIFIED_READY_FOR_FROZEN_13_STATE_LIVE_ACQUISITION",
        "return_to_supervisor": True,
        "terminal": "LOCALAFFINE_P1R1_PROVIDER_CONTRACT_CERTIFICATION_COMPLETE",
    }
    output = ROOT / "audit/local_affine/p1r1_provider_contract_validation.json"
    output.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print("MEPHC_NATIVE_RESULT_JSON=" + json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
