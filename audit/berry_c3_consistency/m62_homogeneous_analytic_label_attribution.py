"""M62: attribute homogeneous C3 failures to reciprocal label or value paths."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
M54_PATH = ROOT / "audit/berry_c3_consistency/m54_r256_material_grid_subpixel_c3_readback_ab.py"
SPEC = importlib.util.spec_from_file_location("m62_m54_reference", M54_PATH)
assert SPEC and SPEC.loader
m54 = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(m54)

RESULT_SCHEMA = "mephc-berry-c3-consistency-m62-homogeneous-analytic-label-attribution-v1"
M50_DATASET_ID = "9b560f99fa264905ee99cb68d4ccdf757446ffb7b3a0af0391d5760a9740861d"
M50_MANIFEST = "c009e68d08bd13084eb0320d95ecda5ceab57bdafa8fddef30ecc5b1177563ed"
M50_SCHEMA = "mephc-berry-c3-consistency-m50-r256-mesh1-c3-causal-control-dataset-v1"
M61R1_DATASET_ID = "d3f8933ef1bddb6f7de72af14de0eae8d6c11194fafd6e9d1e61a556a6e4e11e"
M61R1_MANIFEST = "5e97efd186e02ebddd9ee850d10c58931d21786b257db446c14c4064a5b9949e"
M61R1_SCHEMA = "mephc-berry-c3-consistency-m61r1-homogeneous-frequency-dataset-v1"
MEMBERS = ("IDENTITY", "C3", "C3_SQUARED")
N_EFF = 2.7
A = np.asarray([[0.5, 0.5], [np.sqrt(3.0) / 2.0, -np.sqrt(3.0) / 2.0]], dtype=float)
B = np.linalg.inv(A).T
R3 = np.asarray([[-0.5, -np.sqrt(3.0) / 2.0], [np.sqrt(3.0) / 2.0, -0.5]], dtype=float)


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def require(condition: bool, code: str, detail: str = "") -> None:
    if not condition: raise ValueError(f"{code}:{detail}" if detail else code)


def _safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)): return value
    if isinstance(value, float): return value if math.isfinite(value) else ("INF" if value > 0 else "-INF" if value < 0 else "NAN")
    if isinstance(value, np.generic): return _safe(value.item())
    if isinstance(value, np.ndarray): return _safe(value.tolist())
    if isinstance(value, Mapping): return {str(k): _safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)): return [_safe(v) for v in value]
    raise ValueError(f"M62_UNSAFE_RESULT:{type(value).__name__}")


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path); require(spec is not None and spec.loader is not None, "M62_IMPORT_FAILED", str(path)); module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


def _read_dataset(job: Any, root: Path, dataset_id: str, manifest: str, schema: str, count: int) -> list[dict[str, Any]]:
    verified = job.verify_dataset(root, dataset_id); require(verified.get("dataset_id") == dataset_id and verified.get("manifest_sha256") == manifest and verified.get("record_count") == count, "M62_DATASET_BINDING_INVALID", dataset_id); rows = []
    for key in verified["record_key_sha256"]:
        row = json.loads(job.resolve_dataset_record(root, dataset_id, manifest, key)["payload"].decode("utf-8")); require(isinstance(row, dict) and row.get("schema") == schema, "M62_DATASET_SCHEMA_INVALID", dataset_id); rows.append(row)
    return rows


def frequency_rows(records: list[dict[str, Any]]) -> dict[tuple[int, int, str], dict[str, Any]]:
    rows = {(int(row["vertex_index"]), int(row["repeat_index"]), str(row["c3_member_identity"])): row for row in records}; require(len(rows) == 36 and set(rows) == {(v, r, member) for v in range(4) for r in range(3) for member in MEMBERS}, "M62_FREQUENCY_IDENTITY_SET_INVALID"); return rows


def experimental_frequency_ledger(rows: Mapping[tuple[int, int, str], Mapping[str, Any]]) -> dict[str, Any]:
    failures, ledger = [], {}
    for vertex in range(4):
        for source, target in zip(MEMBERS, MEMBERS[1:] + MEMBERS[:1]):
            for band in range(4):
                left = np.asarray([float(rows[(vertex, repeat, source)]["frequencies_bands_1_to_4"][band]) for repeat in range(3)]); right = np.asarray([float(rows[(vertex, repeat, target)]["frequencies_bands_1_to_4"][band]) for repeat in range(3)]); lm, rm = float(np.median(left)), float(np.median(right)); lu, ru = float(np.max(np.abs(left - lm))), float(np.max(np.abs(right - rm))); item = {"vertex": vertex, "band": band + 1, "source_member": source, "target_member": target, "source_median": lm, "target_median": rm, "source_repeat_uncertainty": lu, "target_repeat_uncertainty": ru, "residual": abs(lm - rm), "combined_repeat_uncertainty": lu + ru, "pass": abs(lm - rm) <= lu + ru}; ledger[f"v{vertex}:{source}_to_{target}:band{band + 1}"] = item
                if not item["pass"]: failures.append(item)
    return {"failure_set": failures, "failure_count": len(failures), "ledger": ledger}


def _catalog_for_coordinate(coordinate: Any, low_window: int = 6, high_window: int = 8, keep: int = 32) -> dict[str, Any]:
    k = np.asarray(coordinate, dtype=float); shell_guard = 512.0 * np.finfo(float).eps
    def entries(window: int) -> list[dict[str, Any]]:
        values = [{"label": [i, j], "frequency": float(np.linalg.norm(k - B @ np.asarray([i, j], dtype=float)) / N_EFF)} for i in range(-window, window + 1) for j in range(-window, window + 1)]
        return sorted(values, key=lambda item: (item["frequency"], item["label"]))[:keep]
    low, high = entries(low_window), entries(high_window); guard = 256.0 * np.finfo(float).eps * max(1.0, max(item["frequency"] for item in low + high)); require(max(abs(a["frequency"] - b["frequency"]) for a, b in zip(low, high)) <= guard, "M62_ANALYTIC_WINDOW_NOT_CONVERGED")
    shells = []
    for item in high:
        shell_guard_value = shell_guard * max(1.0, abs(item["frequency"]))
        if not shells or abs(item["frequency"] - shells[-1]["frequency"]) > shell_guard_value: shells.append({"shell_index": len(shells) + 1, "frequency": item["frequency"], "labels": [item["label"]], "shell_guard": shell_guard_value})
        else: shells[-1]["labels"].append(item["label"])
    ordered = [frequency for shell in shells for frequency in [shell["frequency"]] * len(shell["labels"])]
    return {"coordinate": k.tolist(), "window_L6": low, "window_L8": high, "window_guard": guard, "shells": shells, "ordered_low32": ordered, "low32_hash": hashlib.sha256(canonical(high)).hexdigest()}


def build_label_catalog(rows: Mapping[tuple[int, int, str], Mapping[str, Any]]) -> dict[str, Any]:
    catalog = {}
    for vertex in range(4):
        for member in MEMBERS:
            key = f"v{vertex}:{member}"; item = _catalog_for_coordinate(rows[(vertex, 0, member)]["coordinate"]); persisted = rows[(vertex, 0, member)].get("analytic_reference_first4"); require(persisted is not None, "M62_PERSISTED_ANALYTIC_REFERENCE_MISSING", key); require(np.max(np.abs(np.asarray(item["ordered_low32"][:4]) - np.asarray(persisted))) <= item["window_guard"], "M62_ANALYTIC_FIRST4_MISMATCH", key); catalog[key] = item
    return {"states": catalog, "state_count": len(catalog), "low32_count": 32}


def reciprocal_automorphism() -> np.ndarray:
    S = np.rint(np.linalg.solve(B, R3 @ B)).astype(int); require(np.max(np.abs(S - np.linalg.solve(B, R3 @ B))) <= 256 * np.finfo(float).eps and np.array_equal(S @ S @ S, np.eye(2, dtype=int)), "M62_RECIPROCAL_AUTOMORPHISM_INVALID"); return S


def c3_label_transport(source_labels: list[list[int]], source_coordinate: Any, target_coordinate: Any) -> dict[str, Any]:
    S = reciprocal_automorphism(); delta = R3 @ np.asarray(source_coordinate, dtype=float) - np.asarray(target_coordinate, dtype=float); g_float = np.linalg.solve(B, delta); G = np.rint(g_float).astype(int); guard = 256 * np.finfo(float).eps * max(1.0, float(np.linalg.norm(delta)), float(np.linalg.norm(B @ G))); require(np.max(np.abs(g_float - G)) <= guard and np.linalg.norm(delta - B @ G) <= guard, "M62_C3_EDGE_INVALID"); mapped = (S @ np.asarray(source_labels, dtype=int).T).T - G; return {"S_recip": S.tolist(), "G_edge": G.tolist(), "mapped_labels": mapped.tolist(), "edge_residual": float(np.linalg.norm(delta - B @ G)), "identity_guard": guard}


def assign_band(central: float, uncertainty: float, catalog: Mapping[str, Any]) -> dict[str, Any]:
    compatible = []
    for shell in catalog["shells"]:
        guard = 512 * np.finfo(float).eps * max(1.0, abs(float(shell["frequency"])), abs(float(central))); interval_gap = abs(float(central) - float(shell["frequency"]))
        if interval_gap <= float(uncertainty) + guard: compatible.append({"shell_index": shell["shell_index"], "frequency": shell["frequency"], "labels": shell["labels"], "shell_guard": guard})
    ordered = sorted(catalog["shells"], key=lambda shell: abs(float(central) - float(shell["frequency"])))
    nearest = [{"shell_index": shell["shell_index"], "distance": abs(float(central) - float(shell["frequency"]))} for shell in ordered[:2]]
    if len(compatible) == 1: return {"status": "DEFINITE", "shell": compatible[0], "nearest": nearest, "expected_first4": compatible[0]["shell_index"] <= 4}
    if len(compatible) > 1: return {"status": "AMBIGUOUS_ANALYTIC_SHELL", "compatible": compatible, "nearest": nearest}
    return {"status": "UNMATCHED_ANALYTIC_VALUE", "nearest": nearest}


def state_assignments(rows: Mapping[tuple[int, int, str], Mapping[str, Any]], catalog: Mapping[str, Any]) -> dict[str, Any]:
    output = {}
    for vertex in range(4):
        for member in MEMBERS:
            key = f"v{vertex}:{member}"; bands = []
            for band in range(4):
                values = np.asarray([float(rows[(vertex, repeat, member)]["frequencies_bands_1_to_4"][band]) for repeat in range(3)]); bands.append({"central": float(np.median(values)), "repeat_uncertainty": float(np.max(np.abs(values - np.median(values)))), "assignment": assign_band(float(np.median(values)), float(np.max(np.abs(values - np.median(values)))), catalog["states"][key])})
            output[key] = bands
    return output


def classify_attribution(failure: Mapping[str, Any], source: Mapping[str, Any], target: Mapping[str, Any], transport: Mapping[str, Any] | None = None) -> str:
    if source["assignment"]["status"] == "UNMATCHED_ANALYTIC_VALUE" or target["assignment"]["status"] == "UNMATCHED_ANALYTIC_VALUE": return "UNMATCHED_VALUE"
    if source["assignment"]["status"] != "DEFINITE" or target["assignment"]["status"] != "DEFINITE": return "AMBIGUOUS_SHELL"
    if source["assignment"]["shell"]["shell_index"] != target["assignment"]["shell"]["shell_index"]: return "LABEL_SELECTION_BREAK"
    if transport is not None and set(map(tuple, transport.get("mapped_labels", []))) != set(map(tuple, target["assignment"]["shell"].get("labels", []))): return "LABEL_SELECTION_BREAK"
    return "SAME_SHELL_VALUE_DEFORMATION"


def attribute_failures(failures: list[Mapping[str, Any]], assignments: Mapping[str, Any], rows: Mapping[tuple[int, int, str], Mapping[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for failure in failures:
        vertex, band, source_member, target_member = int(failure["vertex"]), int(failure["band"]), str(failure["source_member"]), str(failure["target_member"]); source = assignments[f"v{vertex}:{source_member}"][band - 1]; target = assignments[f"v{vertex}:{target_member}"][band - 1]; transport = None
        if source["assignment"]["status"] == "DEFINITE": transport = c3_label_transport(source["assignment"]["shell"].get("labels", []), rows[(vertex, 0, source_member)]["coordinate"], rows[(vertex, 0, target_member)]["coordinate"])
        output.append({"failure": dict(failure), "source_assignment": source, "target_assignment": target, "label_transport": transport, "mechanism": classify_attribution(failure, source, target, transport)})
    return output


def classify_outcome(failures: list[Mapping[str, Any]]) -> tuple[str, str]:
    mechanisms = {str(item["mechanism"]) for item in failures}
    if not failures: return "R256_M61R1_HOMOGENEOUS_FAILURE_NOT_REPRODUCED", "SOLVER_FREE_M61R1_HOMOGENEOUS_DATASET_REQUALIFICATION"
    if "UNMATCHED_VALUE" in mechanisms: return "R256_HOMOGENEOUS_C3_BREAK_ANALYTIC_ASSIGNMENT_UNMATCHED", "VENDORED_MPB_HOMOGENEOUS_NATIVE_MODE_METADATA_AUDIT_THEN_PATCH"
    if "AMBIGUOUS_SHELL" in mechanisms: return "R256_HOMOGENEOUS_C3_BREAK_ANALYTIC_ASSIGNMENT_AMBIGUOUS", "VENDORED_MPB_HOMOGENEOUS_NATIVE_MODE_METADATA_AUDIT_THEN_PATCH"
    if mechanisms == {"LABEL_SELECTION_BREAK"}: return "R256_HOMOGENEOUS_C3_BREAK_RECIPROCAL_LABEL_SELECTION", "VENDORED_MPB_RECIPROCAL_BASIS_TRUNCATION_C3_SOURCE_PATCH_AND_HOMOGENEOUS_AB"
    if mechanisms == {"SAME_SHELL_VALUE_DEFORMATION"}: return "R256_HOMOGENEOUS_C3_BREAK_SAME_SHELL_VALUE_DEFORMATION", "VENDORED_MPB_HOMOGENEOUS_OPERATOR_EIGENSOLVER_C3_SOURCE_PATCH_AND_AB"
    return "R256_HOMOGENEOUS_C3_BREAK_MIXED_SELECTION_AND_VALUE_DEFORMATION", "VENDORED_MPB_RECIPROCAL_BASIS_PLUS_OPERATOR_C3_SOURCE_PATCH_WITH_STAGED_AB"


def main() -> int:
    bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8")); source_commit = str(os.environ.get("MEPHC_SOURCE_COMMIT") or bundle.get("source_commit") or "")
    try:
        job = _load(ROOT / "tools/mephc-flow/scientific_job.py", "m62_science_job"); state_root = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"]).parent.parent; m50 = frequency_rows(_read_dataset(job, state_root, M50_DATASET_ID, M50_MANIFEST, M50_SCHEMA, 36)); m61 = frequency_rows(_read_dataset(job, state_root, M61R1_DATASET_ID, M61R1_MANIFEST, M61R1_SCHEMA, 36)); stock = experimental_frequency_ledger(m50); homogeneous = experimental_frequency_ledger(m61); require(homogeneous["failure_set"], "M62_HOMOGENEOUS_FAILURE_NOT_REPRODUCED"); catalog = build_label_catalog(m61); assignments = state_assignments(m61, catalog); failures = attribute_failures(homogeneous["failure_set"], assignments, m50); classification, decision = classify_outcome(failures); result = {"schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 0, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "dataset_schema": None, "source_commit_used": source_commit, "f_stock": stock, "f_homogeneous": homogeneous, "analytic_catalog": catalog, "band_assignments": assignments, "failure_attributions": failures, "classification": classification, "causal_outcome": classification, "next_science_decision": decision, "post_analysis_checkout_unchanged": True}
    except BaseException as exc:
        result = {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 0, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "dataset_schema": None, "failure_code": str(exc)[:1024], "failure_stage": "m62_homogeneous_analytic_label_attribution", "exception_type": type(exc).__name__, "source_commit_used": source_commit, "post_analysis_checkout_unchanged": True}
    Path(os.environ["MEPHC_RESULT_PATH"]).write_text(json.dumps(_safe(result), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8"); return 0


if __name__ == "__main__":
    raise SystemExit(main())
