from __future__ import annotations

import json

import pytest

from audit.e9f import c3_c5_runtime as runtime
from tests.test_e9f_c1_rp2_c3_c5 import ROOT


def _without(incident_id: str):
    review = json.loads((ROOT / "audit/e9f/c3_c5_process_reliability_review.json").read_text())
    review["incidents"] = [item for item in review["incidents"] if item["incident_id"] != incident_id]
    review["p1_items"] = [item for item in review["p1_items"] if item != incident_id]
    return review


def test_process_registry_missing_REL027_rejected():
    with pytest.raises(ValueError, match="PROCESS_REGISTRY"):
        runtime.validate_process_review(_without("REL-027"))


def test_process_registry_missing_REL028_rejected():
    with pytest.raises(ValueError, match="PROCESS_REGISTRY"):
        runtime.validate_process_review(_without("REL-028"))


def test_process_registry_missing_REL029_rejected():
    with pytest.raises(ValueError, match="PROCESS_REGISTRY"):
        runtime.validate_process_review(_without("REL-029"))


def test_actual_C3_C5_process_review_validates_required_registry():
    runtime.validate_process_review(json.loads((ROOT / "audit/e9f/c3_c5_process_reliability_review.json").read_text()))


def test_worker_runtime_uses_row_resolution():
    source = (ROOT / "audit/e9f/c3_c5_runtime.py").read_text()
    assert "resolution=int(resolution)" in source
