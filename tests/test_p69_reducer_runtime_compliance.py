from __future__ import annotations

import ast
import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "audit" / "local_affine" / "frozen_13_state_solver_free_reduction.py"


def _module():
    spec = importlib.util.spec_from_file_location("p69_reducer", TARGET)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_runtime_contract_requires_successor_bundle_and_exact_record_set():
    module = _module()
    plan = {
        "schema": "mephc-local-affine-p66-p64-v2-binding-plan-v1",
        "source_work_order_id": "P64",
        "source_dataset_id": "dataset",
        "source_manifest_sha256": "manifest",
        "record_count": 13,
        "unique_record_key_count": 13,
    }
    bundle = {"schema": "mephc-input-bundle-v1", "work_order_id": "P69", "datasets": [{"record_key_sha256": str(i)} for i in range(13)]}
    provenance = module.validate_runtime_contract(bundle, plan)
    assert provenance["input_work_order_id"] == "P69"
    assert provenance["record_count"] == 13


def test_runtime_contract_rejects_reuse_of_source_work_order():
    module = _module()
    plan = {
        "source_work_order_id": "P64", "record_count": 13, "unique_record_key_count": 13,
        "source_dataset_id": "dataset", "source_manifest_sha256": "manifest", "schema": "plan",
    }
    bundle = {"schema": "mephc-input-bundle-v1", "work_order_id": "P64", "datasets": [{"record_key_sha256": str(i)} for i in range(13)]}
    try:
        module.validate_runtime_contract(bundle, plan)
    except ValueError as exc:
        assert str(exc) == "P69_SUCCESSOR_WORK_ORDER_MUST_BE_DISTINCT"
    else:
        raise AssertionError("source work order reuse was accepted")


def test_source_is_valid_python_and_has_no_science_backend_or_durable_scan():
    source = TARGET.read_text(encoding="utf-8")
    ast.parse(source)
    assert "import meep" not in source
    assert "from meep" not in source
    assert "resolve_dataset_record" not in source
    assert "LocalAffineStateProvider" not in source
    assert "MPBLiveSpectralProvider" not in source
    assert "MEPHC_INPUT_BUNDLE" in source and "MEPHC_RESULT_PATH" in source
