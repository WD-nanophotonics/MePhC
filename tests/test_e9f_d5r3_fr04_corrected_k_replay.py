import ast
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "audit" / "e9f" / "d5r3_fr04_corrected_k_replay.py"
RECONCILIATION = ROOT / "audit" / "e9f" / "d5r2_fr04_validation_state_reconciliation.json"


def load_module():
    spec = importlib.util.spec_from_file_location("d5r3_replay_test_module", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_entrypoint_is_fresh_and_bounded():
    source = SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = [node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)]
    assert calls.count("solve") == 1
    assert "run_e9f_c1" not in source
    assert "d5_fr04_source_binding_validation" not in source
    for forbidden in ("berry", "chern", "wilson", "qualification", "full-grid"):
        assert forbidden not in source.lower()


def test_frozen_reconciliation_authorizes_only_one_replay():
    value = json.loads(RECONCILIATION.read_text(encoding="utf-8"))
    assert value["original_d5_lineage_reconciliation_status"] == "PASS_ZERO_PROVIDER_ZERO_SOLVER_NO_DATASET"
    assert value["one_fresh_corrected_k_replay_can_be_authorized"] is True
    assert value["original_d5_provider_request_count"] == 0
    assert value["original_d5_solver_execution_count"] == 0
    assert value["original_d5_validation_dataset_count"] == 0


def test_constants_bind_corrected_public_k():
    module = load_module()
    assert module.WORK_ORDER_ID == "MEPHC-E9F-D5R3-FR04-CORRECTED-K-REPLAY-20260829-329"
    assert module.PUBLIC_K == (2.0 / 3.0, 0.0)
    assert module.PUBLIC_Q == {"i": 96, "j": 0, "denominator": 144}
    assert module.FR == 0.4
    assert module.ARC_SEGMENTS == 96
    assert module.NUM_BANDS == 6
