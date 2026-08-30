from __future__ import annotations

import ast
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "audit" / "local_affine" / "frozen_13_state_solver_free_reduction.py"
PLAN = ROOT / "audit" / "local_affine" / "p66_p64_v2_binding_plan.json"


def test_binding_plan_has_exact_frozen_p64_identity_and_unique_keys():
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    assert plan["source_work_order_id"] == "MEPHC-LOCALAFFINE-P64-FROZEN-13-STATE-LIVE-ACQUISITION-20260830-428"
    assert plan["source_dataset_id"] == "ac421aedcaf748bb0367b92083298e4f4c1d8095f2b5c66b5f2c371b082c8652"
    assert plan["source_manifest_sha256"] == "4c48e0719531848755b58d8cfed1164677fcbe61d3201165cfd87eabde79108d"
    assert len(plan["bindings"]) == 13
    assert len({row["record_key_sha256"] for row in plan["bindings"]}) == 13


def test_reducer_is_solver_free_and_consumes_framework_bundle_only():
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


def test_graph_and_plan_are_both_thirteen_state_artifacts():
    graph = json.loads((ROOT / "audit" / "local_affine" / "p2_frozen_13_state_request_graph.json").read_text(encoding="utf-8"))
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    assert graph["state_count"] == graph["logical_state_count"] == 13
    assert [row["state_id"] for row in plan["bindings"]] == [row["state_id"] for row in graph["states"]]
