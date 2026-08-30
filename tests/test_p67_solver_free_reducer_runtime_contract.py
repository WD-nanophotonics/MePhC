from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "audit" / "local_affine" / "frozen_13_state_solver_free_reduction.py"
PLAN = ROOT / "audit" / "local_affine" / "p66_p64_v2_binding_plan.json"


def _module():
    spec = importlib.util.spec_from_file_location("p66_reducer", TARGET)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_runtime_entrypoint_is_importable_without_science_backend():
    module = _module()
    assert callable(module.load_bundle)
    assert callable(module.resolve_states)
    assert callable(module.reduce_states)


def test_runtime_contract_is_bundle_bound_and_zero_side_effect_by_construction():
    source = TARGET.read_text(encoding="utf-8")
    ast.parse(source)
    assert "MEPHC_INPUT_BUNDLE" in source
    assert "MEPHC_RESULT_PATH" in source
    assert "resolve_dataset_record" not in source
    assert "LocalAffineStateProvider" not in source
    assert "MPBLiveSpectralProvider" not in source
    assert "import meep" not in source
    assert "from meep" not in source
    assert ".solve(" not in source
    assert "hashlib.sha256(payload)" in source
    assert "load_binding_plan" in source
    assert "rank1_mixed_curvature" in source
    assert "fixed_q_frequency_derivative" in source
    assert "P66_STATE_ROLE_SET_INVALID" in source
    assert "validate_runtime_contract" in source
    assert "BUNDLE_BOUND_SOLVER_FREE_REDUCTION" in source
    assert "validate_bound_dataset_descriptors" in source


def test_runtime_plan_has_fixed_p64_source_and_thirteen_bindings():
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    assert plan["source_dataset_id"] == "ac421aedcaf748bb0367b92083298e4f4c1d8095f2b5c66b5f2c371b082c8652"
    assert plan["source_manifest_sha256"] == "4c48e0719531848755b58d8cfed1164677fcbe61d3201165cfd87eabde79108d"
    assert len(plan["bindings"]) == 13
