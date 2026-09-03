from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "audit" / "berry_c3_consistency" / "m28_h_point_array_sampling_raw_fourier_metadata.py"
SPEC = importlib.util.spec_from_file_location("m28_test_module", PATH)
assert SPEC is not None and SPEC.loader is not None
M28 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M28)


def test_contract_is_bounded_to_existing_triplet_and_result_channel():
    source = PATH.read_text(encoding="utf-8")
    assert "MEPHC_INPUT_BUNDLE" in source and "MEPHC_RESULT_PATH" in source
    assert "run_parity" in source and "get_field_point" in source
    assert "new_metadata_record_count" in source


def test_preregistered_stencil_is_fixed_and_bounded():
    assert len(M28.STENCIL) == 8
    assert M28.STENCIL[0] == (0, 0) and M28.STENCIL[-1] == (127, 127)


def test_point_arguments_use_both_candidate_charts_without_authority_guess():
    source = PATH.read_text(encoding="utf-8")
    assert "index_over_N" in source and "index_plus_half_over_N" in source
    assert "NO_UNIQUE_CORRECTION_ESTABLISHED" in source


def test_h_array_shape_guard_is_exact():
    value = np.zeros((128, 128, 3), dtype=complex)
    assert M28._array(value).shape == (128, 128, 3)
