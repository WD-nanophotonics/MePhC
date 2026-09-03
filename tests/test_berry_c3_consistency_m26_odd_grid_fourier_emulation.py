from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "audit" / "berry_c3_consistency" / "m26_odd_grid_fourier_emulation_and_h_sampling_discrimination.py"
SPEC = importlib.util.spec_from_file_location("m26_test_module", PATH)
assert SPEC is not None and SPEC.loader is not None
M26 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M26)


def test_contract_is_solver_free_and_existing_data_only():
    source = PATH.read_text(encoding="utf-8")
    assert '"native_invocation_count": 0' in source
    assert "MEPHC_INPUT_BUNDLE" in source and "MEPHC_RESULT_PATH" in source
    assert "common_support" in source and "orbit_complete_support" in source
    assert "fresh odd-grid eigensolve" in source


def test_common_support_counts_are_exact_for_neighboring_grids():
    assert len(M26.common_support(127)) == 127 * 127
    assert len(M26.common_support(129)) == 128 * 128
    assert len(M26.common_support(128)) == 128 * 128


def test_integer_label_embedding_round_trips_known_coefficients():
    field = np.zeros((128, 128, 3), dtype=complex)
    field[2, 3, 0] = 1.0
    coeff = np.fft.fftn(field, axes=(0, 1))
    support = {(0, 0), (2, 3), (-2, -3)}
    embedded = M26.embed_coefficients(coeff, 127, support)
    recovered = np.fft.fftn(np.fft.ifftn(embedded, axes=(0, 1)), axes=(0, 1)) / (127 / 128) ** 2
    source_modes = M26.signed_modes(128); target_modes = M26.signed_modes(127)
    for mode in support:
        assert np.allclose(recovered[target_modes.index(mode[0]), target_modes.index(mode[1])], coeff[source_modes.index(mode[0]), source_modes.index(mode[1])])


def test_mode_support_is_not_residual_selected():
    source = PATH.read_text(encoding="utf-8")
    assert "residual" not in source.split("def common_support", 1)[1].split("def embed_coefficients", 1)[0]
    assert "special_modes_removed_counterfactual_metrics" in source


def test_shells_are_preregistered_and_metrics_are_low_rank():
    assert M26.SHELLS == (8, 16, 24, 32, 48, 64)
    source = PATH.read_text(encoding="utf-8")
    assert "_rank2_metrics" in source
    assert "49152x49152" not in source
