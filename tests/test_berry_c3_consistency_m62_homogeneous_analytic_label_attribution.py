from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "audit/berry_c3_consistency/m62_homogeneous_analytic_label_attribution.py"
SPEC = importlib.util.spec_from_file_location("m62_test_module", SOURCE)
assert SPEC and SPEC.loader
m62 = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(m62)


def test_gamma_catalog_preserves_degenerate_label_multiplicity():
    catalog = m62._catalog_for_coordinate([0.0, 0.0])
    assert len(catalog["shells"][1]["labels"]) == 6


def test_assignment_interval_requires_unique_shell_and_reports_unmatched():
    catalog = {"shells": [{"shell_index": 1, "frequency": 1.0, "labels": [[0, 0]]}, {"shell_index": 2, "frequency": 2.0, "labels": [[1, 0]]}]}
    assert m62.assign_band(1.0, 0.0, catalog)["status"] == "DEFINITE"
    assert m62.assign_band(1.5, 0.0, catalog)["status"] == "UNMATCHED_ANALYTIC_VALUE"
    catalog["shells"][1]["frequency"] = 1.0
    assert m62.assign_band(1.0, 0.0, catalog)["status"] == "AMBIGUOUS_ANALYTIC_SHELL"


def test_c3_label_transport_uses_integer_reciprocal_edge():
    source = np.asarray([[0, 0], [1, 0], [0, 1]])
    result = m62.c3_label_transport(source.tolist(), [0.31, 0.17], m62.R3 @ np.asarray([0.31, 0.17]))
    expected = (np.asarray(result["S_recip"], dtype=int) @ source.T).T.tolist()
    assert result["G_edge"] == [0, 0] and result["mapped_labels"] == expected


def test_old_zero_uncertainty_ledger_differs_from_machine_assignment_guard():
    source = {"assignment": {"status": "DEFINITE", "shell": {"shell_index": 1, "labels": [[0, 0]]}}}; target = {"assignment": {"status": "DEFINITE", "shell": {"shell_index": 1, "labels": [[0, 0]]}}}
    assert m62.classify_attribution({}, source, target) == "SAME_SHELL_VALUE_DEFORMATION"


def test_all_mechanism_outcomes_are_explicit():
    assert m62.classify_outcome([])[0] == "R256_M61R1_HOMOGENEOUS_FAILURE_NOT_REPRODUCED"
    assert m62.classify_outcome([{"mechanism": "LABEL_SELECTION_BREAK"}])[0] == "R256_HOMOGENEOUS_C3_BREAK_RECIPROCAL_LABEL_SELECTION"
    assert m62.classify_outcome([{"mechanism": "SAME_SHELL_VALUE_DEFORMATION"}])[0] == "R256_HOMOGENEOUS_C3_BREAK_SAME_SHELL_VALUE_DEFORMATION"
    assert m62.classify_outcome([{"mechanism": "LABEL_SELECTION_BREAK"}, {"mechanism": "SAME_SHELL_VALUE_DEFORMATION"}])[0] == "R256_HOMOGENEOUS_C3_BREAK_MIXED_SELECTION_AND_VALUE_DEFORMATION"
    assert "native_invocation_count" in SOURCE.read_text(encoding="utf-8")
