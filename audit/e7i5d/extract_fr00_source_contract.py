"""E7I.5D primary-source inventory and fail-closed contract recovery tools."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path

from PIL import Image

PAPER_GAP21 = 0.045
PAPER_GAP32 = 0.044
PAPER_BERRY = (-0.92, 0.72, 0.19)
PAPER_FILL = 0.107
PAPER_EPSILON = 2.65
PAPER_A = 400e-9
F2_SHA256 = "6AA4CD9125279FEA08876384D093BAE6788C9922F3B83CD0F97B16BA7E5CC459".lower()


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def content_type(path: Path) -> str:
    return {".tex": "text/x-tex", ".json": "application/json", ".bib": "text/x-bibtex", ".png": "image/png"}.get(path.suffix.lower(), "application/octet-stream")


def inventory(source_root: Path, figshare_metadata: Path, archive: Path | None = None) -> dict:
    files = []
    for path in sorted(source_root.rglob("*")):
        if path.is_file():
            rel = path.relative_to(source_root).as_posix()
            role = "ARXIV_SOURCE_TEXT" if rel == "arxiv/NewBC.tex" else "ARXIV_SOURCE_MANIFEST" if rel == "arxiv/00README.json" else "ARXIV_SOURCE_BIB" if rel.endswith(".bib") else "ARXIV_SOURCE_FIGURE_ASSET" if rel.startswith("arxiv/pic/") else "ARXIV_SOURCE_PACKAGE_EXTRACTED"
            files.append({"source_name": "arXiv_2603.27244v1", "source_role": role, "original_filename": rel, "byte_size": path.stat().st_size, "sha256": sha(path), "content_type": content_type(path)})
    if figshare_metadata.exists():
        files.append({"source_name": "Figshare_31076839", "source_role": "FIGSHARE_PRIMARY_METADATA", "original_filename": figshare_metadata.name, "byte_size": figshare_metadata.stat().st_size, "sha256": sha(figshare_metadata), "content_type": "application/json"})
    if archive and archive.exists():
        files.append({"source_name": "arXiv_2603.27244v1", "source_role": "ARXIV_SOURCE_ARCHIVE", "original_filename": archive.name, "byte_size": archive.stat().st_size, "sha256": sha(archive), "content_type": "application/x-tar"})
    return {"schema": "e7i5d_primary_source_manifest_v1", "figshare_api": "https://api.figshare.com/v2/articles/31076839", "arxiv_source": "https://arxiv.org/e-print/2603.27244v1", "published_doi": "10.1103/1sq1-3168", "file_count": len(files), "files": files, "manifest_sha256": digest(files)}


def find_k_marker(im: Image.Image) -> int:
    candidates = []
    for x in range(1750, 2780):
        n = sum(1 for y in range(820, 1510) if max(im.getpixel((x, y))[:3]) < 30)
        if n > 100:
            candidates.append(x)
    if not candidates:
        raise RuntimeError("Figure 2(b) K marker was not found")
    return round(sum(candidates) / len(candidates))


def find_axis(im: Image.Image) -> tuple[int, int]:
    rows = []
    for y in range(760, 1600):
        n = sum(1 for x in range(1720, 2810) if max(im.getpixel((x, y))[:3]) < 30)
        if n > 500:
            rows.append(y)
    if len(rows) < 2:
        raise RuntimeError("Figure 2(b) axis bounds were not found")
    return min(rows), max(rows)


def raster_frequencies(f2: Path) -> dict:
    if sha(f2).lower() != F2_SHA256:
        raise RuntimeError("Figure 2 source hash mismatch")
    im = Image.open(f2).convert("RGB")
    if im.size != (5552, 4534):
        raise RuntimeError(f"unexpected Figure 2 size: {im.size}")
    kx = find_k_marker(im)
    y_top, y_bottom = find_axis(im)
    colors = {"band1": (0, 128, 0), "band2": (128, 0, 128), "band3": (255, 165, 0)}
    rows = {}
    for band, color in colors.items():
        values = []
        for x in list(range(kx - 20, kx - 5)) + list(range(kx + 6, kx + 21)):
            for y in range(y_top + 10, y_bottom - 10):
                if im.getpixel((x, y)) == color:
                    values.append(y)
        if not values:
            raise RuntimeError(f"source color not found for {band}")
        values.sort()
        row = values[len(values) // 2]
        normalized = (y_bottom - row) / (y_bottom - y_top) * 0.5
        rows[band] = {"pixel_row_median": row, "pixel_row_min": min(values), "pixel_row_max": max(values), "normalized_frequency_a_over_lambda": normalized}
    pixel_uncertainty = 3.0
    uncertainty = pixel_uncertainty / (y_bottom - y_top) * 0.5
    return {"source_asset": "arxiv/pic/f2.png", "source_sha256": F2_SHA256, "image_size": list(im.size), "panel": "Figure 2(b) top band diagram, fr=0 Tri-TPC", "axis_calibration": {"x_K_pixel": kx, "y_top_for_0.5": y_top, "y_bottom_for_0.0": y_bottom, "pixel_uncertainty_rows": pixel_uncertainty, "normalized_frequency_uncertainty": uncertainty, "axis_quantity": "a/lambda = omega*a/(2*pi*c)"}, "bands": rows, "band4": {"status": "NOT_AVAILABLE", "reason": "The source raster does not expose a calibrated fourth K-band value in Figure 2(b)."}, "absolute_frequency_status": "RASTER_DIGITIZED", "extraction_digest": digest({"kx": kx, "y_top": y_top, "y_bottom": y_bottom, "rows": rows})}


def extract_contract(source_root: Path, figshare_metadata: Path, manifest: dict) -> tuple[dict, list]:
    tex_path = source_root / "arxiv" / "NewBC.tex"
    text = tex_path.read_text(encoding="utf-8")
    required = ["finite-element-method (FEM) using COMSOL", "two dimensional PhC model", "lattice constant a=400nm", "effective permittivity of silicon is set to 2.65", "filling factor of the air holes is $10.7\\%", "first three bands of the TE-polarization", "fr=0", "regular triangular shape", "Delta \\omega_{21}=0.045", "Delta \\omega_{32}=0.044"]
    anchors = {phrase: text.find(phrase) for phrase in required}
    if any(value < 0 for value in anchors.values()):
        raise RuntimeError({phrase: value for phrase, value in anchors.items() if value < 0})
    raster = raster_frequencies(source_root / "arxiv" / "pic" / "f2.png")
    f1 = raster["bands"]["band1"]["normalized_frequency_a_over_lambda"]
    f2 = raster["bands"]["band2"]["normalized_frequency_a_over_lambda"]
    f3 = raster["bands"]["band3"]["normalized_frequency_a_over_lambda"]
    uncertainty = raster["axis_calibration"]["normalized_frequency_uncertainty"]
    source = {
        "schema": "e7i5d_source_contract_v1",
        "source_manifest_sha256": manifest["manifest_sha256"],
        "paper_source": {"arxiv": "2603.27244v1", "figshare_doi": "10.6084/m9.figshare.31076839.v2", "published_doi": "10.1103/1sq1-3168", "text_anchor_offsets": anchors},
        "paper_text_contract": {"dimension": "2D", "method": "FEM_COMSOL", "lattice_constant_m": PAPER_A, "effective_permittivity_text": PAPER_EPSILON, "air_hole_filling_factor_text": PAPER_FILL, "air_hole_area_held_fixed": True, "shape_fr0": "regular_triangle", "polarization_text": "TE", "paper_gap21": PAPER_GAP21, "paper_gap32": PAPER_GAP32, "paper_berry": list(PAPER_BERRY)},
        "absolute_K_frequency": {"status": "RASTER_DIGITIZED", "F1": f1, "F2": f2, "F3": f3, "F4": None, "uncertainty_each": uncertainty, "gap21_digitized": f2 - f1, "gap32_digitized": f3 - f2, "text_gap21_authoritative": PAPER_GAP21, "text_gap32_authoritative": PAPER_GAP32, "raster": raster},
        "material": {"paper_text_material_label": "EFFECTIVE_PERMITTIVITY_2P65", "actual_source_model_material_input": "SOURCE_MODEL_NOT_AVAILABLE", "machine_readable_COMSOL_model": False, "alternate_epsilon2_authorized": False},
        "TE": {"paper_comsol_TE_field_content": "UNRESOLVED", "MPB_documented_convention": "E_IN_PLANE_HZ_OUT_OF_PLANE", "match": "UNRESOLVED", "alternate_TM_authorized": False},
        "fill_factor": {"paper_semantics": "TEXT_ONLY_UNRESOLVED", "current_mephc_semantics": "AIR_AREA_OVER_PRIMITIVE_CELL_AREA", "current_numeric_contract": PAPER_FILL},
        "orientation": {"source": "RASTER_DISCRETE_CLASS", "source_asset": "arxiv/pic/f2.png", "degrees_mod_120": 90.0, "mirror_class": "APEX_PLUS_PUBLIC_Y_NON_MIRRORED", "current_degrees_mod_120": 90.0, "source_compatible_candidates": [90.0]},
        "source_artifact_status": {"figshare_assets": "NO_RELEVANT_ASSETS", "arxiv_source_package": "BOUND", "published_supplementary": "NOT_ACCESSIBLE_IN_CURRENT_SOURCE_INVENTORY"},
        "source_contract_bound": False,
        "spectral_structure_compatible": None,
    }
    source["source_contract_sha256"] = digest(source)
    candidate = [{"candidate_id": "CURRENT_FR00_CONTRACT_REUSE", "source_evidence": ["NewBC.tex fr=0 regular triangular shape", "NewBC.tex effective permittivity 2.65", "NewBC.tex TE", "NewBC.tex fixed air-hole area", "Figure 2(b) same apex orientation class"], "difference_from_baseline": "NONE", "why_this_difference_is_source_justified": "This candidate is a reuse of the existing baseline; no unresolved parameter is changed.", "new_live_diagnostic": False}]
    return source, candidate


def diagnose(root: Path, source: dict, candidates: list) -> dict:
    current = json.loads((root / "audit/e7i5c/result.json").read_text(encoding="utf-8"))
    base = current["current_contract_reused"]
    f = source["absolute_K_frequency"]
    return {"schema": "e7i5d_primary_source_recovery_result_v1", "complete": True, "source_contract_sha256": source["source_contract_sha256"], "candidate_count": len(candidates), "new_live_candidate_count": 0, "current_baseline_reused": base, "paper_absolute_frequency_status": f["status"], "paper_K_F1": f["F1"], "paper_K_F2": f["F2"], "paper_K_F3": f["F3"], "paper_K_F4": None, "paper_K_frequency_uncertainty": f["uncertainty_each"], "paper_gap21_text": PAPER_GAP21, "paper_gap32_text": PAPER_GAP32, "paper_gap21_digitized": f["gap21_digitized"], "paper_gap32_digitized": f["gap32_digitized"], "baseline_R48": {"frequencies": base["R48_frequencies"], "gap21": base["R48_gap21"], "gap32": base["R48_gap32"], "abs_error_gap21": abs(base["R48_gap21"] - PAPER_GAP21), "abs_error_gap32": abs(base["R48_gap32"] - PAPER_GAP32)}, "baseline_R64": {"frequencies": base["R64_frequencies"], "gap21": base["R64_gap21"], "gap32": base["R64_gap32"], "abs_error_gap21": abs(base["R64_gap21"] - PAPER_GAP21), "abs_error_gap32": abs(base["R64_gap32"] - PAPER_GAP32)}, "actual_source_model_material_input": source["material"]["actual_source_model_material_input"], "paper_comsol_TE_field_content": source["TE"]["paper_comsol_TE_field_content"], "TE_convention_match": source["TE"]["match"], "paper_fill_factor_semantics": source["fill_factor"]["paper_semantics"], "paper_triangle_orientation_source": source["orientation"]["source"], "paper_triangle_orientation_degrees_mod_120": source["orientation"]["degrees_mod_120"], "source_justified_candidates": candidates, "source_contract_bound": False, "spectral_structure_compatible": None, "paper_reference_model_recovered": False, "spectral_mismatch_root_cause": "SOURCE_ARTIFACTS_INSUFFICIENT", "new_Berry_calculation": "NOT_AUTHORIZED", "new_Chern_calculation": "NOT_AUTHORIZED", "new_live_K_diagnostics": "NONE_SOURCE_CONTRACT_INCOMPLETE", "E7I5D_overall": "PRIMARY_SOURCE_ARTIFACTS_INSUFFICIENT"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("inventory", "extract", "diagnose"))
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--figshare-metadata", type=Path, required=True)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest = inventory(args.source_root, args.figshare_metadata, args.archive)
    (args.output_dir / "source_manifest.json").write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    if args.mode == "inventory":
        print(json.dumps({"files": manifest["file_count"], "manifest_sha256": manifest["manifest_sha256"]}, sort_keys=True))
        return
    source, candidates = extract_contract(args.source_root, args.figshare_metadata, manifest)
    (args.output_dir / "source_contract.json").write_text(json.dumps(source, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    (args.output_dir / "source_justified_candidates.json").write_text(json.dumps(candidates, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    if args.mode == "extract":
        print(json.dumps({"source_contract_sha256": source["source_contract_sha256"], "candidate_count": len(candidates)}, sort_keys=True))
        return
    result = diagnose(args.repo_root, source, candidates)
    (args.output_dir / "result.json").write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"source_contract_sha256": source["source_contract_sha256"], "E7I5D_overall": result["E7I5D_overall"], "new_live_candidate_count": 0}, sort_keys=True))


if __name__ == "__main__":
    main()
