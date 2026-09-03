from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "audit" / "berry_c3_consistency" / "m24_actual_hfield_operator_equivalence_and_fourier_localization.py"
SPEC = importlib.util.spec_from_file_location("m24_test_module", PATH)
assert SPEC is not None and SPEC.loader is not None
M24 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M24)


def test_contract_is_solver_free_and_has_result_channel():
    source = PATH.read_text(encoding="utf-8")
    assert "MEPHC_INPUT_BUNDLE" in source and "MEPHC_RESULT_PATH" in source
    assert '"native_invocation_count": 0' in source
    assert "direct_reciprocal_coefficient_transform" in source
    assert "49152x49152" not in source


def test_direct_coefficient_transform_matches_validated_grid_transform():
    m15 = M24._m15()
    lattice = m15.lattice_automorphisms()
    x, y = np.meshgrid(np.arange(128) / 128, np.arange(128) / 128, indexing="ij")
    field = np.stack([np.exp(2j * np.pi * (5 * x - 9 * y)), np.exp(2j * np.pi * (3 * x + 7 * y)), np.ones_like(x)], axis=-1)
    direct = M24.direct_reciprocal_coefficient_transform(field, lattice["c3_reciprocal_integer_automorphism"], (2, -1), m15)
    expected = m15.fft_transform(field, (128, 128), lattice["c3_reciprocal_integer_automorphism"], (2, -1), m15.R3)
    assert np.max(np.abs(direct - expected)) <= 1e-12


def test_basis_invariant_residual_is_thin_and_fourier_localized():
    rng = np.random.default_rng(24)
    target = rng.normal(size=(128, 128, 3, 2)) + 1j * rng.normal(size=(128, 128, 3, 2))
    transformed = [target + 0.1 * np.roll(target, 3, axis=0)]
    rows, status = M24._residual_localization(transformed, [target])
    assert len(rows) == 1
    assert rows[0]["residual_norm_fraction"] > 0.0
    assert status in {"BROAD_RECIPROCAL_SPACE_RESIDUAL_WITH_OPERATOR_MAPPING_CORRECT", "RESIDUAL_CONCENTRATED_AT_NYQUIST_OR_WRAP_MODES_WITH_OPERATOR_MAPPING_CORRECT"}


def test_all_actual_edge_contract_fields_are_named():
    source = PATH.read_text(encoding="utf-8")
    for field in ("actual_periodic_vs_physical_field_abs_difference_max", "actual_periodic_vs_physical_field_relative_difference", "H_cross_gram_difference_max", "H_metric_pipeline_difference_max", "residual_norm_fraction_by_edge", "nyquist_or_wrap_residual_fraction"):
        assert field in source


def test_no_fitted_transform_is_authoritative():
    source = PATH.read_text(encoding="utf-8")
    assert "fitted" not in source.lower()
    assert "U(2)" not in source
