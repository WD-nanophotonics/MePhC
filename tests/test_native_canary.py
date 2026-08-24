import ast
import json
from pathlib import Path

import pytest

from audit.infrastructure.native_canary import build_plan, load_contract, validate_child
from audit.infrastructure.campaign_runtime import CampaignRuntimeError


def test_parent_module_has_no_top_level_native_import():
    path = Path(__file__).parents[1] / "audit" / "infrastructure" / "native_canary.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
    assert not any("meep" in name.lower() or "mpb" in name.lower() for name in imports)


def test_canary_plan_is_small_and_fixed():
    root = Path(__file__).parents[1]
    contract = load_contract(root)
    rows = build_plan(contract)
    assert [row["sample_id"] for row in rows] == [
        "native_canary_0", "native_canary_1", "native_canary_2"
    ]
    assert all(row["public_q"] == [0.17, 0.23] for row in rows)


def test_equal_child_coordinate_is_accepted():
    root = Path(__file__).parents[1]
    row = build_plan(load_contract(root))[0]
    payload = {"sample_id": row["sample_id"], "sample_index": 0,
               "native_import_confirmed": True,
               "WORKER_COORDINATE_USED": [0.17, 0.23],
               "frequency_vector": [1.0, 2.0]}
    validate_child(row, payload)


def test_different_or_missing_child_coordinate_fails_closed():
    root = Path(__file__).parents[1]
    row = build_plan(load_contract(root))[0]
    base = {"sample_id": row["sample_id"], "sample_index": 0,
            "native_import_confirmed": True, "frequency_vector": [1.0, 2.0]}
    with pytest.raises(CampaignRuntimeError, match="COORDINATE_MISSING"):
        validate_child(row, base)
    base["WORKER_COORDINATE_USED"] = [0.18, 0.23]
    with pytest.raises(CampaignRuntimeError, match="COORDINATE_MISMATCH"):
        validate_child(row, base)
