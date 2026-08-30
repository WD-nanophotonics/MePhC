from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "audit" / "local_affine" / "frozen_13_state_solver_free_reduction.py"
PLAN = ROOT / "audit" / "local_affine" / "p66_p64_v2_binding_plan.json"


def test_reducer_implements_bound_identity_validation_not_placeholder_defaults():
    source = TARGET.read_text(encoding="utf-8")
    ast.parse(source)
    assert "P66_CANONICAL_STATE_IDENTITY_MISSING" in source
    assert "P66_REFERENCE_CELL_CONTRACT_MISSING" in source
    assert "P66_STATE_ROLE_COORDINATE_MISMATCH" in source
    assert "decode_snapshot(payload)" in source
    assert "Path(result_path).write_text" in source
    assert "local-affine-bound" not in source
    assert "certified-common-reference-cell" not in source


def test_all_plan_record_keys_are_canonical_sha256_bindings():
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    for binding in plan["bindings"]:
        identity = {
            "work_order_id": plan["source_work_order_id"],
            "state_id": binding["state_id"],
            "role": binding["role"],
            "public_q": binding["public_q"],
            "s": binding["s"],
        }
        encoded = json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        assert hashlib.sha256(encoded).hexdigest() == binding["record_key_sha256"]


def test_reducer_reports_only_zero_execution_counters():
    source = TARGET.read_text(encoding="utf-8")
    assert '"native_invocation_count": 0' in source
    assert '"provider_request_count": 0' in source
    assert '"solver_execution_count": 0' in source
    assert '"mpb_execution": False' in source
