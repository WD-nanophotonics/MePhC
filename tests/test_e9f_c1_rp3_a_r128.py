from __future__ import annotations

import ast
import copy
import json
from pathlib import Path

import pytest

from audit.e9f import c3_c5_runtime as c35
from audit.e9f import rp3_a_r128_runtime as rp3
from audit.e9f import rp3_a_r128_runner as runner

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "audit/e9f/rp3_a_r128_execution_contract.json"


def test_fixed_six_r128_plan_and_canary():
    rows = rp3.build_plan(ROOT)
    assert len(rows) == 6
    assert [row["sample_index"] for row in rows] == list(range(6))
    assert all(row["resolution"] == 128 for row in rows)
    assert rows[0]["source_sample_id"] == "fr=0;grid_i=-34;grid_j=-17;estimator=SOURCE_GRID"
    assert runner.CANARY == "fr=0;grid_i=-4;grid_j=0;estimator=SOURCE_GRID"


def test_contract_binds_r128_and_no_reducer():
    contract = json.loads(CONTRACT.read_text())
    assert contract["resolution"] == 128
    assert contract["worker_count"] == 6
    assert contract["authorized_native_solve_count"] == 54
    assert contract["no_new_q_centers"] is True
    assert contract["reducer_admissible"] is False
    assert contract["rp3_reducer_authorized"] is False
    assert contract["rp3_chern_authorized"] is False


def test_actual_provider_constructor_is_row_resolution_and_bounded_gauge():
    source = Path(c35.__file__).read_text()
    tree = ast.parse(source)
    make_provider = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "make_provider")
    make_text = ast.get_source_segment(source, make_provider) or ""
    assert 'resolution=int(resolution)' in make_text
    safe = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_safe_gauge")
    safe_text = ast.get_source_segment(source, safe) or ""
    assert "base @ base.conj().T" not in safe_text
    assert "np.outer" not in safe_text
    assert "np.eye(" not in safe_text


def test_r128_replay_policy_is_not_applicable():
    source = Path(Path(rp3.__file__).resolve().parent / "rp3_a_r128_worker.py").read_text()
    assert "NOT_APPLICABLE_R128" in source
    assert "ORIGINAL_RP2_HAS_NO_R128_KEY" in source


def test_checkpoint_empty_and_fail_closed_mutations(tmp_path):
    rows = rp3.build_plan(ROOT)
    checkpoint = rp3.construct_checkpoint(completed=[], execution_sha="e"*40, contract_sha256="c"*64, policy_sha256="p"*64)
    rp3.validate_checkpoint(checkpoint, root=ROOT, rows=rows)
    bad = copy.deepcopy(checkpoint)
    bad["generation"] = 1
    with pytest.raises(ValueError):
        rp3.validate_checkpoint(bad, root=ROOT, rows=rows)
    bad = copy.deepcopy(checkpoint)
    bad["completed_workers"] = [{"worker_id": rows[0]["sample_id"], "resolution": 96, "payload_path": str(tmp_path/"missing"), "payload_file_sha256": "0"*64, "payload_body_sha256": "0"*64}]
    bad["generation"] = 1
    with pytest.raises(ValueError):
        rp3.validate_checkpoint(bad, root=ROOT, rows=rows, orphan_scan=[])


def test_no_scientific_production_scope_in_rp3_files():
    assert not any(part == "mephc" for path in [Path(runner.__file__), Path(rp3.__file__)] for part in path.parts[-3:-1])
    assert "mephc/" not in (Path(runner.__file__).read_text() + Path(rp3.__file__).read_text())
