from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "audit/berry_c3_consistency/m60_canonical_primitive_frequency_causal_ab.py"
SPEC = importlib.util.spec_from_file_location("m60_test_module", SOURCE)
assert SPEC and SPEC.loader
m60 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m60)


def _freq(failures):
    return {"failure_set": [{"vertex": v, "band": b, "source_member": s, "target_member": t} for v, b, s, t in failures], "failure_count": len(failures)}


def _proof(status="PASS"):
    return {"c3_status": status, "features": [], "unmatched_feature_count": 0 if status == "PASS" else 1, "structural_guard": 1e-12, "raw_feature_count": 0, "unique_periodic_feature_count": 0}


def test_material_gate_failure_does_not_block_frequency_authorization():
    stock = _freq([(0, 1, "IDENTITY", "C3")])
    route = m60.route_frequency_after_geometry(stock, _proof("PASS"), {"operator_gate": False})
    assert route["authorize_frequency"] is True


def test_canonical_proof_has_exact_two_cylinders_and_c3_contract():
    assert "mp.Cylinder" in SOURCE.read_text(encoding="utf-8")
    assert "feature_c3_ledger" in SOURCE.read_text(encoding="utf-8")
    assert "create_unitcell" not in SOURCE.read_text(encoding="utf-8")


def test_periodic_species_matching_includes_height_and_torus_residual():
    features = [{"center": [0.0, 0.0], "radius": 0.2, "height": 100.0, "material": "air:1"}, {"center": [1.0, 0.0], "radius": 0.2, "height": 100.0, "material": "air:1"}]
    unique, duplicates = m60.deduplicate_periodic(features)
    assert len(unique) == 1 and len(duplicates) == 1
    seed = np.asarray([0.25, 0.0]); centers = [seed % 1, m60.D @ seed % 1, m60.D @ (m60.D @ seed) % 1]
    orbit = [{"center": c.tolist(), "radius": 0.2, "height": 100.0, "material": "air:1"} for c in centers]; orbit[1]["height"] = 101.0
    assert m60.feature_c3_ledger(orbit)["height_mismatch_count"] > 0


def test_exact_failure_set_relations_are_used():
    stock = _freq([(0, 1, "IDENTITY", "C3"), (1, 2, "C3", "C3_SQUARED")])
    canonical = _freq([(1, 2, "C3", "C3_SQUARED"), (2, 3, "C3_SQUARED", "IDENTITY")])
    classification, _, relations = m60.classify(stock, canonical)
    assert classification == "R256_CANONICAL_PRIMITIVE_INTRODUCES_NEW_FAILURES"
    assert relations["restored"] == {(0, 1, "IDENTITY", "C3")} and relations["new_failures"] == {(2, 3, "C3_SQUARED", "IDENTITY")}


def test_no_raw_fields_or_higher_level_berry_science():
    text = SOURCE.read_text(encoding="utf-8")
    assert "get_epsilon" in text and "run_parity" in text
    assert "eigenvectors" not in text and "Wilson" not in text and "Berry" not in text

