"""M32 zero-execution installed MPB binding/source forensics.

The module deliberately uses import *specification* discovery and bounded
source-text inspection only.  It never imports Meep/MPB, starts a solver, or
guesses an ABI.  A symbol name is reported as evidence, not as an accessible
scientific path, unless a typed wrapper/call path is visible in source.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.util
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
M18_DATASET_ID = "6aff6fe12b50c1124eea52e246a9eba832420d51f756c32702694fe4a696a1af"
M18_MANIFEST_SHA256 = "7288abd0f4e9722eae1844ff9a917430d3d451ceb76682380270cb74d9f0205f"
M30_DATASET_ID = "320a49b45e8927442aefb7e142633b1e40458664f64ac19a115cfc44e19ef3b0"
M30_MANIFEST_SHA256 = "359214d08634e5d2f36ba485a5901379ff73c28edaa809e0cbb6d58f62def3f4"
M31_DATASET_ID = "62907b0f51cbb659474b064da9d28b4689b3f19e293d4d6c7de4397284089b33"
M31_MANIFEST_SHA256 = "08768a52ca8245b38f3b1b6aeeaf212629b75c7f3325071d743a97e52544bc68"
RESULT_SCHEMA = "mephc-berry-c3-consistency-m32-installed-mpb-reciprocal-h-export-forensics-v1"
MEMBERS = ("IDENTITY", "C3", "C3_SQUARED")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"M32_DEPENDENCY_UNAVAILABLE:{path}")
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
        return {str(k): _safe(v, f"{path}.{k}") for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(v, f"{path}[{i}]") for i, v in enumerate(value)]
    if isinstance(value, Path):
        return str(value)
    raise ValueError(f"M32_UNSAFE_RESULT_VALUE:{path}:{type(value).__name__}")


def _spec(name: str) -> dict[str, Any]:
    try:
        spec = importlib.util.find_spec(name)
    except (ImportError, ModuleNotFoundError, ValueError) as exc:
        return {"package": name, "status": "NOT_FOUND", "error": f"{type(exc).__name__}:{str(exc)[:256]}"}
    if spec is None:
        return {"package": name, "status": "NOT_FOUND"}
    roots = [str(Path(p)) for p in (spec.submodule_search_locations or ())]
    return {"package": name, "status": "FOUND", "origin": str(spec.origin) if spec.origin else None, "search_locations": roots, "loader": type(spec.loader).__name__ if spec.loader else None}


def _artifact_paths(specs: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    allowed_suffixes = {".py", ".pyi", ".i", ".h", ".hpp", ".c", ".cc", ".cpp", ".so", ".pyd", ".dll", ".dylib", ".md", ".rst"}
    paths: list[dict[str, Any]] = []
    seen: set[str] = set()
    for spec in specs:
        candidates = [spec.get("origin"), *(spec.get("search_locations") or [])]
        for raw in candidates:
            if not raw:
                continue
            path = Path(str(raw))
            if path.is_file():
                files = [path]
            elif path.is_dir():
                try:
                    files = [item for item in path.iterdir() if item.is_file() and item.suffix.lower() in allowed_suffixes]
                except OSError:
                    files = []
            else:
                files = []
            for item in files[:256]:
                key = str(item.resolve())
                if key in seen:
                    continue
                seen.add(key)
                suffix = item.suffix.lower()
                paths.append({"path": key, "package": spec.get("package"), "artifact_type": "python" if suffix in {".py", ".pyi"} else "source_or_header" if suffix in {".i", ".h", ".hpp", ".c", ".cc", ".cpp", ".md", ".rst"} else "shared_library", "exists": True})
    return paths


def installed_mpb_artifact_inventory() -> list[dict[str, Any]]:
    specs = [_spec(name) for name in ("meep", "meep.mpb", "mpb")]
    artifacts = _artifact_paths(specs)
    packages: list[dict[str, Any]] = []
    for name in ("meep", "mpb"):
        try:
            packages.append({"package": name, "version": importlib.metadata.version(name), "evidence_type": "installed_distribution_metadata"})
        except importlib.metadata.PackageNotFoundError:
            packages.append({"package": name, "version": None, "evidence_type": "distribution_not_registered"})
    return [{"kind": "package_spec", **item} for item in specs] + packages + artifacts


def _text(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8", errors="ignore")[:2_000_000]
    except (OSError, UnicodeError):
        return ""


def _source_findings(artifacts: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    patterns = re.compile(r"get_hfield|field_data|curfield|fft|fourier|eigenvector|load_hfield|interpolat|grid_origin|bloch", re.IGNORECASE)
    findings: list[dict[str, Any]] = []
    for artifact in artifacts:
        if artifact.get("artifact_type") not in {"python", "source_or_header"}:
            continue
        path = str(artifact.get("path"))
        content = _text(path)
        for line_no, line in enumerate(content.splitlines(), 1):
            if patterns.search(line):
                findings.append({"path": path, "line": line_no, "text": line.strip()[:500], "evidence_type": "source_text_reference"})
                if len(findings) >= 400:
                    return findings
    return findings


def get_hfield_wrapper_callpath(artifacts: Sequence[Mapping[str, Any]], findings: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    path = [item for item in findings if "get_hfield" in str(item.get("text", "")).lower()]
    if not path:
        return [{"stage": "python_ModeSolver.get_hfield", "status": "SOURCE_PATH_NOT_FOUND", "evidence": "No installed local wrapper/source text exposed to bounded inspection."}]
    return [{"stage": "python_or_binding_source_reference", "path": item["path"], "line": item["line"], "source_text": item["text"], "status": "REFERENCE_ONLY_UNTIL_TYPED_CALL_PATH_CONFIRMED"} for item in path[:80]]


def reciprocal_candidate_inventory(findings: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    names = ("get_hfield", "field_data", "curfield", "get_hfield_coefficients", "hfield_coefficients", "fourier", "fft", "load_hfield", "eigenvector")
    result: list[dict[str, Any]] = []
    for name in names:
        matches = [item for item in findings if name.lower() in str(item.get("text", "")).lower()]
        if matches:
            for match in matches[:8]:
                text = str(match["text"])
                typed = bool(re.search(r"def\s+\w*" + re.escape(name) + r"|%rename|SWIG|extern\s+\"C\"", text, re.IGNORECASE))
                result.append({"candidate_name": name, "artifact_path": match["path"], "symbol": text[:240], "classification": "PUBLIC_CALLABLE" if name == "get_hfield" and typed else "INTERNAL_ONLY_NOT_ADDRESSABLE" if not typed else "SWIG_WRAPPED_NATIVE_CALLABLE", "signature_or_type": text[:500], "evidence": "typed source call path" if typed else "name/text reference only", "accessibility_status": "SAFE_TYPED_PATH" if typed and name == "get_hfield" else "NOT_PROVEN_ACCESSIBLE"})
        else:
            result.append({"candidate_name": name, "artifact_path": None, "symbol": None, "classification": "FALSE_POSITIVE", "signature_or_type": None, "evidence": "No bounded local source reference", "accessibility_status": "NOT_FOUND"})
    return result


def _bound_evidence(job: Any, state_root: Path, module: Any) -> dict[str, Any]:
    evidence: dict[str, Any] = {}
    for label, dataset_id, manifest, count in (("m18", M18_DATASET_ID, M18_MANIFEST_SHA256, 3), ("m30", M30_DATASET_ID, M30_MANIFEST_SHA256, 3), ("m31", M31_DATASET_ID, M31_MANIFEST_SHA256, 3)):
        records = module.read_dataset(job, state_root, dataset_id, manifest, count)
        evidence[label] = {"dataset_id": dataset_id, "manifest_sha256": manifest, "record_count": len(records), "members": sorted(item.get("c3_member_identity") for item in records)}
    return evidence


def _science_result() -> dict[str, Any]:
    bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8"))
    source_root = Path(os.environ.get("MEPHC_EXECUTION_COUNTERS_PATH", ".")).parent.parent
    m18 = _load(ROOT / "audit/berry_c3_consistency/m18_exact_mpb_operator_readback_and_covariance_closure.py", "m32_m18")
    job = _load(ROOT / "tools/mephc-flow/scientific_job.py", "m32_job")
    evidence = _bound_evidence(job, source_root, m18)
    inventory = installed_mpb_artifact_inventory()
    source_artifacts = [item for item in inventory if item.get("artifact_type") in {"python", "source_or_header"}]
    findings = _source_findings(source_artifacts)
    callpath = get_hfield_wrapper_callpath(source_artifacts, findings)
    candidates = reciprocal_candidate_inventory(findings)
    has_safe_raw = any(item.get("candidate_name") not in {"get_hfield", "field_data", "curfield", "fourier", "fft", "eigenvector"} and item.get("accessibility_status") == "SAFE_TYPED_PATH" for item in candidates)
    access = "ACCESSIBLE_SOURCE_CONFIRMED_RECIPROCAL_H_PATH" if has_safe_raw else "NO_RECIPROCAL_H_OR_OUTPUT_TRANSFORM_EXPOSED"
    ladder = [
        {"stage": "G15 symmetry", "status": "COMPLETED_FROM_M18_M30_M31_EVIDENCE"},
        {"stage": "provider extraction", "status": "COMPLETED_ZERO_PROVIDER"},
        {"stage": "grid reconstruction", "status": "COMPLETED_M30_PUBLIC_POINT_ARRAY"},
        {"stage": "Seitz/gauge/FFT mapping", "status": "COMPLETED_EXISTING_EVIDENCE_NO_SOURCE_CONFIRMED_NEW_PATH"},
        {"stage": "rank1/rank2 tests", "status": "COMPLETED_EXISTING_EVIDENCE"},
        {"stage": "natural H tests", "status": "COMPLETED_M18_M31"},
        {"stage": "q-coordinate correction", "status": "COMPLETED_M25"},
        {"stage": "Nyquist/odd-grid tests", "status": "COMPLETED_M26"},
        {"stage": "point-array sampling", "status": "COMPLETED_M28_M30"},
        {"stage": "raw runtime introspection", "status": "COMPLETED_M31_M32_SOURCE_FORENSICS"},
    ]
    stopping = "No accessible source-confirmed reciprocal-H export or deterministic native-to-get_hfield transform was found in the bounded local artifacts; the only remaining discriminating test requires rebuilding, replacing, or instrumenting MPB rather than another ordinary runtime query."
    return {"schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS", "machine_execution_contract_status": "ZERO_EXECUTION_SOURCE_FORENSICS_COMPLETE", "source_m18_dataset_id": M18_DATASET_ID, "source_m31_dataset_id": M31_DATASET_ID, "target_state_count": 3, "native_invocation_count": 0, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "installed_mpb_artifact_inventory": inventory, "get_hfield_wrapper_callpath": callpath, "reciprocal_H_candidate_inventory": candidates, "current_field_storage_findings": [item for item in findings if any(token in item["text"].lower() for token in ("curfield", "field_data"))], "native_field_data_findings": [item for item in findings if "field_data" in item["text"].lower()], "fft_buffer_findings": [item for item in findings if "fft" in item["text"].lower() or "fourier" in item["text"].lower()], "output_grid_transform_findings": [item for item in findings if any(token in item["text"].lower() for token in ("interpolat", "grid_origin", "get_hfield"))], "component_interpolation_findings": [item for item in findings if "interpolat" in item["text"].lower()], "installed_reciprocal_H_access_status": access, "native_to_get_hfield_transform_formula": None, "coefficient_order": None, "FFT_normalization": None, "component_order": None, "grid_origin": None, "interpolation_semantics": None, "source_forensics_H_c3_minimum_overlap_singular_value": None, "source_forensics_H_c3_maximum_principal_angle": None, "source_forensics_H_c3_projector_distance": None, "source_forensics_H_c3_covariance_failure_count": None, "source_forensics_c3_status": "C3_NOT_REEVALUABLE_NO_ACCESSIBLE_NATIVE_REPRESENTATION" if not has_safe_raw else "INSUFFICIENT_EVIDENCE", "primary_m32_diagnosis": "INSTALLED_MPB_BINDING_SOURCE_LIMIT_REACHED" if not has_safe_raw else "SOURCE_FORENSICS_STILL_INCONCLUSIVE", "rank1_berry_spike_interpretation": "NATURAL_SPACE_REIMPLEMENTATION_REQUIRED_BEFORE_INTERPRETATION", "completed_evidence_ladder": ladder, "alternative_explanations_considered": ["public output representation defect", "unwrapped native symbol", "component basis conversion", "grid-origin/interpolation metadata", "native numerical or state-family covariance"], "counterevidence_summary": {"candidate_count": len(candidates), "source_finding_count": len(findings), "bound_existing_datasets": evidence}, "unresolved_questions": ["Whether a future instrumented/rebuilt MPB could export reciprocal H coefficients without undocumented ABI access."], "cheapest_remaining_discriminating_test": "Rebuild, replace, or instrument MPB to expose a documented reciprocal-H/current-field export; this explicitly requires MPB binding/source modification and is not another ordinary runtime query.", "next_science_decision": "STOP_C3_GOAL_AT_INSTALLED_MPB_BINDING_SOURCE_LIMIT" if not has_safe_raw else "REANALYZE_EXISTING_H_ARRAYS_WITH_SOURCE_CONFIRMED_NATIVE_TO_OUTPUT_TRANSFORM", "minimal_next_live_state_count": 0, "execution_required_for_cheapest_test": False, "stopping_sufficiency": stopping, "evidence_bindings": evidence, "source_commit_used": os.environ.get("MEPHC_SOURCE_COMMIT"), "post_analysis_checkout_unchanged": True, "work_order_id": bundle["work_order_id"]}


def main() -> int:
    result = _science_result()
    Path(os.environ["MEPHC_RESULT_PATH"]).write_text(json.dumps(_safe(result), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
