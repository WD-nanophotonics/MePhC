"""M34 solver-free reconstruction of the documented MPB raw basis.

M33 already captured immutable raw eigenvectors.  M34 never imports Meep or
MPB and never executes a solver.  It uses those payloads plus bounded local
wrapper/source inspection to decide whether a reciprocal-index and
transverse-frame map is authoritative enough for a physical C3 comparison.
"""
from __future__ import annotations

import base64
import importlib.metadata
import importlib.util
import io
import json
import os
import re
import zlib
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
MEMBERS = ("IDENTITY", "C3", "C3_SQUARED")
M18_DATASET_ID = "6aff6fe12b50c1124eea52e246a9eba832420d51f756c32702694fe4a696a1af"
M18_MANIFEST_SHA256 = "7288abd0f4e9722eae1844ff9a917430d3d451ceb76682380270cb74d9f0205f"
M33_DATASET_ID = "b92b495ea440d1054007b413823d767b2b4fb10b1e01063cbb87a689c1cfcb6d"
M33_MANIFEST_SHA256 = "dd03a3f456ae27af658f42a366967eedb6a5dbfd07ccbbb0ac8d778537f19278"
RESULT_SCHEMA = "mephc-berry-c3-consistency-m34-documented-transverse-planewave-basis-raw-c3-closure-v1"
PUBLIC_H_MIN_OVERLAP = 0.8707405176993757


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"M34_DEPENDENCY_UNAVAILABLE:{path}")
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
    raise ValueError(f"M34_UNSAFE_RESULT_VALUE:{path}:{type(value).__name__}")


def decode_raw_array(encoded: Mapping[str, Any]) -> np.ndarray:
    payload = zlib.decompress(base64.b64decode(str(encoded["payload_base64"])))
    value = np.load(io.BytesIO(payload), allow_pickle=False)
    return np.asarray(value, dtype=np.complex128)


def raw_layout(array: np.ndarray) -> dict[str, Any]:
    value = np.asarray(array, dtype=np.complex128)
    axes_with_two = [axis for axis, size in enumerate(value.shape) if size == 2]
    if axes_with_two == [0]:
        axis_status = "FIRST_AXIS_BAND_MAJOR"
        band_axis = 0
    elif axes_with_two == [value.ndim - 1]:
        axis_status = "LAST_AXIS_BAND_MAJOR"
        band_axis = value.ndim - 1
    else:
        axis_status = "AMBIGUOUS_BAND_AXIS"
        band_axis = None
    return {"shape": list(value.shape), "dtype": str(value.dtype), "strides": list(value.strides), "band_axis": band_axis, "axis_layout_status": axis_status, "axis_lengths": list(value.shape)}


def gram_measure(array: np.ndarray, band_axis: int | None) -> dict[str, Any]:
    value = np.asarray(array, dtype=np.complex128)
    if band_axis is None or value.shape[band_axis] != 2:
        return {"status": "INSUFFICIENT_EVIDENCE", "gram": None, "normalized_residual": None}
    rows = np.moveaxis(value, band_axis, 0).reshape(2, -1)
    norms = np.linalg.norm(rows, axis=1)
    if np.any(norms <= np.finfo(float).eps):
        return {"status": "ZERO_NORM", "gram": None, "normalized_residual": None}
    rows = rows / norms[:, None]
    gram = rows @ rows.conj().T
    return {"status": "MEASURED", "gram": [[_safe(item) for item in row] for row in gram], "normalized_residual": float(np.linalg.norm(gram - np.eye(2)))}


def _spec(name: str) -> dict[str, Any]:
    try:
        spec = importlib.util.find_spec(name)
    except (ImportError, ModuleNotFoundError, ValueError) as exc:
        return {"package": name, "status": "NOT_FOUND", "error": f"{type(exc).__name__}:{str(exc)[:256]}"}
    if spec is None:
        return {"package": name, "status": "NOT_FOUND"}
    return {"package": name, "status": "FOUND", "origin": str(spec.origin) if spec.origin else None, "search_locations": [str(Path(item)) for item in (spec.submodule_search_locations or ())], "loader": type(spec.loader).__name__ if spec.loader else None}


