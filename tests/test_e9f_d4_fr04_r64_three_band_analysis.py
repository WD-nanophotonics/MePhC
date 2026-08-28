import ast
import json
from pathlib import Path

import pytest

from mephc.valley_integration import SOURCE_GRID_MIDPOINT_V1, build_berry_row, build_integration_plan, build_source_bound_domain, reduce_supplied_berry_rows


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "audit" / "e9f" / "d4_fr04_r64_three_band_analysis.py"
DOMAIN = ROOT / "audit" / "e9f" / "d1_fr04_source_grid_domain.json"


def load_module():
    pytest.importorskip("scipy")
    namespace = {"__file__": str(SCRIPT), "__name__": "d4_test_module"}
    exec(compile(SCRIPT.read_text(encoding="utf-8"), str(SCRIPT), "exec"), namespace)
    return namespace


def test_entrypoint_is_zero_argument_and_forbids_live_creation_tokens():
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main")
    assert not main.args.args and not main.args.vararg and not main.args.kwarg
    text = SCRIPT.read_text(encoding="utf-8").lower()
    assert "provider factory" not in text
    assert "meep" not in text
    assert "adaptive" not in text
    assert "zero_fill" not in text


def test_plan_is_exact_frozen_source_domain():
    module = load_module()
    domain = json.loads(DOMAIN.read_text(encoding="utf-8"))
    plan = module["make_plan"](domain)
    assert plan["ESTIMATOR_ID"] == SOURCE_GRID_MIDPOINT_V1
    assert plan["SAMPLE_COUNT"] == 641
    assert all(row["WEIGHT_Q2"] == 1.0 / 1296.0 for row in plan["ROWS"])


def test_reducer_is_fail_closed_for_missing_berry():
    domain_plan = build_integration_plan(build_source_bound_domain(0.4), SOURCE_GRID_MIDPOINT_V1)
    row = domain_plan["ROWS"][0]
    rows = [build_berry_row(domain_plan, item, 2, "QUALIFIED_REPORTED", omega_q=0.0) for item in domain_plan["ROWS"]]
    rows[0] = build_berry_row(domain_plan, row, 2, "NOT_REPORTED_WITH_REASON", reason="EXTERNAL_ISOLATION_GAP_FAILED")
    reduced = reduce_supplied_berry_rows(domain_plan, rows, 2)
    assert reduced["COMPLETE_STATUS"] == "INCOMPLETE_NOT_REPORTED"
    assert reduced["VALLEY_CHERN"] == "NOT_EMITTED"
    assert reduced["FLUX_Q"] == "NOT_EMITTED"


def test_output_artifacts_are_bounded_if_present():
    for path in (
        ROOT / "audit" / "e9f" / "d4_fr04_r64_three_band_qualification_berry.json",
        ROOT / "audit" / "e9f" / "d4_fr04_r64_source_grid_reduction.json",
    ):
        if not path.exists():
            continue
        value = json.loads(path.read_text(encoding="utf-8"))
        text = path.read_text(encoding="utf-8").lower()
        assert "h_fields" not in text and "normalized_vectors" not in text
        assert "/home/" not in text and "c:\\users\\" not in text
        if "rows" in value:
            assert len(value["rows"]) == 641 * 3
