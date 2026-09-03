"""M15 exact lattice/FFT representation tests, all solver-free."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / "audit" / "berry_c3_consistency" / "m15_discrete_fft_maxwell_covariance_audit.py"
SPEC = importlib.util.spec_from_file_location("berry_c3_m15", ENTRYPOINT)
assert SPEC and SPEC.loader
M15 = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(M15)


def test_canonical_lattice_automorphisms_are_integer_dual_and_order_three():
    values = M15.lattice_automorphisms()
    assert np.array_equal(values["c3_direct_integer_automorphism"] @ values["c3_direct_integer_automorphism"] @ values["c3_direct_integer_automorphism"], np.eye(2, dtype=int))
    assert np.array_equal(values["c3_reciprocal_integer_automorphism"] @ values["c3_reciprocal_integer_automorphism"] @ values["c3_reciprocal_integer_automorphism"], np.eye(2, dtype=int))
    assert values["direct_reconstruction_residual"] <= 1e-12
    assert values["reciprocal_reconstruction_residual"] <= 1e-12


def test_fft_mode_map_is_bijective_and_cubed_identity():
    values = M15.lattice_automorphisms(); shape = (16, 16); first = M15.fft_mode_permutation(shape, values["c3_reciprocal_integer_automorphism"])
    assert M15.mode_permutation_is_bijective(first, shape)
    second = M15.fft_mode_permutation(shape, values["c3_reciprocal_integer_automorphism"] @ values["c3_reciprocal_integer_automorphism"])
    composed = np.empty_like(first)
    for i in range(shape[0]):
        for j in range(shape[1]):
            p = first[i, j]; composed[i, j] = first[p[0], p[1]]
    # Three applications of the fixed automorphism return every mode.
    third = M15.fft_mode_permutation(shape, values["c3_reciprocal_integer_automorphism"] @ values["c3_reciprocal_integer_automorphism"] @ values["c3_reciprocal_integer_automorphism"])
    assert np.array_equal(third, np.indices((shape[0], shape[1])).transpose(1, 2, 0))
    assert not np.array_equal(first, M15.fft_mode_permutation(shape, values["c3_reciprocal_integer_automorphism"].T))


def test_fft_and_real_space_actions_agree_on_scalar_multimode_and_vector_fixture():
    result = M15.synthetic_representation_validation()
    assert result["scalar_fft_vs_real_space_residual"] <= 1e-12
    assert result["cartesian_vector_fft_vs_real_space_residual"] <= 1e-12
    assert result["scalar_c3_cubed_residual"] <= 1e-12
    assert result["mode_permutation_bijection_status"] == "PASS"


def test_fft_conventions_are_explicit_and_solver_free():
    source = ENTRYPOINT.read_text(encoding="utf-8")
    assert "import meep" not in source
    assert "MPBLiveEnergySpectralProvider" not in source
    assert "ImmutableDatasetStore" not in source
    assert "provider.solve(" not in source
    assert "numpy fftn forward exp(-2pi*i*m.x)" in source


def test_actual_child_entrypoint_emits_structured_result_without_generic_masking(tmp_path, monkeypatch):
    bundle = tmp_path / "bundle.json"
    output = tmp_path / "result.json"
    counters = tmp_path / "counters.json"
    bundle.write_text(json.dumps({"work_order_id": "MEPHC-BERRY-C3-M15R1-TEST-00000000"}), encoding="utf-8")
    counters.write_text("{}", encoding="utf-8")
    expected = {"schema": M15.RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS", "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0}
    monkeypatch.setenv("MEPHC_INPUT_BUNDLE", str(bundle))
    monkeypatch.setenv("MEPHC_RESULT_PATH", str(output))
    monkeypatch.setenv("MEPHC_EXECUTION_COUNTERS_PATH", str(counters))
    monkeypatch.setattr(M15, "read_dataset", lambda *_args: [])
    monkeypatch.setattr(M15, "analyze", lambda *_args: expected)
    assert M15.main() == 0
    emitted = json.loads(output.read_text(encoding="utf-8"))
    assert emitted == expected
    assert emitted["status"] == "PASS"
