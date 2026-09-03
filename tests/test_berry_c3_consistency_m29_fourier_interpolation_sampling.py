from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "audit" / "berry_c3_consistency" / "m29_recovered_point_array_fourier_interpolation_sampling_closure.py"
SPEC = importlib.util.spec_from_file_location("m29_test_module", PATH)
assert SPEC is not None and SPEC.loader is not None
M29 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M29)


def test_unshifted_fourier_reconstruction_preserves_complex_vector_modes():
    array = np.zeros((M29.N, M29.N, 3), dtype=np.complex128)
    for x in range(M29.N):
        for y in range(M29.N):
            phase = np.exp(2j * np.pi * (3 * x / M29.N + 5 * y / M29.N))
            array[x, y] = phase * np.asarray([1 + 2j, -2 + 0.5j, 0.25 - 3j])
    predicted = M29.reconstruct_from_array(array, (7 / M29.N, 11 / M29.N))
    expected = np.exp(2j * np.pi * (3 * 7 / M29.N + 5 * 11 / M29.N)) * np.asarray([1 + 2j, -2 + 0.5j, 0.25 - 3j])
    assert np.allclose(predicted, expected, rtol=0, atol=1e-12)


def test_candidate_offsets_are_preregistered_and_no_fit_parameters_exist():
    assert M29.OFFSETS == ((0.0, 0.0), (0.5, 0.0), (0.0, 0.5), (0.5, 0.5))
    source = PATH.read_text(encoding="utf-8")
    assert "np.linalg.lstsq" not in source and "scipy.optimize" not in source


def test_recovered_m28_and_m18_analysis_is_zero_execution_and_three_member_only():
    job_spec = importlib.util.spec_from_file_location("m29_job", ROOT / "tools" / "mephc-flow" / "scientific_job.py")
    assert job_spec is not None and job_spec.loader is not None
    job = importlib.util.module_from_spec(job_spec)
    job_spec.loader.exec_module(job)
    if not Path("/home/icy/.local/state/mephc-runner/MEPHC/flow").exists():
        pytest.skip("WSL durable state is unavailable")
    result = M29.analyze(job, Path("/home/icy/.local/state/mephc-runner/MEPHC/flow"), "M29-TEST")
    assert result["recovered_m28_record_count"] == 3
    assert result["member_identities"] == ["IDENTITY", "C3", "C3_SQUARED"]
    assert result["native_invocation_count"] == result["provider_execution_count"] == result["solver_execution_count"] == 0
    assert result["new_dataset_record_count"] == 0
