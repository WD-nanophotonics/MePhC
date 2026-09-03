"""Solver-free M14 tests for reciprocal folding and gauge sign."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / "audit" / "berry_c3_consistency" / "m14_reciprocal_folding_gauge_phase_audit.py"
SPEC = importlib.util.spec_from_file_location("berry_c3_m14", ENTRYPOINT)
assert SPEC and SPEC.loader
M14 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M14)


def _record(member, coordinate):
    return {"member_index": member, "c3_member_identity": ("IDENTITY", "C3", "C3_SQUARED")[member], "coordinate": coordinate}


def test_reciprocal_basis_reconstructs_all_three_nonzero_folding_edges():
    q0 = np.asarray([17.0 / 36.0, 0.0])
    q1 = np.asarray([55.0 / 72.0, -7.0 * np.sqrt(3.0) / 72.0])
    q2 = np.asarray([55.0 / 72.0, 7.0 * np.sqrt(3.0) / 72.0])
    edges = M14.derive_reciprocal_folding_edges([_record(0, q0.tolist()), _record(1, q1.tolist()), _record(2, q2.tolist())])
    assert [item["reciprocal_folding_integer_coefficients"] for item in edges] == [[-1, 0], [-1, 0], [-1, 0]]
    assert max(item["folding_reconstruction_residual"] for item in edges) <= 1e-12


def test_bloch_convention_derives_plus_sign_without_overlap_selection():
    convention = M14.full_bloch_convention()
    assert "u_target(r)=exp(+i G dot r)" in convention["representative_relation"]
    assert convention["authoritative_gauge_phase_formula"] == "exp(+i G dot r)"
    assert "overlap" not in convention["sign_derivation"]


def test_nonzero_g_fixture_distinguishes_plus_minus_and_no_phase():
    validation = M14.synthetic_nonzero_g_validation()
    assert validation["plus_sign_is_analytically_selected"]
    assert validation["plus_sign_residual"] <= 1e-12
    assert validation["minus_sign_residual"] > 1e-6
    assert validation["no_phase_residual"] > 1e-6


def test_gauge_phase_is_unitary_and_applies_to_both_eh_blocks():
    shape = (4, 4)
    phase = M14.folding_phase(shape, (1, -1), 1)
    assert np.allclose(np.abs(phase), 1.0, rtol=0.0, atol=1e-12)
    assert phase.size * 6 == 2 * shape[0] * shape[1] * 3
    assert "tau=0" in M14.full_bloch_convention()["seitz_phase_distinction"]


def test_m14_is_solver_free_and_writes_no_dataset():
    source = ENTRYPOINT.read_text(encoding="utf-8")
    assert "import meep" not in source
    assert "provider.solve(" not in source
    assert "ImmutableDatasetStore" not in source
    assert "BudgetCounter" not in source
    assert "MPBLiveEnergySpectralProvider" not in source
