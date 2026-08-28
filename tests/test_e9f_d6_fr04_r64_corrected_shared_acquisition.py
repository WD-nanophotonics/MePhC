import ast
import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "audit" / "e9f" / "d6_fr04_r64_corrected_shared_acquisition.py"


def load_module():
    spec = importlib.util.spec_from_file_location("d6_acquisition_test_module", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_d6_entrypoint_is_frozen_to_corrected_shared_acquisition():
    source = SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert sum(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "solve" for node in ast.walk(tree)) == 1
    assert "d3_fr04_r64_shared_acquisition" not in source
    assert "d5r3_fr04_corrected_k_replay" not in source
    assert "full-grid" not in source.lower()
    assert "rank2" not in source.lower()


def test_d6_constants_and_namespace_are_distinct():
    module = load_module()
    assert module.WORK_ORDER_ID.endswith("-331")
    assert module.SOURCE_MODEL_IDENTITY == "E9E_FR04_ROUNDED_TRIANGLE_V1"
    assert module.GRAPH_SHA256 == "44ae0ce1cc56c169c499d6957700da40f7d3431f3c96dda68e8ab879d03533a0"
    assert module.UNIQUE_COUNT == 3205
    assert module.ARC_SEGMENTS == 96
