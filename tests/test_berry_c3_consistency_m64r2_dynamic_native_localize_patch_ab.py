from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "audit/berry_c3_consistency/m64r2_dynamic_native_localize_patch_ab.py"
SPEC = importlib.util.spec_from_file_location("m64r2", SOURCE)
assert SPEC and SPEC.loader
m64r2 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m64r2)


def test_exact_build5_identity_and_frozen_bindings_are_explicit():
    assert m64r2.SOURCE_SHA == "8d2b206254b217f66a53c1ad20cc0c369b93b0e71ee671d68e333a583eaaeda4"
    assert m64r2.LIBMPB_SHA == "884071022f8c5230909e269c63b17cef120b51d2a4ee22b862c6a7005d209dbc"
    assert all(len(binding[0]) == 64 and len(binding[1]) == 64 for binding in (m64r2.M50, m64r2.M60, m64r2.M61, m64r2.M63))


def test_analytic_reciprocal_reference_is_deterministic_and_four_band():
    first = m64r2._analytic_spectrum([0.25, -0.5])
    assert first == m64r2._analytic_spectrum([0.25, -0.5])
    assert len(first) == 4 and first == sorted(first)


def test_trace_contract_has_ordered_stages_and_no_scientific_patch_by_default():
    text = SOURCE.read_text(encoding="utf-8")
    stages = ["input/native k representation", "reciprocal label/index", "q or k+G vector and metric q2", "transverse basis/projector", "homogeneous operator action or Rayleigh quantity", "eigensolver eigenvalue plus residual/convergence metadata", "eigenvalue-to-frequency conversion", "band sorting/Python-visible frequency"]
    assert all(stage in text for stage in stages)
    assert '"patch_applied": False' in text


def test_source_manifest_and_allowed_patch_are_fail_closed_until_unique_layer():
    manifest = json.loads((ROOT / "vendor/mpb_c3_patch/source_manifest.json").read_text(encoding="utf-8"))
    patch = (ROOT / "vendor/mpb_c3_patch/mpb-1.12.0-homogeneous-c3.patch").read_text(encoding="utf-8")
    instrumentation = (ROOT / "vendor/mpb_c3_patch/mpb-1.12.0-homogeneous-c3-instrumentation.patch").read_text(encoding="utf-8")
    assert manifest["installed_backend_touched"] is False
    assert "NO SCIENTIFIC PATCH" in patch
    assert "TRACE-ONLY" in instrumentation
