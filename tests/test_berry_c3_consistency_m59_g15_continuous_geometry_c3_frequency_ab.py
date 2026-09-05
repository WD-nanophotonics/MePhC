from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "audit/berry_c3_consistency/m59_g15_continuous_geometry_c3_frequency_ab.py"
SPEC = importlib.util.spec_from_file_location("m59_test_module", SOURCE)
assert SPEC and SPEC.loader
m59 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m59)


def _freq(failures):
    return {"failure_set": [{"vertex": v, "band": b, "source_member": s, "target_member": t} for v, b, s, t in failures], "failure_count": len(failures)}


def test_canonical_honeycomb_center_is_programmatically_derived():
    centers = m59.canonical_centers()
    assert np.allclose(centers["b_fractional"], [2 / 3, 1 / 3], atol=centers["identity_guard"], rtol=0)
    assert np.array_equal(m59.D @ m59.D @ m59.D, np.eye(2, dtype=int))


def test_periodic_feature_deduplication_and_c3_pass_fail():
    features = [{"center": [0.0, 0.0], "radius": 0.2, "height": 100.0, "material": "air:1.0"}, {"center": [1.0, 0.0], "radius": 0.2, "height": 100.0, "material": "air:1.0"}]
    unique, duplicates = m59.deduplicate_periodic(features)
    assert len(unique) == 2
    bad = features + [{"center": [0.1, 0.1], "radius": 0.2, "height": 100.0, "material": "air:1.0"}]
    assert m59.feature_c3_ledger(bad)["c3_status"] == "FAIL"


def test_exact_c3_orbit_passes_and_radius_mismatch_fails():
    seed = np.asarray([0.25, 0.0]); centers = [seed % 1, m59.D @ seed % 1, m59.D @ (m59.D @ seed) % 1]
    features = [{"center": center.tolist(), "radius": 0.2, "height": 100.0, "material": "air:1.0"} for center in centers]
    assert m59.feature_c3_ledger(features)["c3_status"] == "PASS"
    altered = [dict(feature) for feature in features]; altered[1]["radius"] = 0.21
    assert m59.feature_c3_ledger(altered)["c3_status"] == "FAIL"


def test_projection_and_failure_set_classification():
    mapping = m59.m54.build_index_map(); epsilon = np.ones(m59.SHAPE); epsilon[3, 7] = 4.0
    projected, summary = m59.projected_epsilon(epsilon, mapping)
    assert summary["projection_linf"] > summary["identity_guard"]
    stock = _freq([(0, 1, "IDENTITY", "C3"), (1, 2, "C3", "C3_SQUARED")])
    assert m59.classify(stock, _freq([]))[0] == "R256_CANONICAL_PRIMITIVE_FULL_FREQUENCY_RESTORATION"
    assert m59.classify(stock, _freq([(1, 2, "C3", "C3_SQUARED")]))[0] == "R256_CANONICAL_PRIMITIVE_PARTIAL_FREQUENCY_RESTORATION"
    assert m59.classify(stock, _freq([(2, 3, "C3_SQUARED", "IDENTITY")]))[0] == "R256_CANONICAL_PRIMITIVE_INTRODUCES_NEW_FAILURES"


def test_contract_forbids_fitted_or_finite_outline_canonical_path():
    text = SOURCE.read_text(encoding="utf-8")
    assert "BravaisLattice2D.triangular" in text
    assert "create_unitcell" in text
    assert "Lattice.get_points" not in text
    assert "pattern_to_meep_geometry" not in text
    assert "geometry=[]" not in text
    assert "run_parity" in text and "get_epsilon_inverse_tensor_point" in text


def test_no_higher_level_science_outputs():
    text = SOURCE.read_text(encoding="utf-8")
    assert "Berry" not in text.split("def main", 1)[0]
    assert "fields_gaps_subspaces_wilson_berry_computed" in text
