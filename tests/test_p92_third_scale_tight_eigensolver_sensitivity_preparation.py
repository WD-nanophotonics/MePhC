from __future__ import annotations

import importlib.util
import json
import py_compile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "audit" / "local_affine" / "third_scale_6_state_tight_eigensolver_live_acquisition.py"
GRAPH = ROOT / "audit" / "local_affine" / "p84_third_scale_6_state_request_graph.json"


def _module():
    spec = importlib.util.spec_from_file_location("p92_acquisition", TARGET)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_graph_coordinates_and_order_match_the_frozen_six_state_graph():
    module = _module()
    graph = json.loads(GRAPH.read_text(encoding="utf-8"))
    assert module.STATE_ORDER == tuple(item["state_id"] for item in graph["states"])
    assert [item["public_q"] for item in graph["states"]] == [
        [0.00025, -0.6166666666666667], [-0.00025, -0.6166666666666667],
        [0.0, -0.6164166666666667], [0.0, -0.6169166666666667],
        [0.0, -0.6166666666666667], [0.0, -0.6166666666666667],
    ]
    assert [item["s"] for item in graph["states"]] == [0.0, 0.0, 0.0, 0.0, 0.005, -0.005]


def test_only_eigensolver_tolerance_differs_from_the_frozen_solver_configuration():
    module = _module()
    baseline = {
        "resolution": 64, "num_bands": 6, "polarization": "TM",
        "eigensolver_tolerance": 1e-7, "mesh_size": 3,
        "deterministic": True, "phase_callback": None,
    }
    assert module.SOLVER_CONFIGURATION.keys() == baseline.keys()
    for key, value in baseline.items():
        if key == "eigensolver_tolerance":
            assert module.SOLVER_CONFIGURATION[key] == 1e-9
        else:
            assert module.SOLVER_CONFIGURATION[key] == value


def test_future_budget_is_exactly_one_six_six_and_framework_budget_is_separate():
    module = _module()
    assert module.validate_acquisition_budgets({"native_invocations": 1, "provider_requests": 6, "solver_executions": 6})
    assert module.validate_framework_budgets({"MEPHC_PROVIDER_REQUEST_BUDGET": "6", "MEPHC_SOLVER_EXECUTION_BUDGET": "6"}) == {"provider_requests": 6, "solver_executions": 6}
    with pytest.raises(RuntimeError):
        module.validate_acquisition_budgets({"native_invocations": 1, "provider_requests": 5, "solver_executions": 6})


def test_record_key_derivation_is_deterministic_and_work_order_bound():
    module = _module()
    args = ("MEPHC-LOCALAFFINE-P92-FUTURE", "STATE_14", "THIRD_PLUS_QX", (0.00025, -0.6166666666666667), 0.0)
    assert module.derive_record_key_sha256(*args) == module.derive_record_key_sha256(*args)
    assert module.derive_record_key_sha256(*args) != module.derive_record_key_sha256("OTHER", *args[1:])


def test_rank1_qualification_does_not_replace_dataset_completeness():
    module = _module()
    assert module.rank1_preflight(0.05) is True
    assert module.rank1_preflight(0.049999) is False
    assert module.solver_free_reduction_ready(6, True) is True
    assert module.solver_free_reduction_ready(5, True) is False
    assert module.solver_free_reduction_ready(6, False) is False


def test_graph_is_read_only_and_future_entrypoint_has_no_old_dataset_substitution():
    module = _module()
    graph, digest = module.load_graph({"request_graph_sha256": module.sha256_file(GRAPH)})
    assert len(graph["states"]) == 6
    assert digest == module.sha256_file(GRAPH)
    source = TARGET.read_text(encoding="utf-8").lower()
    assert "third_scale_6_state_live_acquisition.py" not in source
    assert "p85" not in source
    assert "archived runtime" not in source


def test_entrypoint_compiles_and_preserves_future_snapshot_guards():
    module = _module()
    assert module.normalize_json((1, (2, 3))) == [1, [2, 3]]
    py_compile.compile(str(TARGET), doraise=True)
    source = TARGET.read_text(encoding="utf-8")
    for required in (
        "isinstance(spec.geometry, tuple)", "identity_before == identity_after",
        "encode_snapshot", "rank1_preflight_threshold", "solver_free_reduction_ready",
        "eigensolver_tolerance=1e-9",
    ):
        assert required in source
