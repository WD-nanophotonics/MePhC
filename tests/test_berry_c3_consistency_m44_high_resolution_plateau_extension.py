from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "audit/berry_c3_consistency/m44_high_resolution_plateau_extension.py"
SPEC = importlib.util.spec_from_file_location("m44", SOURCE)
assert SPEC and SPEC.loader
m44 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m44)


def _analysis(value=1.0, eligible=True):
    members = {member: {"rank1_phase_density": {"median": value, "uncertainty": 0.01}, "rank2_trace_phase_density": {"median": value, "uncertainty": 0.01}, "rank1_association": eligible, "rank2_association": {edge: {"state": "CANONICAL_STABLE"} for edge in range(4)}} for member in m44.MEMBERS}
    return {"configuration_id": "SYNTHETIC", "member_summary": members, "rank1_qualification": {"status": "RANK1_QUALIFIED" if eligible else "RANK1_WITHHELD", "stable_band2_association": eligible}, "rank2_association_stable": eligible, "rank1_c3_status": "PASS" if eligible else "RANK1_WITHHELD", "rank2_c3_status": "PASS" if eligible else "FAIL"}


def test_dynamic_high_resolution_layouts_and_graphs():
    for resolution in (160, 192):
        raw = np.zeros((4, resolution * resolution, 2), dtype=np.complex128)
        raw[:, :, 0] = 1.0
        canonical, diagnostics = m44.m41r3._normalize_raw(raw, resolution)
        assert canonical.shape == (4, resolution * resolution, 2)
        assert diagnostics["mode_count"] == resolution * resolution
    centers = {member: [float(i + 1), float(i) + 0.25] for i, member in enumerate(m44.MEMBERS)}
    for name in ("R160_T1E9_M3", "R192_T1E9_M3"):
        graph = m44.high_resolution_graph(name, centers, "a" * 40)
        assert len(graph) == 36
        assert len({row["request_key_sha256"] for row in graph}) == 36
        assert all(row["configuration_id"] != "R128_T1E9_M3" for row in graph)


def test_r192_trigger_uses_scalar_and_status_evidence():
    r128 = _analysis()
    r160 = _analysis(value=9.0)
    trigger, reasons = m44.r192_trigger(r128, r160)
    assert trigger is True
    assert any(reason.startswith("scalar_difference:") for reason in reasons)
    assert m44.r192_trigger(r128, _analysis())[0] is False


def test_plateau_selection_is_direct_and_only_measured():
    r128 = _analysis()
    r160 = _analysis()
    assert m44.plateau(r128, r160) is True
    selected = m44.select_plateau_control(r128, r160, None)
    assert selected["selected_high_resolution_control"] == "R128_T1E9_M3"
    r160_bad = _analysis(value=9.0)
    r192 = _analysis(value=9.0)
    selected = m44.select_plateau_control(r128, r160_bad, r192)
    assert selected["R128_R160_plateau"] is False
    assert selected["R160_R192_plateau"] is True
    assert selected["selected_high_resolution_control"] == "R160_T1E9_M3"


def test_contract_has_conditional_r192_and_zero_old_reacquisition():
    source = SOURCE.read_text(encoding="utf-8")
    assert "R192" in source and "r192_trigger" in source
    assert "resolution=160" in source and "resolution=192" in source
    assert "Persist every completed state" in source or "store.put" in source
    assert "m41r3._capture" in source
    assert "C3_COVARIANT" in source and "deterministic=True" in source

