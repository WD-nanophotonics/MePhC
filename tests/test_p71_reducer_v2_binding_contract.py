from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "audit" / "local_affine" / "frozen_13_state_solver_free_reduction.py"


def _module():
    spec = importlib.util.spec_from_file_location("p71_reducer", TARGET)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _binding():
    return {"state_id": "STATE_01", "role": "CENTER", "public_q": [0.0, -0.6166666666666667], "s": 0.0}


def _identity(module):
    canonical = {"public_q": [0.0, -0.6166666666666667], "s": 0.0}
    value = {
        "state_id": "STATE_01", "role": "CENTER", "public_q": [0.0, -0.6166666666666667], "s": 0.0,
        "canonical_state_identity": canonical,
        "canonical_state_identity_sha256": hashlib.sha256(module._canonical(canonical)).hexdigest(),
        "solver_configuration": dict(module._SOLVER_CONFIGURATION), "reciprocal_metadata": [0.0, 0.0, 0.0],
        "reference_cell_contract_sha256": "0" * 64, "frequencies": [1.0], "raw_norms": [1.0],
        "normalized_vector_digest": "0" * 64, "request_graph_sha256": "0" * 64,
        "science_source_commit": "1" * 40, "payload_sha256": "a" * 64,
    }
    return value


def test_thin_v2_schema_acceptance_and_contract_sha_binding(tmp_path, monkeypatch):
    module = _module()
    bundle = {"schema": "mephc-thin-input-bundle-v1", "contract_sha256": "contract", "work_order_id": "P71", "datasets": []}
    path = tmp_path / "bundle.json"
    path.write_text(json.dumps(bundle), encoding="utf-8")
    monkeypatch.setenv("MEPHC_INPUT_BUNDLE", str(path))
    monkeypatch.setenv("MEPHC_SCIENCE_CONTRACT_SHA256", "contract")
    with pytest.raises(ValueError, match="P71_DATASET_BINDINGS_COUNT_INVALID"):
        module.load_bundle()
    monkeypatch.setenv("MEPHC_SCIENCE_CONTRACT_SHA256", "wrong")
    with pytest.raises(ValueError, match="P71_CONTRACT_SHA_MISMATCH"):
        module.load_bundle()


def test_descriptor_requires_payload_size_bytes_and_checks_length(tmp_path):
    module = _module()
    plan = {"source_dataset_id": "dataset", "source_manifest_sha256": "manifest"}
    base = {"dataset_id": "dataset", "manifest_sha256": "manifest", "record_key_sha256": "a" * 64, "payload_sha256": "b" * 64, "payload_file": "payload.bin", "identity": {}}
    with pytest.raises(ValueError, match="P71_DATASET_DESCRIPTOR_MISSING:payload_size_bytes"):
        module.validate_bound_dataset_descriptors({"datasets": [base]}, plan)
    base["payload_size_bytes"] = 4
    module.validate_bound_dataset_descriptors({"datasets": [base]}, plan)
    payload = tmp_path / "payload.bin"
    payload.write_bytes(b"abc")
    with pytest.raises(ValueError, match="P71_PAYLOAD_LENGTH_MISMATCH"):
        module._payload_bytes(tmp_path / "bundle.json", base)


def test_record_role_canonical_digest_and_solver_configuration_are_hard_bindings():
    module = _module()
    identity = _identity(module)
    descriptor = {"payload_sha256": identity["payload_sha256"]}
    wrong_role = dict(identity, role="PRIMARY_PLUS_QX")
    with pytest.raises(ValueError, match="P71_RECORD_ROLE_MISMATCH"):
        module.validate_record_identity(wrong_role, _binding(), descriptor)
    wrong_digest = dict(identity, canonical_state_identity_sha256="f" * 64)
    with pytest.raises(ValueError, match="P71_CANONICAL_IDENTITY_DIGEST_MISMATCH"):
        module.validate_record_identity(wrong_digest, _binding(), descriptor)
    wrong_solver = dict(identity, solver_configuration=dict(identity["solver_configuration"], mesh_size=4))
    with pytest.raises(ValueError, match="P71_SOLVER_CONFIGURATION_MISMATCH"):
        module.validate_record_identity(wrong_solver, _binding(), descriptor)


def test_future_result_templates_and_legacy_contract_rejection():
    module = _module()
    result = module._future_result("PASS")
    assert result["schema"] == "mephc-local-affine-solver-free-two-scale-reduction-v1"
    assert result["native_invocation_count"] == 1
    assert result["provider_execution_count"] == 0
    assert result["solver_execution_count"] == 0
    assert result["dataset_record_count"] == 0
    assert result["mpb_execution"] is False
    assert result["field_payload_retained"] is False
    source = TARGET.read_text(encoding="utf-8")
    ast.parse(source)
    for legacy in ("mephc-input-bundle-v1", "payload_size compatibility", 'get("state_identity")', 'get("solver_configuration_identity")', "mephc-local-affine-p66-solver-free-reduction-v1", "provider_request_count", '"native_invocation_count": 0'):
        assert legacy not in source
    assert "payload_size_bytes" in source
    assert "canonical_state_identity" in source
    assert "MEPHC_SCIENCE_CONTRACT_SHA256" in source


def test_reducer_compiles_without_private_dataset_materialization():
    compile(TARGET.read_text(encoding="utf-8"), str(TARGET), "exec")
