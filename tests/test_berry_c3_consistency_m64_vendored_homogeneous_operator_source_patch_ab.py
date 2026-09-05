from __future__ import annotations

import json
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "audit/berry_c3_consistency/m64_vendored_homogeneous_operator_source_patch_ab.py"
PATCH = ROOT / "vendor/mpb_c3_patch/mpb-1.12.0-homogeneous-c3.patch"
MANIFEST = ROOT / "vendor/mpb_c3_patch/source_manifest.json"
PROVENANCE = ROOT / "vendor/mpb_c3_patch/source_build5_provenance.json"


def test_source_boundary_is_fail_closed_without_exact_artifact():
    data = json.loads(MANIFEST.read_text(encoding="utf-8")); assert data["source_available_in_workspace"] is False and data["installed_backend_touched"] is False


def test_patch_artifact_contains_no_unverified_hunk():
    assert "no patch hunk" in PATCH.read_text(encoding="utf-8")


def test_m64_uses_zero_science_side_effects_until_source_identity_exists():
    text = SOURCE.read_text(encoding="utf-8"); assert "native_invocation_count\": 0" in text and "installed_backend_touched\": False" in text


def test_supervisor_recovered_exact_build5_recipe_source_artifact():
    data = json.loads(PROVENANCE.read_text(encoding="utf-8"))
    artifact = ROOT / data["source_artifact"]
    assert data["package_build"] == "mpi_mpich_hef3cbd5_5"
    assert data["binary_identity_status"] == "EXACT_CACHE_AND_INSTALLED_LIBMPB_MATCH"
    assert hashlib.sha256(artifact.read_bytes()).hexdigest() == data["source_sha256"]
    assert data["installed_backend_touched"] is False