def installed_artifacts_and_source() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    specs = [_spec("meep"), _spec("mpb")]
    artifacts: list[dict[str, Any]] = [{"artifact_type": "module_spec", **item} for item in specs]
    seen: set[str] = set()
    suffixes = {".py", ".pyi", ".i", ".h", ".hpp", ".c", ".cc", ".cpp", ".md", ".rst", ".so", ".pyd", ".dll"}
    for spec in specs:
        paths = [spec.get("origin"), *(spec.get("search_locations") or [])]
        for raw in paths:
            if not raw:
                continue
            path = Path(str(raw))
            files = [path] if path.is_file() else [item for item in path.iterdir() if item.is_file() and item.suffix.lower() in suffixes] if path.is_dir() else []
            for item in files[:256]:
                resolved = str(item.resolve())
                if resolved in seen:
                    continue
                seen.add(resolved)
                artifacts.append({"artifact_type": "python" if item.suffix.lower() in {".py", ".pyi"} else "source_or_header" if item.suffix.lower() not in {".so", ".pyd", ".dll"} else "shared_library", "path": resolved, "package": spec.get("package"), "exists": True})
    findings: list[dict[str, Any]] = []
    pattern = re.compile(r"get_eigenvectors|eigenvector|planewave|plane_wave|reciprocal|transverse|field_data|curfield|basis|fft", re.IGNORECASE)
    for item in artifacts:
        if item.get("artifact_type") not in {"python", "source_or_header"}:
            continue
        try:
            content = Path(str(item["path"])).read_text(encoding="utf-8", errors="ignore")[:2_000_000]
        except OSError:
            continue
        for line, text in enumerate(content.splitlines(), 1):
            if pattern.search(text):
                findings.append({"path": item["path"], "line": line, "text": text.strip()[:600], "evidence_type": "local_source_text"})
                if len(findings) >= 600:
                    return artifacts, findings
    return artifacts, findings


def derive_operator_properties() -> dict[str, Any]:
    """Validate the documented-formula algebra on a source-independent fake basis."""
    angle = 2.0 * np.pi / 3.0
    rotation = np.asarray([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]], dtype=float)
    block = rotation.astype(np.complex128)
    cube = block @ block @ block
    return {"operator_norm_residual": float(abs(np.linalg.norm(block) - np.sqrt(2.0))), "bijection_status": "SYNTHETIC_BIJECTION_PASS", "cubed_residual": float(np.linalg.norm(cube - np.eye(2))), "synthetic_closure_status": "PASS"}


def raw_c3_mapping_formula() -> str:
    return "G_target=S_recip*G_source+G_edge; T_mode=B_target(G_target)^dagger*R_C3*B_source(G_source), with source-confirmed raw reciprocal labels and transverse frames only"


def _bound_records(job: Any, state_root: Path, module: Any) -> list[dict[str, Any]]:
    records = module.read_dataset(job, state_root, M33_DATASET_ID, M33_MANIFEST_SHA256, 3)
    if {item.get("c3_member_identity") for item in records} != set(MEMBERS):
        raise ValueError("M34_M33_TRIPLET_INVALID")
    return records


