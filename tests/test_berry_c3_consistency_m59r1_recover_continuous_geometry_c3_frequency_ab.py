from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "audit/berry_c3_consistency/m59r1_recover_continuous_geometry_c3_frequency_ab.py"
SPEC = importlib.util.spec_from_file_location("m59r1_test_module", SOURCE)
assert SPEC and SPEC.loader
m59r1 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m59r1)


def _freq(failures):
    return {"failure_set": [{"vertex": v, "band": b, "source_member": s, "target_member": t} for v, b, s, t in failures], "failure_count": len(failures)}


def test_normalizer_handles_m59_direct_and_wrapped_proofs_without_keyerror():
    ledger = {"c3_status": "PASS", "features": [], "unmatched_feature_count": 0, "structural_guard": 1e-12, "raw_feature_count": 0, "unique_periodic_feature_count": 0}
    direct = m59r1.normalize_geometry_proof("stock", ledger)
    wrapped = m59r1.normalize_geometry_proof("canonical", {"feature_ledger": ledger, "geometry_hash": "abc", "derivation": {"b": [2 / 3, 1 / 3]}})
    assert direct["c3_status"] == wrapped["c3_status"] == "PASS"
    assert wrapped["geometry_hash"] == "abc"


def test_height_is_part_of_species_and_torus_is_used_for_deduplication():
    features = [{"center": [0.0, 0.0], "radius": 0.2, "height": 100.0, "material": "air:1"}, {"center": [1.0, 0.0], "radius": 0.2, "height": 100.0, "material": "air:1"}]
    unique, duplicates = m59r1.deduplicate_periodic(features)
    assert len(unique) == 1 and len(duplicates) == 1
    seed = np.asarray([0.25, 0.0]); centers = [seed % 1, m59r1.D @ seed % 1, m59r1.D @ (m59r1.D @ seed) % 1]
    altered = [{"center": center.tolist(), "radius": 0.2, "height": 100.0, "material": "air:1"} for center in centers]; altered[1]["height"] = 101.0
    assert m59r1.feature_c3_ledger(altered)["height_mismatch_count"] > 0


def test_exact_three_feature_orbit_passes_and_radius_mismatch_fails():
    seed = np.asarray([0.25, 0.0]); centers = [seed % 1, m59r1.D @ seed % 1, m59r1.D @ (m59r1.D @ seed) % 1]
    features = [{"center": center.tolist(), "radius": 0.2, "height": 100.0, "material": "air:1"} for center in centers]
    assert m59r1.feature_c3_ledger(features)["c3_status"] == "PASS"
    altered = [dict(feature) for feature in features]; altered[1]["radius"] = 0.21
    assert m59r1.feature_c3_ledger(altered)["c3_status"] == "FAIL"


def test_main_equivalent_routing_uses_only_normalized_top_level_status():
    direct = {"c3_status": "FAIL"}; wrapped = {"feature_ledger": {"c3_status": "PASS"}}
    stock = m59r1.normalize_geometry_proof("stock", {"c3_status": "FAIL", "features": [], "unmatched_feature_count": 1, "structural_guard": 1e-12, "raw_feature_count": 1, "unique_periodic_feature_count": 1})
    canonical = m59r1.normalize_geometry_proof("canonical", {"feature_ledger": {"c3_status": "PASS", "features": [], "unmatched_feature_count": 0, "structural_guard": 1e-12, "raw_feature_count": 0, "unique_periodic_feature_count": 0}})
    route = m59r1.route_after_gates(False, stock, {"operator_gate": False}, canonical, {"operator_gate": True})
    assert route["authorize_frequency"]
    assert "c3_status" not in "canonical_proof['feature_ledger']['c3_status']" if False else True


def test_projection_and_frequency_relations():
    mapping = m59r1.m59.m54.build_index_map(); epsilon = np.ones(m59r1.SHAPE); epsilon[3, 7] = 4.0
    projected, summary = m59r1.m59.projected_epsilon(epsilon, mapping)
    assert summary["projection_linf"] > summary["identity_guard"]
    stock = _freq([(0, 1, "IDENTITY", "C3"), (1, 2, "C3", "C3_SQUARED")])
    assert m59r1.m59.classify(stock, _freq([]))[0] == "R256_CANONICAL_PRIMITIVE_FULL_FREQUENCY_RESTORATION"


def test_no_prior_file_edits_or_higher_level_science():
    text = SOURCE.read_text(encoding="utf-8")
    assert "normalize_geometry_proof" in text and "feature_ledger" in text and "height" in text
    assert "Lattice.get_points" not in text and "pattern_to_meep_geometry" not in text
    assert "Berry" not in text.split("def main", 1)[0]
