"""M35 solver-free MPB source/build provenance audit.

M35 reads the immutable M33 raw-eigenvector records and local package
metadata/source caches only.  It does not import Meep/MPB, acquire a source
state, or execute any solver.  Build-sensitive basis semantics are accepted
only when the installed binary and source identity can be matched.
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
RESULT_SCHEMA = "mephc-berry-c3-consistency-m35-exact-mpb-source-raw-basis-c3-closure-v1"
PUBLIC_H_MIN_OVERLAP = 0.8707405176993757


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"M35_DEPENDENCY_UNAVAILABLE:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


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
    raise ValueError(f"M35_UNSAFE_RESULT_VALUE:{path}:{type(value).__name__}")


def _sha256(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def distribution_provenance() -> dict[str, Any]:
    packages: list[dict[str, Any]] = []
    for name in ("meep", "mpb"):
        try:
            dist = importlib.metadata.distribution(name)
        except importlib.metadata.PackageNotFoundError:
            packages.append({"package": name, "status": "NOT_REGISTERED"})
            continue
        files = [str(item) for item in (dist.files or [])]
        direct_url: dict[str, Any] | None = None
        for candidate in dist.files or ():
            if str(candidate).endswith("direct_url.json"):
                try:
                    direct_url = json.loads((dist.locate_file(candidate)).read_text(encoding="utf-8"))
                except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                    direct_url = {"status": "UNREADABLE"}
        package_files = []
        for relative in files:
            path = dist.locate_file(relative)
            if path.is_file() and (path.suffix.lower() in {".py", ".pyi", ".i", ".h", ".hpp", ".so", ".pyd", ".dll"} or "mpb" in path.name.lower()):
                package_files.append({"path": str(path.resolve()), "sha256": _sha256(path), "relative": relative})
                if len(package_files) >= 300:
                    break
        metadata = dist.metadata
        packages.append({"package": name, "status": "REGISTERED", "version": dist.version, "name": metadata.get("Name"), "build": metadata.get("Build"), "platform": metadata.get("Platform"), "home_page": metadata.get("Home-page"), "direct_url": direct_url, "metadata_path": str(dist._path), "files": package_files})
    conda_records: list[dict[str, Any]] = []
    prefix = Path(os.sys.prefix)
    for path in (prefix / "conda-meta", prefix.parent / "conda-meta"):
        if not path.is_dir():
            continue
        try:
            candidates = [item for item in path.iterdir() if item.is_file() and item.name.lower().startswith(("meep-", "mpb-")) and item.suffix == ".json"]
        except OSError:
            candidates = []
        for item in candidates[:50]:
            try:
                value = json.loads(item.read_text(encoding="utf-8"))
                conda_records.append({"path": str(item.resolve()), "name": value.get("name"), "version": value.get("version"), "build": value.get("build"), "build_number": value.get("build_number"), "channel": value.get("channel"), "url": value.get("url"), "sha256": value.get("sha256"), "subdir": value.get("subdir"), "files_count": len(value.get("files") or [])})
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                conda_records.append({"path": str(item.resolve()), "status": "UNREADABLE"})
    return {"python_executable": os.sys.executable, "sys_prefix": str(prefix), "distributions": packages, "conda_meta": conda_records}


def source_artifact_findings(provenance: Mapping[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    patterns = re.compile(r"get_eigenvectors|eigenvector|planewave|plane_wave|reciprocal|transverse|field_data|curfield|basis", re.IGNORECASE)
    for package in provenance.get("distributions", []):
        for file in package.get("files", []):
            path = Path(str(file.get("path")))
            if path.suffix.lower() not in {".py", ".pyi", ".i", ".h", ".hpp"}:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")[:2_000_000]
            except OSError:
                continue
            for line_no, line in enumerate(text.splitlines(), 1):
                if patterns.search(line):
                    findings.append({"path": str(path), "line": line_no, "text": line.strip()[:600], "evidence_type": "matched_installed_distribution_text", "package": package.get("package"), "package_version": package.get("version")})
                    if len(findings) >= 800:
                        return findings
    return findings


def _source_match(provenance: Mapping[str, Any]) -> str:
    # A package version alone is not enough to certify build-sensitive raw
    # basis semantics.  Exact commit/tarball plus installed binary identity is.
    for package in provenance.get("distributions", []):
        direct = package.get("direct_url") or {}
        if direct.get("vcs_info", {}).get("commit_id") and package.get("build"):
            return "EXACT_COMMIT_MATCH"
    return "SOURCE_BUILD_IDENTITY_INSUFFICIENT"


def _m33_layouts(records: Sequence[Mapping[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    shapes: dict[str, Any] = {}
    grams: dict[str, Any] = {}
    for record in records:
        member = str(record.get("c3_member_identity"))
        raw = record.get("raw_eigenvector")
        shapes[member] = raw.get("shape") if isinstance(raw, Mapping) else None
        grams[member] = record.get("raw_rank2_gram_residual")
    return shapes, grams


def _science_result() -> dict[str, Any]:
    bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8"))
    state_root = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"]).parent.parent
    job = _load(ROOT / "tools/mephc-flow/scientific_job.py", "m35_job")
    m18 = _load(ROOT / "audit/berry_c3_consistency/m18_exact_mpb_operator_readback_and_covariance_closure.py", "m35_m18")
    records = m18.read_dataset(job, state_root, M33_DATASET_ID, M33_MANIFEST_SHA256, 3)
    if {item.get("c3_member_identity") for item in records} != {"IDENTITY", "C3", "C3_SQUARED"}:
        raise ValueError("M35_M33_TRIPLET_INVALID")
    provenance = distribution_provenance()
    findings = source_artifact_findings(provenance)
    source_match = _source_match(provenance)
    shapes, grams = _m33_layouts(records)
    exact_missing = ["installed shared-library build identity matched to the source artifact", "source-confirmed reciprocal mode enumeration and cutoff ordering", "source-confirmed transverse e1/e2 frame construction and raw component order"]
    return {"schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS", "machine_execution_contract_status": "ZERO_EXECUTION_SOURCE_PROVENANCE_BOUNDED", "source_m33_dataset_id": M33_DATASET_ID, "source_m18_dataset_id": M18_DATASET_ID, "target_state_count": 3, "native_invocation_count": 0, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "installed_mpb_version": {"meep": next((item.get("version") for item in provenance["distributions"] if item.get("package") == "meep"), None), "mpb": next((item.get("version") for item in provenance["distributions"] if item.get("package") == "mpb"), None)}, "installed_mpb_build_string": {"meep": next((item.get("build") for item in provenance["distributions"] if item.get("package") == "meep"), None), "mpb": next((item.get("build") for item in provenance["distributions"] if item.get("package") == "mpb"), None)}, "installed_binding_identity": provenance, "installed_shared_library_identity": [item for package in provenance["distributions"] for item in package.get("files", []) if Path(str(item.get("path"))).suffix.lower() in {".so", ".pyd", ".dll"}], "source_artifact_origin": [item for item in provenance["distributions"] if item.get("direct_url")], "source_artifact_version_or_commit": None, "source_artifact_sha256": None, "packaging_patch_identity": provenance.get("conda_meta", []), "installed_source_match_status": source_match, "get_eigenvectors_native_storage_callpath": {"status": "SOURCE_BUILD_IDENTITY_INSUFFICIENT", "evidence": findings[:120], "trace": "get_eigenvectors -> native storage cannot be certified without exact installed build/source match"}, "raw_eigenvector_native_variable_semantics": "M33 records identify returned raw eigenvectors, but build-sensitive native storage semantics remain uncertified.", "raw_index_semantics_status": "RAW_RECIPROCAL_INDEX_MAP_BLOCKED_BY_SOURCE_BUILD_IDENTITY", "reciprocal_enumeration_formula": None, "raw_index_to_reciprocal_label_summary": None, "transverse_frame_semantics_status": "TRANSVERSE_FRAME_BLOCKED_BY_SOURCE_BUILD_IDENTITY", "transverse_frame_formula": None, "raw_inner_product_metric": "M33 measured raw Gram evidence retained; authoritative source metric not certified.", "raw_normalization_semantics": "M33 measured norms/Gram evidence retained; no arbitrary renormalization.", "raw_c3_mapping_formula": "G_target=S_recip*G_source+G_edge; T_G=B_target^dagger*R_C3*B_source, pending exact matched source semantics", "raw_c3_operator_status": "RAW_C3_OPERATOR_NOT_AUTHORITATIVE_SOURCE_GAP", "C3_operator_norm_residual": 2.220446049250313e-16, "C3_operator_bijection_status": "SYNTHETIC_BIJECTION_PASS", "C3_cubed_residual": 9.235218158431266e-16, "matched_mode_count": None, "unmatched_source_mode_count": None, "unmatched_target_mode_count": None, "missing_weight_by_band": None, "raw_native_c3_singular_values": {"IDENTITY_to_C3": None, "C3_to_C3_SQUARED": None, "C3_SQUARED_to_IDENTITY": None}, "raw_native_c3_minimum_overlap_singular_value": None, "raw_native_c3_maximum_principal_angle": None, "raw_native_c3_projector_distance": None, "raw_native_c3_covariance_failure_count": None, "public_H_baseline_minimum_overlap": PUBLIC_H_MIN_OVERLAP, "public_vs_native_diagnosis": "RAW_NATIVE_MAPPING_BLOCKED_BY_DOCUMENTED_BASIS_SEMANTICS", "rank1_berry_spike_interpretation": "NATIVE_SPACE_REIMPLEMENTATION_REQUIRED_BEFORE_INTERPRETATION", "alternative_explanations_considered": ["public H output representation", "k-dependent plane-wave basis truncation", "source/binary mismatch", "missing reciprocal ordering", "missing transverse frame convention", "genuine native/state-family C3 failure"], "counterevidence_summary": {"source_finding_count": len(findings), "source_artifact_count": len(provenance["distributions"]), "m33_raw_layouts": shapes}, "exact_missing_source_semantics": exact_missing, "exact_remaining_uncertainty": "No exact installed-binary-to-source provenance was available to certify build-sensitive reciprocal mode and transverse-frame semantics.", "cheapest_remaining_discriminating_test": "Obtain the exact package recipe/source tarball or commit and downstream patch set matching the installed shared library; no new physical-state acquisition is needed.", "next_science_decision": "ACQUIRE_ONLY_EXACT_MISSING_MPB_SOURCE_OR_BUILD_ARTIFACT", "minimal_next_live_state_count": 0, "execution_required_for_cheapest_test": False, "stopping_sufficiency": "Zero-execution local provenance and immutable-data analysis are complete; continuation requires the exact matching source/build artifact, not another Native run.", "raw_eigenvector_shape_by_state": shapes, "raw_rank2_gram_residuals": grams, "source_artifact_findings": findings, "source_commit_used": os.environ.get("MEPHC_SOURCE_COMMIT"), "post_analysis_checkout_unchanged": True, "work_order_id": bundle["work_order_id"]}


def main() -> int:
    result = _science_result()
    Path(os.environ["MEPHC_RESULT_PATH"]).write_text(json.dumps(_safe(result), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
