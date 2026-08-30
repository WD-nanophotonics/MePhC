from __future__ import annotations

import ast
import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "audit" / "local_affine" / "frozen_13_state_solver_free_reduction.py"


def _module():
    spec = importlib.util.spec_from_file_location("p70_reducer", TARGET)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _plan():
    return {
        "source_work_order_id": "P64", "record_count": 1,
        "unique_record_key_count": 1, "source_dataset_id": "dataset",
        "source_manifest_sha256": "manifest", "schema": "plan",
    }


def test_full_runtime_requires_complete_bound_descriptor():
    module = _module()
    bundle = {"datasets": [{"dataset_id": "dataset", "manifest_sha256": "manifest", "record_key_sha256": "0" * 64, "payload_file": "payload.npz"}]}
    try:
        module.validate_bound_dataset_descriptors(bundle, _plan())
    except ValueError as exc:
        assert str(exc) == "P70_DATASET_DESCRIPTOR_MISSING:identity"
    else:
        raise AssertionError("incomplete descriptor was accepted")


def test_full_runtime_has_single_bundle_result_boundary_and_no_backend():
    source = TARGET.read_text(encoding="utf-8")
    ast.parse(source)
    assert "MEPHC_INPUT_BUNDLE" in source and "MEPHC_RESULT_PATH" in source
    assert "validate_bound_dataset_descriptors(bundle, plan)" in source
    assert "decode_snapshot(payload)" in source
    assert "import meep" not in source
    assert "from meep" not in source
    assert "resolve_dataset_record" not in source
    assert "LocalAffineStateProvider" not in source
    assert "MPBLiveSpectralProvider" not in source
