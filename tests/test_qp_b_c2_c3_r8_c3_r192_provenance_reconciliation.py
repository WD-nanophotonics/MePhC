from __future__ import annotations

import importlib.util
import hashlib
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "audit" / "e9f"
SCRIPT = AUDIT / "qp_b_c2_c3_r8_c3_r192_provenance_reconciliation.py"
GRAPH = AUDIT / "qp_b_c2_c3_r8_c3_r192_request_graph.json"


def load():
    spec = importlib.util.spec_from_file_location("r192_reconciliation", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_graph_hash_and_contract_targets_are_frozen():
    module = load()
    assert hashlib.sha256(GRAPH.read_bytes()).hexdigest() == module.TARGET_GRAPH_SHA256
    assert module.TARGET_SOURCE_COMMIT == "f468e6016fed3019fcdf5937722abf47d20995e6"
    assert module.TARGET_DECLARED_SOURCE_COMMIT == "56f7e51a2cb910a7187d982366a492c9cb17bd09"
    assert module.PARENT_DATASET_ID == "a2935beba40ef0c4b524198e6d2f44b93630bdff4c645e61a47d31187012b3db"


def test_candidate_selection_requires_all_immutable_identities():
    module = load()
    manifest = {
        "schema": "mephc_direct_flow_r8_acquisition_dataset_v1",
        "dataset_id": module.RAW_DATASET_ID, "manifest_sha256": module.RAW_MANIFEST_SHA256,
        "resolution": "R192", "acquisition_source_commit": module.TARGET_DECLARED_SOURCE_COMMIT,
        "entrypoint_sha256": module.TARGET_ENTRYPOINT_SHA256, "graph_sha256": module.TARGET_GRAPH_SHA256,
        "parent_dataset_id": module.PARENT_DATASET_ID, "source_model_identity": "FROZEN_QP_B_SOURCE_MODEL",
        "provider_configuration_identity": "FROZEN_QP_B_PROVIDER_CONFIGURATION",
        "band_request_configuration": "FROZEN_QP_B_LOCKED_BAND_REQUEST", "completed_key_count": 70,
        "records": [{}] * 70, "completion_state": "COMPLETE", "dataset_is_mpb_backed": True,
        "fresh_provider_execution_count": 70, "cache_reuse_count": 0,
    }
    generic = {"namespace": {"source_commit": module.TARGET_DECLARED_SOURCE_COMMIT}}
    summary = {"R192_dataset_id": module.RAW_DATASET_ID}
    assert module.candidate_matches(manifest, generic, summary)
    for field, value in (("graph_sha256", "0" * 64), ("parent_dataset_id", "1" * 64), ("resolution", "R224")):
        changed = dict(manifest)
        changed[field] = value
        assert not module.candidate_matches(changed, generic, summary)


def test_manifest_integrity_and_dataset_immutability_checks():
    module = load()
    unsigned = {
        "schema": "mephc_direct_flow_r8_acquisition_dataset_v1", "records": [],
        "dataset_id": "placeholder", "manifest_sha256": "placeholder",
    }
    unsigned["dataset_id"] = hashlib.sha256(module.canonical({"schema": unsigned["schema"], "records": []})).hexdigest()
    unsigned["manifest_sha256"] = hashlib.sha256(module.canonical({key: value for key, value in unsigned.items() if key != "manifest_sha256"})).hexdigest()
    generic = {"completion_state": "COMPLETE", "record_count": 70}
    namespace = {"source_commit": module.TARGET_DECLARED_SOURCE_COMMIT, "resolution": "R192"}
    bad = dict(unsigned)
    bad["dataset_id"] = "0" * 64
    with pytest.raises(module.ReconciliationError, match="DATASET_ID_INTEGRITY_INVALID"):
        module.verify_manifest(bad, generic, namespace)


def test_reconciliation_content_is_bounded_and_preserves_historical_error(tmp_path):
    module = load()
    stdout = tmp_path / "stdout.log"
    stderr = tmp_path / "stderr.log"
    stdout.write_bytes(b"stdout")
    stderr.write_bytes(b"")
    job = {"job_id": "MEPHC-SCIENCE-test"}
    native = {"run_id": "MEPHC-NATIVE-test", "process_started": True, "return_code": 0,
              "state": "failed", "result_error": "RESULT_SUMMARY_UNSAFE"}
    manifest = {"dataset_id": module.RAW_DATASET_ID, "manifest_sha256": module.RAW_MANIFEST_SHA256,
                "acquisition_source_commit": module.TARGET_DECLARED_SOURCE_COMMIT}
    result = module.reconciliation_content(job, native, stdout, stderr, manifest, 70)
    assert result["provenance_defect_class"] == "HARDCODED_WORK_ORDER_BASE_USED_AS_ACQUISITION_SOURCE"
    assert result["dataset_mutation"] is False
    assert result["full_r192_record_integrity_pass_count"] == 70
    assert "/home/" not in json.dumps(result)
    assert "normalized_vectors" not in json.dumps(result)


def test_reconciliation_path_has_no_solver_or_provider_execution():
    source = SCRIPT.read_text(encoding="utf-8")
    assert "from mephc.mpb_spectral_provider" not in source
    assert "provider.solve" not in source
    assert "import meep" not in source
    assert "subprocess.run" in source