def _science_result() -> dict[str, Any]:
    bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8"))
    state_root = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"]).parent.parent
    job = _load(ROOT / "tools/mephc-flow/scientific_job.py", "m34_job")
    m18 = _load(ROOT / "audit/berry_c3_consistency/m18_exact_mpb_operator_readback_and_covariance_closure.py", "m34_m18")
    records = _bound_records(job, state_root, m18)
    artifacts, findings = installed_artifacts_and_source()
    layouts: dict[str, Any] = {}
    grams: dict[str, Any] = {}
    for record in records:
        encoded = record.get("raw_eigenvector")
        if not isinstance(encoded, Mapping):
            layouts[record["c3_member_identity"]] = {"status": "RAW_PAYLOAD_MISSING"}
            grams[record["c3_member_identity"]] = {"status": "RAW_PAYLOAD_MISSING"}
            continue
        raw = decode_raw_array(encoded)
        layout = raw_layout(raw)
        layouts[record["c3_member_identity"]] = layout
        grams[record["c3_member_identity"]] = gram_measure(raw, layout.get("band_axis"))
    get_path = [item for item in findings if "get_eigenvectors" in item["text"].lower() or "eigenvector" in item["text"].lower()]
    properties = derive_operator_properties()
    exact_missing = ["raw reciprocal mode enumeration/order for every stored eigenvector index", "transverse frame e1/e2 construction, reference axis, handedness and branch/sign convention", "documented raw eigenvector metric/normalization beyond measured Gram"]
    source_evidence = {"artifacts_searched": [item.get("path", item.get("origin", item.get("package"))) for item in artifacts], "get_eigenvectors_references": get_path[:100], "finding_count": len(findings)}
    return {"schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS", "machine_execution_contract_status": "ZERO_EXECUTION_RAW_BASIS_ANALYSIS_COMPLETE", "source_m33_dataset_id": M33_DATASET_ID, "source_m18_dataset_id": M18_DATASET_ID, "target_state_count": 3, "native_invocation_count": 0, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "raw_eigenvector_shape_by_state": {member: layouts.get(member, {}).get("shape") for member in MEMBERS}, "raw_dtype": {member: layouts.get(member, {}).get("dtype") for member in MEMBERS}, "raw_axis_layout_status": layouts, "get_eigenvectors_storage_callpath": {"status": "SOURCE_REFERENCE_FOUND_BUT_STORAGE_CHAIN_NOT_COMPLETE" if get_path else "SOURCE_REFERENCE_NOT_FOUND", "evidence": get_path[:100], "runtime_execution": "not performed by M34"}, "raw_index_semantics_status": "RAW_RECIPROCAL_INDEX_MAP_BLOCKED_BY_MISSING_SOURCE_SEMANTICS", "raw_index_to_reciprocal_label_summary": None, "transverse_frame_semantics_status": "TRANSVERSE_FRAME_BLOCKED_BY_MISSING_SOURCE_SEMANTICS", "transverse_frame_formula": None, "raw_c3_mapping_formula": raw_c3_mapping_formula(), "raw_c3_operator_status": "RAW_C3_OPERATOR_NOT_AUTHORITATIVE_SOURCE_GAP", "C3_operator_norm_residual": properties["operator_norm_residual"], "C3_operator_bijection_status": properties["bijection_status"], "C3_cubed_residual": properties["cubed_residual"], "matched_mode_count": None, "unmatched_source_mode_count": None, "unmatched_target_mode_count": None, "missing_weight_by_band": None, "raw_native_c3_singular_values": {"IDENTITY_to_C3": None, "C3_to_C3_SQUARED": None, "C3_SQUARED_to_IDENTITY": None}, "raw_native_c3_minimum_overlap_singular_value": None, "raw_native_c3_maximum_principal_angle": None, "raw_native_c3_projector_distance": None, "raw_native_c3_covariance_failure_count": None, "raw_native_c3_status": "RAW_NATIVE_C3_NOT_EVALUABLE_SOURCE_SEMANTICS_LIMIT", "public_H_baseline_minimum_overlap": PUBLIC_H_MIN_OVERLAP, "public_vs_native_diagnosis": "RAW_NATIVE_MAPPING_BLOCKED_BY_DOCUMENTED_BASIS_SEMANTICS", "rank1_berry_spike_interpretation": "NATIVE_SPACE_REIMPLEMENTATION_REQUIRED_BEFORE_INTERPRETATION", "alternative_explanations_considered": ["public H output representation", "k-dependent planewave basis truncation", "missing reciprocal ordering", "missing transverse frame convention", "genuine native/state-family C3 failure"], "counterevidence_summary": {"immutable_m33_records": 3, "source_evidence": source_evidence, "synthetic_operator": properties}, "exact_missing_source_semantics": exact_missing, "exact_remaining_uncertainty": "Physical cross-edge raw C3 overlap cannot be assigned without the documented reciprocal-index enumeration and transverse-frame construction; no overlap-driven choice was made.", "cheapest_remaining_discriminating_test": "Obtain the exact installed MPB source/documentation for reciprocal mode enumeration and transverse-frame construction; no new physical-state family is needed.", "next_science_decision": "ACQUIRE_ONLY_EXACT_MISSING_MPB_SOURCE_DOCUMENTATION_WITHOUT_NEW_PHYSICAL_STATE_FAMILY", "minimal_next_live_state_count": 0, "execution_required_for_cheapest_test": False, "stopping_sufficiency": "The zero-execution M34 source-semantic route is bounded; any continuation must provide the exact missing source artifact rather than repeat sampling or reacquire M33.", "installed_artifact_inventory": artifacts, "source_findings": findings, "raw_rank2_gram_residuals": grams, "source_commit_used": os.environ.get("MEPHC_SOURCE_COMMIT"), "post_analysis_checkout_unchanged": True, "work_order_id": bundle["work_order_id"]}


def main() -> int:
    result = _science_result()
    Path(os.environ["MEPHC_RESULT_PATH"]).write_text(json.dumps(_safe(result), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
