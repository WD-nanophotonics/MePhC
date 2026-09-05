from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]; SOURCE = ROOT / "audit/berry_c3_consistency/m63_homogeneous_raw_support_tolerance_adjudication.py"; SPEC = importlib.util.spec_from_file_location("m63_test_module", SOURCE); assert SPEC and SPEC.loader
m63 = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(m63)


def test_all_three_committed_raw_layouts_normalize_to_canonical_shape():
    raw = np.zeros((4, m63.P, 2), complex)
    for shape in ((m63.P, 2, 4), (4, m63.P, 2), (4, 2, m63.P)):
        source = np.transpose(raw, (1, 2, 0)) if shape == (m63.P, 2, 4) else np.transpose(raw, (0, 2, 1)) if shape == (4, 2, m63.P) else raw
        normalized, info = m63.normalize_raw(source); assert normalized.shape == (4, m63.P, 2) and info["canonical_shape"] == [4, m63.P, 2]


def test_degenerate_shell_power_keeps_multiplicity_and_uses_machine_tie_only():
    catalog = {"shells": [{"shell_index": 1, "frequency": 0.0, "labels": [[0, 0], [0, 1]]}, {"shell_index": 2, "frequency": 1.0, "labels": [[1, 0]]}]}; raw = np.zeros((4, m63.P, 2), complex); raw[:, 0, 0] = 1.0; support = m63.shell_support(raw, catalog); assert len(support["bands"][0]["shells"][0]["labels"]) == 2 and support["bands"][0]["status"] in {"DEFINITE", "AMBIGUOUS_RAW_SHELL"}


def test_tolerance_logic_requires_strict_two_step_improvement():
    metrics = [{"max_member_absolute_analytic_error": 3.0, "max_directed_c3_residual": 2.0}, {"max_member_absolute_analytic_error": 2.0, "max_directed_c3_residual": 1.0}, {"max_member_absolute_analytic_error": 1.0, "max_directed_c3_residual": 0.5}]; assert m63.tolerance_assessment(metrics, {"max_member_absolute_analytic_error": 0.1, "max_directed_c3_residual": 0.1}) == "TOLERANCE_SENSITIVE"


def test_mechanism_classification_is_explicit_and_no_patterned_science():
    assert m63.classify_raw({"RAW_RECIPROCAL_SELECTION_BREAK"})[0] == "R256_HOMOGENEOUS_RAW_RECIPROCAL_LABEL_SELECTION_BREAK"; assert m63.classify_raw({"RAW_SAME_SHELL_VALUE_DEFORMATION"}, "TOLERANCE_INSENSITIVE")[0] == "R256_HOMOGENEOUS_RAW_SAME_SHELL_VALUE_DEFORMATION_TOLERANCE_INSENSITIVE"; text = SOURCE.read_text(encoding="utf-8"); assert "geometry=[]" in text and "Cylinder" not in text and "Berry" not in text and "Wilson" not in text

