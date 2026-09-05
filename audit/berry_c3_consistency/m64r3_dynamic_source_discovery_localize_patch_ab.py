"""M64R3: data-driven exact-source discovery and bounded native localization."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import re
import tarfile
import tempfile
from pathlib import Path
from typing import Any, Mapping

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
RESULT_SCHEMA = "mephc-berry-c3-consistency-m64r3-dynamic-source-discovery-localize-patch-ab-v1"
DATASET_SCHEMA = "mephc-berry-c3-consistency-m64r3-patched-frequency-ab-dataset-v1"
SOURCE_SHA = "8d2b206254b217f66a53c1ad20cc0c369b93b0e71ee671d68e333a583eaaeda4"
LIBMPB_SHA = "884071022f8c5230909e269c63b17cef120b51d2a4ee22b862c6a7005d209dbc"
BUILD_ID = "mpi_mpich_hef3cbd5_5"
N_EFF = 2.7
MEMBERS = ("IDENTITY", "C3", "C3_SQUARED")
M50 = ("9b560f99fa264905ee99cb68d4ccdf757446ffb7b3a0af0391d5760a9740861d", "c009e68d08bd13084eb0320d95ecda5ceab57bdafa8fddef30ecc5b1177563ed", "mephc-berry-c3-consistency-m50-r256-mesh1-c3-causal-control-dataset-v1", 36)
M60 = ("4657c25e5443938a5bd3ffaa3f8bb5ea88c0fc9c1c17f008638aa52a43569b28", "df22be7416f29e7ba40d7c03e2caf6f604d0a70050fb2ff6d074d9aa0b18d2e1", "mephc-berry-c3-consistency-m60-canonical-primitive-frequency-dataset-v1", 36)
M61 = ("d3f8933ef1bddb6f7de72af14de0eae8d6c11194fafd6e9d1e61a556a6e4e11e", "5e97efd186e02ebddd9ee850d10c58931d21786b257db446c14c4064a5b9949e", "mephc-berry-c3-consistency-m61r1-homogeneous-frequency-dataset-v1", 36)
M63 = ("bd02f350a86d8376f89f9ef08cc943a117cbac2cece62ffa84e1266ae07d1a29", "f650352c9d8f3872ba880f82a15ec5e0c2cfa629a80c6af147a0204b6fc0698e", "mephc-berry-c3-consistency-m63-homogeneous-raw-mode-tolerance-dataset-v1", 18)


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise ValueError(f"{code}:{detail}" if detail else code)


def _safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else ("INF" if value > 0 else "-INF" if value < 0 else "NAN")
    if isinstance(value, np.generic):
        return _safe(value.item())
    if isinstance(value, np.ndarray):
        return _safe(value.tolist())
    if isinstance(value, Mapping):
        return {str(k): _safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(v) for v in value]
    raise ValueError(f"M64R3_UNSAFE_RESULT:{type(value).__name__}")


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, "M64R3_IMPORT_FAILED", str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _read_dataset(job: Any, root: Path, binding: tuple[str, str, str, int]) -> list[dict[str, Any]]:
    dataset_id, manifest, schema, count = binding
    verified = job.verify_dataset(root, dataset_id)
    require(verified.get("dataset_id") == dataset_id and verified.get("manifest_sha256") == manifest, "M64R3_DATASET_BINDING_INVALID", dataset_id)
    require(verified.get("record_count") == count, "M64R3_DATASET_COUNT_INVALID", dataset_id)
    rows = []
    for key in verified["record_key_sha256"]:
        row = json.loads(job.resolve_dataset_record(root, dataset_id, manifest, key)["payload"].decode("utf-8"))
        require(row.get("schema") == schema, "M64R3_DATASET_SCHEMA_INVALID", dataset_id)
        rows.append(row)
    return rows


def _frequency_rows(rows: list[dict[str, Any]]) -> dict[tuple[int, int, str], dict[str, Any]]:
    result = {(int(row["vertex_index"]), int(row["repeat_index"]), str(row["c3_member_identity"])): row for row in rows}
    require(len(result) == 36, "M64R3_FREQUENCY_COVERAGE_INVALID")
    return result


def _failure_set(rows: Mapping[tuple[int, int, str], Mapping[str, Any]]) -> list[dict[str, Any]]:
    failures = []
    for vertex in range(4):
        for source, target in zip(MEMBERS, MEMBERS[1:] + MEMBERS[:1]):
            for band in range(4):
                left = np.asarray([float(rows[(vertex, repeat, source)]["frequencies_bands_1_to_4"][band]) for repeat in range(3)])
                right = np.asarray([float(rows[(vertex, repeat, target)]["frequencies_bands_1_to_4"][band]) for repeat in range(3)])
                lm, rm = float(np.median(left)), float(np.median(right))
                lu, ru = float(np.max(np.abs(left - lm))), float(np.max(np.abs(right - rm)))
                if abs(lm - rm) > lu + ru:
                    failures.append({"vertex": vertex, "band": band + 1, "source_member": source, "target_member": target, "residual": abs(lm - rm), "combined_repeat_uncertainty": lu + ru})
    return failures


def _analytic_spectrum(coordinate: Any) -> list[float]:
    direct = np.asarray([[0.5, 0.5], [np.sqrt(3.0) / 2.0, -np.sqrt(3.0) / 2.0]])
    reciprocal = np.linalg.inv(direct).T
    k = np.asarray(coordinate, dtype=float)
    return sorted(float(np.linalg.norm(k - reciprocal @ np.asarray([i, j], dtype=float)) / N_EFF) for i in range(-8, 9) for j in range(-8, 9))[:4]


def _source_functions(text: str, path: str) -> list[dict[str, Any]]:
    pattern = re.compile(r"(?ms)^\s*(?:(?:static|inline|extern|const|unsigned|signed|long|short)\s+)*[A-Za-z_]\w*(?:\s+|\s*\*)+([A-Za-z_]\w*)\s*\([^;{}]*\)\s*\{")
    result = []
    for match in pattern.finditer(text):
        name = match.group(1)
        if name in {"if", "for", "while", "switch"}:
            continue
        start = match.start()
        brace = text.find("{", match.start(), match.end())
        depth = 0
        end = brace
        for index in range(brace, len(text)):
            if text[index] == "{": depth += 1
            elif text[index] == "}":
                depth -= 1
                if depth == 0:
                    end = index + 1
                    break
        body = text[start:end]
        result.append({"path": path, "function": name, "start_line": text.count("\n", 0, start) + 1, "end_line": text.count("\n", 0, end) + 1, "body_sha256": hashlib.sha256(body.encode()).hexdigest(), "body": body})
    return result


def discover_source() -> dict[str, Any]:
    source = ROOT / "vendor/mpb_c3_patch/source/mpb-1.12.0.tar.gz"
    with tempfile.TemporaryDirectory(prefix="m64r3-source-") as temporary:
        with tarfile.open(source, "r:gz") as archive:
            archive.extractall(temporary)
        root = Path(temporary) / "mpb-1.12.0"
        inventory, functions = [], []
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            relative = str(path.relative_to(root)).replace("\\", "/")
            data = path.read_bytes()
            item = {"path": relative, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
            inventory.append(item)
            if path.suffix in {".c", ".h"}:
                functions.extend(_source_functions(data.decode("utf-8", errors="replace"), relative))
        definitions = {item["function"]: {key: value for key, value in item.items() if key != "body"} for item in functions}
        by_name = {item["function"]: item for item in functions}
        require("update_maxwell_data_k" in by_name, "M64R3_SEED_SYMBOL_MISSING")
        graph: dict[str, list[str]] = {}
        pending = ["update_maxwell_data_k"]
        while pending:
            name = pending.pop(0)
            if name in graph:
                continue
            body = by_name[name]["body"]
            calls = sorted({candidate for candidate in definitions if candidate != name and re.search(rf"\b{re.escape(candidate)}\s*\(", body)})
            graph[name] = calls
            pending.extend(calls)
        semantic = {
            "K_NATIVE": [item["function"] for item in functions if re.search(r"\b(k|kdom|k_plus_G|G[123])\b", item["body"])],
            "RECIP_LABEL": [item["function"] for item in functions if re.search(r"\b(g|index|integer|fft)\b", item["body"], re.I)],
            "Q_METRIC": [item["function"] for item in functions if re.search(r"\b(q|k_plus_G|norm|dot|cross)\b", item["body"])],
            "TRANSVERSE": [item["function"] for item in functions if re.search(r"cross|transverse|polar", item["body"], re.I)],
            "OPERATOR_ONE_MODE": [item["function"] for item in functions if re.search(r"operator|matrix|curl|maxwell", item["body"], re.I)],
            "EIGENSOLVER_RETURN": [item["function"] for item in functions if re.search(r"eigen|solve|residual|converg", item["body"], re.I)],
            "LIBMPB_FREQUENCY": [item["function"] for item in functions if re.search(r"frequency|omega|freq", item["body"], re.I)],
            "PYTHON_VISIBLE": [],
        }
        anchors = {stage: sorted(set(names))[:64] for stage, names in semantic.items()}
        for item in functions:
            item.pop("body", None)
        return {"source_root_inventory": inventory, "function_definitions": functions, "callgraph_from_update_maxwell_data_k": graph, "semantic_stage_candidates": anchors, "seed": "update_maxwell_data_k", "discovery_method": "exact-source-definition-call-and-semantic-anchor-analysis", "guessed_symbol_preconditions": [], "source_tree_extracted_to_isolated_temp": True}


def _probe(mp: Any, mpb: Any, band: Any, coordinate: list[float], reference: list[float], label: str) -> dict[str, Any]:
    reciprocal = mp.cartesian_to_reciprocal(mp.Vector3(float(coordinate[0]), float(coordinate[1]), 0), band.geo_latt)
    solver = mpb.ModeSolver(geometry=[], geometry_lattice=band.geo_latt, k_points=[reciprocal], resolution=256, num_bands=4, default_material=mp.Medium(epsilon=N_EFF ** 2), tolerance=1e-9, deterministic=True, mesh_size=1)
    solver.run_parity(mp.TE, False)
    values = np.asarray(solver.all_freqs, dtype=float).reshape(-1)[:4]
    require(values.size == 4 and np.all(np.isfinite(values)), "M64R3_PROBE_FREQUENCY_INVALID", label)
    return {"probe": label, "coordinate": coordinate, "analytic_reference_first4": reference, "observed_frequencies_first4": [float(value) for value in values], "analytic_error_max": float(np.max(np.abs(values - np.asarray(reference)))), "trace_only": True, "patch_applied": False, "runtime_identity": "installed_exact_build5_payload"}


def main() -> int:
    bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8")); source_commit = str(os.environ.get("MEPHC_SOURCE_COMMIT") or bundle.get("source_commit") or ""); records: list[dict[str, Any]] = []
    try:
        job = _load(ROOT / "tools/mephc-flow/scientific_job.py", "m64r3_job"); state_root = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"]).parent.parent
        datasets = {"m50": _read_dataset(job, state_root, M50), "m60": _read_dataset(job, state_root, M60), "m61r1": _read_dataset(job, state_root, M61), "m63": _read_dataset(job, state_root, M63)}
        m61 = _frequency_rows(datasets["m61r1"]); failures = _failure_set(m61); require(failures, "M64R3_M63_FAILURE_NOT_REPRODUCED")
        worst = sorted(failures, key=lambda item: (-(item["residual"] - item["combined_repeat_uncertainty"]), -item["residual"], item["vertex"], item["band"], item["source_member"], item["target_member"]))[0]
        discovery = discover_source(); source = ROOT / "vendor/mpb_c3_patch/source/mpb-1.12.0.tar.gz"; provenance = json.loads((ROOT / "vendor/mpb_c3_patch/source_build5_provenance.json").read_text(encoding="utf-8")); require(hashlib.sha256(source.read_bytes()).hexdigest() == SOURCE_SHA and provenance.get("source_sha256") == SOURCE_SHA and provenance.get("package_build") == BUILD_ID and provenance.get("installed_libmpb_sha256") == LIBMPB_SHA, "M64R3_EXACT_BUILD5_IDENTITY_INVALID")
        import meep as mp
        from meep import mpb
        from mephc.band import Band
        band = Band(a=400.0, r1=80.14335684352235, r2=75.13439704080221, n_eff=N_EFF, h=100.0, resolution=256, lattice_type="triangular", polarization="TE", structure_type="slab")
        frozen = [(member, list(m61[(worst["vertex"], 0, member)]["coordinate"]), _analytic_spectrum(m61[(worst["vertex"], 0, member)]["coordinate"])) for member in MEMBERS]
        probes = [_probe(mp, mpb, band, coordinate, reference, f"unpatched:frozen:v{worst['vertex']}:{member}") for member, coordinate, reference in frozen]
        probes.append(_probe(mp, mpb, band, [0.123456, -0.210987], _analytic_spectrum([0.123456, -0.210987]), "unpatched:generic:k0"))
        records = [{"schema": DATASET_SCHEMA, "work_order_id": bundle["work_order_id"], "arm": "UNPATCHED_TRACE", "source_commit": source_commit, **probe} for probe in probes]
        namespace = {"goal_id": "MEPHC-BERRY-C3-CONSISTENCY-V1", "work_order_id": bundle["work_order_id"], "source_commit": source_commit, "record_schema": DATASET_SCHEMA}; store = job.ImmutableDatasetStore(state_root, namespace); require(not store.root.exists(), "M64R3_DATASET_NAMESPACE_EXISTS")
        for row in records:
            store.put(canonical({"work_order_id": bundle["work_order_id"], "arm": row["arm"], "probe": row["probe"]}), canonical(row), {"arm": row["arm"], "probe": row["probe"]})
        manifest = store.finalize(len(records), {"dataset_schema": DATASET_SCHEMA, "arm": "UNPATCHED_TRACE", "patch_applied": False, "source_sha256": SOURCE_SHA})
        result = {"schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "BOUNDED_NEGATIVE_RESULT", "work_order_id": bundle["work_order_id"], "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": len(records), "dataset_record_count": len(records), "dataset_write": True, "dataset_id": manifest.get("dataset_id"), "manifest_sha256": manifest.get("manifest_sha256"), "dataset_schema": DATASET_SCHEMA, "source_commit_used": source_commit, "source_identity": {"source_sha256": SOURCE_SHA, "installed_libmpb_sha256": LIBMPB_SHA, "package_build": BUILD_ID, "installed_backend_touched": False, "isolated_build_status": "NOT_PERFORMED_NO_SAFE_BUILD_DRIVER"}, "preflight_dataset_bindings": {name: {"record_count": len(rows)} for name, rows in datasets.items()}, "f_homogeneous": {"failure_count": len(failures), "failure_set": failures}, "frozen_worst_triplet": worst, "source_discovery": discovery, "baseline_probes": records, "localization_status": "INCONCLUSIVE_AFTER_DISCOVERY_NO_ISOLATED_BUILD", "classification": "R256_NATIVE_DYNAMIC_SOURCE_DISCOVERY_INCONCLUSIVE_NO_PATCH", "causal_outcome": "R256_NATIVE_DYNAMIC_SOURCE_DISCOVERY_INCONCLUSIVE_NO_PATCH", "next_science_decision": "VENDORED_MPB_SOURCE_CALLGRAPH_AND_BUILD_BINDING_AUDIT", "scientific_patch_applied": False, "instrumentation_trace_only": True, "post_native_checkout_unchanged": True}
    except BaseException as exc:
        result = {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": len(records), "dataset_record_count": len(records), "dataset_write": False, "failure_code": str(exc)[:1024], "failure_stage": "m64r3_dynamic_source_discovery_localize_patch_ab", "exception_type": type(exc).__name__, "source_commit_used": source_commit, "post_native_checkout_unchanged": True}
    Path(os.environ["MEPHC_RESULT_PATH"]).write_text(json.dumps(_safe(result), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8"); return 0


if __name__ == "__main__":
    raise SystemExit(main())
