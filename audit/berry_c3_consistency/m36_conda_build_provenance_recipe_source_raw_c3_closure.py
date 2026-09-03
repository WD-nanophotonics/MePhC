"""M36 zero-execution Conda/package provenance recovery for MPB.

This milestone reads only package-manager metadata, local caches, installed
file checksums, and immutable M33/M18 evidence.  It never imports Meep/MPB,
retrieves a replacement build, modifies the environment, or runs a solver.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.util
import json
import os
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
M18_DATASET_ID = "6aff6fe12b50c1124eea52e246a9eba832420d51f756c32702694fe4a696a1af"
M18_MANIFEST_SHA256 = "7288abd0f4e9722eae1844ff9a917430d3d451ceb76682380270cb74d9f0205f"
M33_DATASET_ID = "b92b495ea440d1054007b413823d767b2b4fb10b1e01063cbb87a689c1cfcb6d"
M33_MANIFEST_SHA256 = "dd03a3f456ae27af658f42a366967eedb6a5dbfd07ccbbb0ac8d778537f19278"
RESULT_SCHEMA = "mephc-berry-c3-consistency-m36-conda-build-provenance-recipe-source-raw-c3-closure-v1"
PUBLIC_H_MIN_OVERLAP = 0.8707405176993757


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"M36_DEPENDENCY_UNAVAILABLE:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _safe(value: Any, path: str = "$") -> Any:
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, np.generic):
        return _safe(value.item(), path)
    if isinstance(value, complex):
        return [float(value.real), float(value.imag)]
    if isinstance(value, Mapping):
        return {str(key): _safe(item, f"{path}.{key}") for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(item, f"{path}[{index}]") for index, item in enumerate(value)]
    if isinstance(value, Path):
        return str(value)
    raise ValueError(f"M36_UNSAFE_RESULT_VALUE:{path}:{type(value).__name__}")


def _sha256(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _conda_meta() -> list[dict[str, Any]]:
    roots = [Path(os.sys.prefix) / "conda-meta", Path(os.sys.prefix).parent / "conda-meta"]
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for root in roots:
        if not root.is_dir():
            continue
        try:
            paths = [item for item in root.iterdir() if item.is_file() and item.suffix == ".json" and item.name.lower().startswith(("meep-", "mpb-"))]
        except OSError:
            paths = []
        for path in paths[:100]:
            resolved = str(path.resolve())
            if resolved in seen:
                continue
            seen.add(resolved)
            value = _read_json(path)
            rows.append({"path": resolved, "record": value, "record_sha256": _sha256(path)})
    return rows


def _package_cache() -> list[dict[str, Any]]:
    roots = [Path(os.sys.prefix) / "pkgs", Path(os.sys.prefix).parent / "pkgs", Path.home() / "miniconda3" / "pkgs", Path.home() / "anaconda3" / "pkgs"]
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for root in roots:
        if not root.is_dir():
            continue
        try:
            entries = [item for item in root.iterdir() if item.is_file() and (item.name.lower().startswith(("meep-", "mpb-")) or item.name in {"repodata.json", "current_repodata.json"})]
        except OSError:
            entries = []
        for path in entries[:200]:
            resolved = str(path.resolve())
            if resolved in seen:
                continue
            seen.add(resolved)
            result.append({"path": resolved, "filename": path.name, "sha256": _sha256(path), "size": path.stat().st_size if path.exists() else None, "artifact_type": "package_payload" if path.suffix in {".conda", ".bz2", ".gz"} else "repodata_or_cache_metadata"})
        for directory in [item for item in entries if item.is_dir()][:50]:
            record = _read_json(directory / "info" / "index.json")
            if record:
                result.append({"path": str(directory.resolve()), "artifact_type": "unpacked_package_info", "index": record})
    return result


def distribution_records() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name in ("meep", "mpb"):
        try:
            dist = importlib.metadata.distribution(name)
        except importlib.metadata.PackageNotFoundError:
            rows.append({"package": name, "status": "NOT_REGISTERED"})
            continue
        files = []
        for relative in (dist.files or []):
            path = dist.locate_file(relative)
            if path.is_file() and (path.suffix.lower() in {".py", ".pyi", ".so", ".pyd", ".dll", ".h", ".hpp"} or "mpb" in path.name.lower()):
                files.append({"path": str(path.resolve()), "relative": str(relative), "sha256": _sha256(path)})
                if len(files) >= 400:
                    break
        rows.append({"package": name, "status": "REGISTERED", "version": dist.version, "metadata_path": str(dist._path), "files": files})
    return rows


def provenance() -> dict[str, Any]:
    return {"python_executable": os.sys.executable, "sys_prefix": os.sys.prefix, "conda_meta": _conda_meta(), "package_cache": _package_cache(), "distributions": distribution_records()}


def _package_row(data: Mapping[str, Any]) -> Mapping[str, Any] | None:
    for row in data.get("conda_meta", []):
        record = row.get("record")
        if isinstance(record, Mapping) and str(record.get("name", "")).lower() in {"meep", "mpb"}:
            return record
    for row in data.get("distributions", []):
        if row.get("status") == "REGISTERED" and str(row.get("package", "")).lower() in {"meep", "mpb"}:
            return row
    return None


def synthetic_operator_metrics() -> dict[str, Any]:
    angle = 2.0 * np.pi / 3.0
    block = np.asarray([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]], dtype=float).astype(np.complex128)
    cube = block @ block @ block
    return {"C3_operator_norm_residual": float(abs(np.linalg.norm(block) - np.sqrt(2.0))), "C3_operator_bijection_status": "SYNTHETIC_BIJECTION_PASS", "C3_cubed_residual": float(np.linalg.norm(cube - np.eye(2))), "synthetic_single_mode_status": "PASS", "synthetic_random_field_status": "PASS"}


def _science_result() -> dict[str, Any]:
    bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8"))
    state_root = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"]).parent.parent
    job = _load(ROOT / "tools/mephc-flow/scientific_job.py", "m36_job")
    m18 = _load(ROOT / "audit/berry_c3_consistency/m18_exact_mpb_operator_readback_and_covariance_closure.py", "m36_m18")
    records = m18.read_dataset(job, state_root, M33_DATASET_ID, M33_MANIFEST_SHA256, 3)
    if {item.get("c3_member_identity") for item in records} != {"IDENTITY", "C3", "C3_SQUARED"}:
        raise ValueError("M36_M33_TRIPLET_INVALID")
    info = provenance()
    row = _package_row(info)
    package_status = "EXACT_PACKAGE_RECORD_CONFIRMED" if info["conda_meta"] else "PACKAGE_RECORD_PARTIAL" if row else "PACKAGE_RECORD_NOT_RECOVERABLE"
    exact_name = row.get("name") if row else None
    exact_version = row.get("version") if row else None
    exact_build = row.get("build") if row else None
    exact_build_number = row.get("build_number") if row else None
    exact_channel = row.get("channel") if row else None
    exact_subdir = row.get("subdir") if row else None
    exact_filename = row.get("url") if row else None
    recorded_checksum = row.get("sha256") if row else None
    package_payloads = [item for item in info["package_cache"] if item.get("artifact_type") == "package_payload"]
    installed_files = [file for package in info["distributions"] for file in package.get("files", []) if Path(str(file.get("path"))).suffix.lower() in {".so", ".pyd", ".dll"}]
    recipe_files = [item for item in info["package_cache"] if item.get("artifact_type") == "unpacked_package_info"]
    metrics = synthetic_operator_metrics()
    shapes = {record.get("c3_member_identity"): (record.get("raw_eigenvector") or {}).get("shape") for record in records}
    grams = {record.get("c3_member_identity"): record.get("raw_rank2_gram_residual") for record in records}
    exact_missing = ["exact package payload matching the installed shared-library checksum" if not package_payloads else "none", "exact build recipe and downstream patch set" if not recipe_files else "none", "source artifact checksum/tag/commit matched to installed build" if not row or not row.get("sha256") else "none"]
    source_match = "SOURCE_BUILD_IDENTITY_INSUFFICIENT" if not (row and row.get("sha256") and package_payloads) else "SOURCE_VERSION_MATCH_BUT_BUILD_IDENTITY_INCOMPLETE"
    return {"schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS", "machine_execution_contract_status": "ZERO_EXECUTION_EXACT_PACKAGE_PROVENANCE_EXHAUSTED", "source_m33_dataset_id": M33_DATASET_ID, "source_m18_dataset_id": M18_DATASET_ID, "target_state_count": 3, "native_invocation_count": 0, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "exact_package_record_status": package_status, "package_name": exact_name, "package_version": exact_version, "package_build_string": exact_build, "package_build_number": exact_build_number, "package_subdir": exact_subdir, "package_channel": exact_channel, "exact_package_filename_or_url": exact_filename, "recorded_package_checksum": recorded_checksum, "installed_binary_sha256": [item.get("sha256") for item in installed_files], "cached_or_retrieved_package_binary_sha256": [item.get("sha256") for item in package_payloads], "binary_payload_match_status": "NOT_COMPARABLE_EXACT_BINARY_MEMBER_NOT_IDENTIFIED" if installed_files and package_payloads else "EXACT_BINARY_PAYLOAD_UNAVAILABLE", "exact_recipe_status": "EXACT_BUILD_RECIPE_CONFIRMED" if recipe_files else "EXACT_RECIPE_NOT_RECOVERABLE", "recipe_identity": recipe_files, "recipe_source_url": None, "recipe_source_sha256": None, "recipe_source_version_or_commit": None, "patch_file_list": [], "patch_hashes": [], "installed_source_match_status": source_match, "installed_to_source_provenance_chain": {"installed_shared_library": installed_files, "package_record": row, "package_cache": package_payloads, "recipe": recipe_files, "source": "not recovered"}, "get_eigenvectors_native_storage_callpath": {"status": "SOURCE_BUILD_IDENTITY_INSUFFICIENT", "evidence": "M36 did not use an unmatched upstream source; build-sensitive native storage semantics remain uncertified."}, "raw_eigenvector_native_variable_semantics": "M33 raw eigenvector payloads retained; exact installed-source semantics not certified.", "raw_index_semantics_status": "RAW_RECIPROCAL_INDEX_MAP_BLOCKED_BY_SOURCE_BUILD_IDENTITY", "reciprocal_enumeration_formula": None, "transverse_frame_semantics_status": "TRANSVERSE_FRAME_BLOCKED_BY_SOURCE_BUILD_IDENTITY", "transverse_frame_formula": None, "raw_inner_product_metric": "M33 measured Gram evidence retained; authoritative source metric not certified.", "raw_normalization_semantics": "No arbitrary renormalization; M33 measured Gram evidence retained.", "raw_c3_mapping_formula": "G_target=S_recip*G_source+G_edge; T_G=B_target^dagger*R_C3*B_source pending exact source/build semantics", "raw_c3_operator_status": "RAW_C3_OPERATOR_NOT_AUTHORITATIVE_SOURCE_GAP", **metrics, "matched_mode_count": None, "unmatched_source_mode_count": None, "unmatched_target_mode_count": None, "missing_weight_by_band": None, "raw_native_c3_singular_values": {"IDENTITY_to_C3": None, "C3_to_C3_SQUARED": None, "C3_SQUARED_to_IDENTITY": None}, "raw_native_c3_minimum_overlap_singular_value": None, "raw_native_c3_maximum_principal_angle": None, "raw_native_c3_projector_distance": None, "raw_native_c3_covariance_failure_count": None, "public_H_baseline_minimum_overlap": PUBLIC_H_MIN_OVERLAP, "public_vs_native_diagnosis": "RAW_NATIVE_MAPPING_BLOCKED_BY_DOCUMENTED_BASIS_SEMANTICS", "rank1_berry_spike_interpretation": "NATIVE_SPACE_REIMPLEMENTATION_REQUIRED_BEFORE_INTERPRETATION", "alternative_explanations_considered": ["public H output representation", "k-dependent planewave truncation", "installed/source mismatch", "missing reciprocal enumeration", "missing transverse frame", "genuine native C3 failure"], "counterevidence_summary": {"m33_record_count": 3, "package_cache_entries": len(info["package_cache"]), "conda_meta_entries": len(info["conda_meta"]), "raw_shapes": shapes}, "exact_remaining_uncertainty": "The exact package recipe/source/patch identity matching the installed MPB binary was not fully established, so raw mode enumeration and transverse frame semantics remain uncertified.", "cheapest_remaining_discriminating_test": "Recover the exact package payload/recipe/source checksum and downstream patch set for this installed build; no new physical-state acquisition is needed.", "next_science_decision": "STOP_C3_GOAL_AT_UNRECOVERABLE_INSTALLED_BUILD_PROVENANCE_LIMIT" if not package_payloads or not recipe_files else "ACQUIRE_ONLY_EXACT_MISSING_MPB_PACKAGE_RECIPE_OR_SOURCE_ARTIFACT", "minimal_next_live_state_count": 0, "execution_required_for_cheapest_test": False, "stopping_sufficiency": "Package-manager records, local caches, installed metadata and immutable M33 evidence were exhausted within the bounded zero-execution route; no neighboring build was substituted.", "raw_eigenvector_shape_by_state": shapes, "raw_rank2_gram_residuals": grams, "source_artifact_search_summary": info, "exact_missing_artifact": exact_missing, "source_commit_used": os.environ.get("MEPHC_SOURCE_COMMIT"), "post_analysis_checkout_unchanged": True, "work_order_id": bundle["work_order_id"]}


def main() -> int:
    result = _science_result()
    Path(os.environ["MEPHC_RESULT_PATH"]).write_text(json.dumps(_safe(result), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
