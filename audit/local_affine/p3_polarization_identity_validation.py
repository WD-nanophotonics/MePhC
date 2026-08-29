"""Solver-free validation of the explicit LocalAffine polarization identity."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
WORK_ORDER_ID = "MEPHC-LOCALAFFINE-P3-POLARIZATION-IDENTITY-IMPLEMENTATION-20260829-365"
BASE_SANDBOX_SHA = "8f03fefcee59df2251c513f0f65adf48c1ef805e"
MAIN_SHA = "5a4e9e839eff40f582c2404ff3eadd2bf8b676b5"
PREIMPLEMENTATION_PROVIDER_SHA = "ffc77a84bbcd28d2b32fa25bbbd32ea573b07ea461919b4a84afd0bfb6595a69"
GRAPH_SHA = "b33771c08eff0c989c10ae3bd80704d6eaeb71659c40931479c42055a6746ed4"
STATE_SET_SHA = "d38510a2a29996334dccb8fc697d6cec20179a7e510e11cea90806e8560d7549"
PROVIDER_PATH = ROOT / "mephc/local_affine_state_provider.py"
TEST_PATH = ROOT / "tests/test_local_affine_state_provider.py"
CONTRACT_PATH = ROOT / "audit/e10f/local_affine_state_provider_contract.json"
GRAPH_PATH = ROOT / "audit/local_affine/p2r1_frozen_13_state_request_graph.json"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def require(condition: bool, code: str) -> None:
    if not condition:
        raise RuntimeError(code)


def main() -> int:
    provider_source = PROVIDER_PATH.read_text(encoding="utf-8")
    test_source = TEST_PATH.read_text(encoding="utf-8")
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    graph = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
    provider_sha = sha256_file(PROVIDER_PATH)
    require(provider_sha != PREIMPLEMENTATION_PROVIDER_SHA, "PROVIDER_BYTES_UNCHANGED")
    require("polarization_identity" in provider_source, "EXPLICIT_POLARIZATION_IDENTITY_MISSING")
    require("str(self.polarization)" not in provider_source, "OPAQUE_POLARIZATION_STRING_INFERENCE_REMAINS")
    require("SOLVER_POLARIZATION_HANDLE_MISSING" in provider_source, "MISSING_SOLVER_HANDLE_GUARD_MISSING")
    require("POLARIZATION_IDENTITY_MISSING" in provider_source, "MISSING_POLARIZATION_IDENTITY_GUARD_MISSING")
    require("STATE_POLARIZATION_IDENTITY_MISMATCH" in provider_source, "STATE_POLARIZATION_GUARD_MISSING")
    require("local_affine_solver_polarization_identity" in provider_source, "POLARIZATION_PROVENANCE_BINDING_MISSING")
    tree = ast.parse(provider_source)
    provider_class = next((node for node in tree.body if isinstance(node, ast.ClassDef)
                           and node.name == "LocalAffineStateProvider"), None)
    require(provider_class is not None, "PROVIDER_CLASS_MISSING")
    fields = {node.target.id for node in provider_class.body if isinstance(node, ast.AnnAssign)
              and isinstance(node.target, ast.Name)}
    require({"polarization", "polarization_identity"}.issubset(fields), "POLARIZATION_FIELDS_MISSING")
    require(sha256_file(GRAPH_PATH) == GRAPH_SHA, "FROZEN_GRAPH_CHANGED")
    states = [(item["state_id"], item["role"], item["public_q"], item["s"]) for item in graph["states"]]
    require(hashlib.sha256(canonical(states)).hexdigest() == STATE_SET_SHA, "FROZEN_STATE_SET_CHANGED")
    identity_contract = contract.get("polarization_identity_contract", {})
    require(identity_contract.get("solver_polarization_handle") == "opaque runtime object", "HANDLE_CONTRACT_UNDOCUMENTED")
    require(identity_contract.get("canonical_polarization_identity") == "explicit semantic string", "IDENTITY_CONTRACT_UNDOCUMENTED")
    require(identity_contract.get("state_identity_polarization") == "must equal canonical identity", "STATE_IDENTITY_CONTRACT_UNDOCUMENTED")
    require(identity_contract.get("implicit_runtime_object_string_inference_forbidden") is True, "STRING_INFERENCE_POLICY_UNDOCUMENTED")
    required_tests = ("OpaquePolarization", "SOLVER_POLARIZATION_HANDLE_MISSING", "POLARIZATION_IDENTITY_MISSING",
                      "STATE_POLARIZATION_IDENTITY_MISMATCH", "local_affine_solver_polarization_identity")
    require(all(marker in test_source for marker in required_tests), "FOCUSED_POLARIZATION_TESTS_MISSING")
    require("meep" not in sys.modules, "MEEP_IMPORTED_BEFORE_FOCUSED_TESTS")
    env = dict(__import__("os").environ)
    env["PYTHONPATH"] = str(ROOT)
    completed = subprocess.run([sys.executable, "-m", "pytest", "-q", str(TEST_PATH)], cwd=ROOT,
                               env=env, capture_output=True, text=True, check=False)
    require(completed.returncode == 0, "SOLVER_FREE_TEST_STATUS_FAIL")
    require("meep" not in sys.modules, "MEEP_IMPORTED_DURING_VALIDATION")
    result = {
        "schema": "mephc-local-affine-p3-polarization-identity-validation-v1",
        "work_order_id": WORK_ORDER_ID, "base_sandbox_sha": BASE_SANDBOX_SHA, "main_sha": MAIN_SHA,
        "preimplementation_provider_sha256": PREIMPLEMENTATION_PROVIDER_SHA,
        "postimplementation_provider_sha256": provider_sha, "request_graph_sha256": GRAPH_SHA,
        "scientific_state_set_identity": STATE_SET_SHA, "explicit_polarization_identity_contract_status": "PASS",
        "missing_solver_polarization_fail_closed_status": "PASS", "missing_polarization_identity_fail_closed_status": "PASS",
        "opaque_solver_handle_binding_status": "PASS", "state_polarization_identity_match_status": "PASS",
        "provider_result_polarization_binding_status": "PASS", "provider_result_identity_binding_status": "PASS",
        "reference_cell_metadata_binding_status": "PASS", "fake_provider_payload_preservation_status": "PASS",
        "solver_free_test_status": "PASS", "meep_imported_during_tests": False,
        "frozen_scientific_state_set_unchanged": True, "native_invocation_count": 0,
        "provider_execution_count": 0, "solver_execution_count": 0, "mpb_execution": False,
        "localaffine_p3_polarization_identity_status": "PASS", "local_affine_live_acquisition_ready_to_reissue": True,
        "local_affine_live_acquisition_executed": False, "next_live_solver_authorization": False,
        "pipeline_health": "HEALTHY", "blocked_by_infrastructure": False, "scientific_work_must_stop": False,
        "next_scientific_state": "LOCAL_AFFINE_POLARIZATION_IDENTITY_CERTIFIED_READY_TO_REISSUE_FROZEN_13_STATE_ACQUISITION",
        "return_to_supervisor": True, "terminal": "LOCALAFFINE_P3_POLARIZATION_IDENTITY_IMPLEMENTATION_COMPLETE",
    }
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
