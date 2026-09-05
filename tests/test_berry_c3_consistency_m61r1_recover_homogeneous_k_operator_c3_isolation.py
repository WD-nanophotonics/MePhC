from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "audit/berry_c3_consistency/m61r1_recover_homogeneous_k_operator_c3_isolation.py"
SPEC = importlib.util.spec_from_file_location("m61r1_test_module", SOURCE)
assert SPEC and SPEC.loader
m61r1 = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(m61r1)


def _graph():
    base = [np.asarray([0.31, 0.17]), np.asarray([0.22, -0.11]), np.asarray([-0.13, 0.29]), np.asarray([0.07, -0.23])]
    rows = {}
    for vertex, k in enumerate(base):
        for member_index, member in enumerate(m61r1.MEMBERS):
            coordinate = k.copy()
            for _ in range(member_index): coordinate = m61r1.R3 @ coordinate
            for repeat in range(3): rows[(vertex, repeat, member)] = {"vertex_index": vertex, "repeat_index": repeat, "c3_member_identity": member, "coordinate": coordinate.tolist(), "frequencies_bands_1_to_4": [1.0, 2.0, 3.0, 4.0]}
    return rows


def test_real_analytic_reference_passes_floating_c3_graph():
    reference = m61r1.analytic_reference(_graph())
    assert reference["status"] == "PASS" and reference["analytic_c3_ledger"]["failure_count"] == 0


def test_coordinate_orbit_audit_reports_integer_reciprocal_edges():
    audit = m61r1.coordinate_orbit_audit(_graph())
    assert audit["status"] == "PASS" and all(edge["pass"] for edge in audit["edges"])


def test_above_guard_coordinate_perturbation_fails_without_refitting():
    rows = _graph(); rows[(0, 0, "C3")]["coordinate"][0] += 1e-5
    assert m61r1.coordinate_orbit_audit(rows)["status"] == "FAIL"


def test_machine_identity_ledger_rejects_zero_uncertainty_bug_boundary():
    spectra = {(vertex, member): [1.0 + (1e-15 if member == "C3" else 0.0), 2.0, 3.0, 4.0] for vertex in range(4) for member in m61r1.MEMBERS}
    analytic = m61r1.analytic_identity_ledger(spectra)
    assert analytic["failure_count"] == 0
    experimental = m61r1.experimental_frequency_ledger({(v, r, member): {"frequencies_bands_1_to_4": spectra[(v, member)]} for v in range(4) for r in range(3) for member in m61r1.MEMBERS})
    assert experimental["failure_count"] > 0


def test_convergence_preserves_gamma_multiplicity_and_no_raw_science():
    values = m61r1.reciprocal_spectrum([0.0, 0.0], 4); assert len(values) == 4 and values[1] == values[2] == values[3]
    text = SOURCE.read_text(encoding="utf-8")
    assert "geometry=[]" in text and "Cylinder" not in text and "Wilson" not in text and "Berry" not in text
