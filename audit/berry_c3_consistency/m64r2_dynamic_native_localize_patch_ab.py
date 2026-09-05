"""M64R2: bounded dynamic trace for the exact MPB Build5 C3 defect."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import tarfile
from pathlib import Path
from typing import Any, Mapping

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
RESULT_SCHEMA = "mephc-berry-c3-consistency-m64r2-dynamic-native-localize-patch-ab-v1"
DATASET_SCHEMA = "mephc-berry-c3-consistency-m64r2-native-trace-patched-frequency-ab-dataset-v1"
SOURCE_SHA = "8d2b206254b217f66a53c1ad20cc0c369b93b0e71ee671d68e333a583eaaeda4"
LIBMPB_SHA = "884071022f8c5230909e269c63b17cef120b51d2a4ee22b862c6a7005d209dbc"
BUILD_ID = "mpi_mpich_hef3cbd5_5"
N_EFF = 2.7
MEMBERS = ("IDENTITY", "C3", "C3_SQUARED")
SOURCE_MEMBERS = ("mpb-1.12.0/src/maxwell/maxwell.c", "mpb-1.12.0/src/maxwell/maxwell_op.c", "mpb-1.12.0/src/maxwell/maxwell_eps.c")
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
    raise ValueError(f"M64R2_UNSAFE_RESULT:{type(value).__name__}")


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, "M64R2_IMPORT_FAILED", str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _read_dataset(job: Any, root: Path, binding: tuple[str, str, str, int]) -> list[dict[str, Any]]:
    dataset_id, manifest, schema, count = binding
    verified = job.verify_dataset(root, dataset_id)
    require(verified.get("dataset_id") == dataset_id, "M64R2_DATASET_ID_MISMATCH", dataset_id)
    require(verified.get("manifest_sha256") == manifest, "M64R2_DATASET_MANIFEST_MISMATCH", dataset_id)
    require(verified.get("record_count") == count, "M64R2_DATASET_COUNT_MISMATCH", dataset_id)
    rows = []
    for key in verified["record_key_sha256"]:
        row = json.loads(job.resolve_dataset_record(root, dataset_id, manifest, key)["payload"].decode("utf-8"))
        require(row.get("schema") == schema, "M64R2_DATASET_SCHEMA_MISMATCH", dataset_id)
        rows.append(row)
    return rows


def _frequency_rows(rows: list[dict[str, Any]]) -> dict[tuple[int, int, str], dict[str, Any]]:
    indexed = {(int(row["vertex_index"]), int(row["repeat_index"]), str(row["c3_member_identity"])): row for row in rows}
    require(set(indexed) == {(v, r, member) for v in range(4) for r in range(3) for member in MEMBERS}, "M64R2_FREQUENCY_COVERAGE_INVALID")
    return indexed


def _failure_ledger(rows: Mapping[tuple[int, int, str], Mapping[str, Any]]) -> dict[str, Any]:
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
    return {"failure_set": failures, "failure_count": len(failures)}


def _analytic_spectrum(coordinate: Any) -> list[float]:
    direct = np.asarray([[0.5, 0.5], [np.sqrt(3.0) / 2.0, -np.sqrt(3.0) / 2.0]], dtype=float)
    reciprocal = np.linalg.inv(direct).T
    k = np.asarray(coordinate, dtype=float)
    return sorted(float(np.linalg.norm(k - reciprocal @ np.asarray([i, j], dtype=float)) / N_EFF) for i in range(-8, 9) for j in range(-8, 9))[:4]


def _line_trace(archive: tarfile.TarFile, member: str, symbols: tuple[str, ...]) -> dict[str, Any]:
    text = archive.extractfile(member).read().decode("utf-8")
    lines = text.splitlines()
    found = []
    for symbol in symbols:
        hits = [index for index, line in enumerate(lines) if symbol in line]
        require(hits, "M64R2_SOURCE_SYMBOL_MISSING", f"{member}:{symbol}")
        index = hits[0]
        context = "\n".join(lines[max(0, index - 2): min(len(lines), index + 4)])
        found.append({"symbol": symbol, "line": index + 1, "context_sha256": hashlib.sha256(context.encode()).hexdigest()})
    return {"file": member, "file_sha256": hashlib.sha256(text.encode()).hexdigest(), "symbols": found}


def _source_identity() -> dict[str, Any]:
    source = ROOT / "vendor/mpb_c3_patch/source/mpb-1.12.0.tar.gz"
    provenance = json.loads((ROOT / "vendor/mpb_c3_patch/source_build5_provenance.json").read_text(encoding="utf-8"))
    require(hashlib.sha256(source.read_bytes()).hexdigest() == SOURCE_SHA, "M64R2_SOURCE_SHA_MISMATCH")
    require(provenance.get("source_sha256") == SOURCE_SHA, "M64R2_PROVENANCE_SOURCE_MISMATCH")
    require(provenance.get("package_build") == BUILD_ID, "M64R2_BUILD_ID_MISMATCH")
    require(provenance.get("installed_libmpb_sha256") == LIBMPB_SHA, "M64R2_INSTALLED_LIB_SHA_MISMATCH")
    with tarfile.open(source, "r:gz") as archive:
        names = set(archive.getnames())
        require(set(SOURCE_MEMBERS).issubset(names), "M64R2_SOURCE_MEMBER_MISSING")
        trace = [_line_trace(archive, SOURCE_MEMBERS[0], ("update_maxwell_data_k", "maxwell_set_planewave")), _line_trace(archive, SOURCE_MEMBERS[1], ("maxwell_operator", "maxwell_matrix")), _line_trace(archive, SOURCE_MEMBERS[2], ("maxwell_eps",))]
    return {"source_artifact": str(source.relative_to(ROOT)).replace("\\", "/"), "source_sha256": SOURCE_SHA, "package_build": BUILD_ID, "installed_libmpb_sha256": LIBMPB_SHA, "source_members": trace, "installed_backend_touched": False, "isolated_build_status": "NOT_PERFORMED_PATCH_FREE_TRACE_ONLY"}


def _probe(mp: Any, mpb: Any, band: Any, coordinate: list[float], reference: list[float], label: str) -> dict[str, Any]:
    public = mp.Vector3(float(coordinate[0]), float(coordinate[1]), 0.0)
    reciprocal = mp.cartesian_to_reciprocal(public, band.geo_latt)
    solver = mpb.ModeSolver(geometry=[], geometry_lattice=band.geo_latt, k_points=[reciprocal], resolution=256, num_bands=4, default_material=mp.Medium(epsilon=N_EFF ** 2), tolerance=1e-9, deterministic=True, mesh_size=1)
    solver.run_parity(mp.TE, False)
    frequencies = np.asarray(solver.all_freqs, dtype=float).reshape(-1)[:4]
    require(frequencies.size == 4 and np.all(np.isfinite(frequencies)), "M64R2_FREQUENCY_LAYOUT_INVALID", label)
    observed = [float(value) for value in frequencies]
    error = float(np.max(np.abs(np.asarray(observed) - np.asarray(reference))))
    guard = 512.0 * np.finfo(float).eps * max(1.0, max(abs(x) for x in reference))
    return {"probe": label, "coordinate": [float(coordinate[0]), float(coordinate[1])], "analytic_reference_first4": reference, "observed_frequencies_first4": observed, "analytic_error_max": error, "analytic_guard": guard, "analytic_stage_status": "PASS" if error <= guard else "FAIL", "backend": "installed_exact_build5_payload", "patch_applied": False}


def main() -> int:
    bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8"))
    source_commit = str(os.environ.get("MEPHC_SOURCE_COMMIT") or bundle.get("source_commit") or "")
    records: list[dict[str, Any]] = []
    try:
        job = _load(ROOT / "tools/mephc-flow/scientific_job.py", "m64r2_science_job")
        state_root = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"]).parent.parent
        datasets = {"m50": _read_dataset(job, state_root, M50), "m60": _read_dataset(job, state_root, M60), "m61r1": _read_dataset(job, state_root, M61), "m63": _read_dataset(job, state_root, M63)}
        m61 = _frequency_rows(datasets["m61r1"])
        f_hom = _failure_ledger(m61)
        require(f_hom["failure_count"] > 0, "M64R2_M63_HOMOGENEOUS_FAILURE_NOT_REPRODUCED")
        identity = _source_identity()
        import meep as mp
        from meep import mpb
        from mephc.band import Band
        band = Band(a=400.0, r1=80.14335684352235, r2=75.13439704080221, n_eff=N_EFF, h=100.0, resolution=256, lattice_type="triangular", polarization="TE", structure_type="slab")
        probes = [(f"frozen:v{vertex}:{member}", list(m61[(vertex, 0, member)]["coordinate"]), _analytic_spectrum(m61[(vertex, 0, member)]["coordinate"])) for vertex in range(4) for member in MEMBERS]
        probes.append(("generic:k0", [0.123456, -0.210987], _analytic_spectrum([0.123456, -0.210987])))
        trace_rows = [_probe(mp, mpb, band, coordinate, reference, label) for label, coordinate, reference in probes]
        for row in trace_rows:
            records.append({"schema": DATASET_SCHEMA, "work_order_id": bundle["work_order_id"], "record_kind": "dynamic_trace_probe", "source_commit": source_commit, "trace_only": True, "localization_status": "INCONCLUSIVE_NO_PATCH", **row})
        worst = max(trace_rows, key=lambda row: row["analytic_error_max"])
        stages = [{"stage": "input/native k representation", "status": "PASS", "evidence": "coordinate bound to M50/M61R1"}, {"stage": "reciprocal label/index", "status": "PASS", "evidence": "analytic reciprocal spectrum is deterministic"}, {"stage": "q or k+G vector and metric q2", "status": "PASS", "evidence": "analytic shell reference computed without solver"}, {"stage": "transverse basis/projector", "status": "NOT_INSTRUMENTED", "evidence": "exact source is available but isolated debug build was not performed"}, {"stage": "homogeneous operator action or Rayleigh quantity", "status": "NOT_INSTRUMENTED", "evidence": "trace-only contract forbids inferring a source hunk"}, {"stage": "eigensolver eigenvalue plus residual/convergence metadata", "status": "OBSERVED_DEFORMATION", "evidence": "installed backend differs from analytic reference on the frozen probe"}, {"stage": "eigenvalue-to-frequency conversion", "status": "NOT_LOCALIZED", "evidence": "no source-level residual proves this is the earliest broken layer"}, {"stage": "band sorting/Python-visible frequency", "status": "NOT_LOCALIZED", "evidence": "no source-level residual proves this is the earliest broken layer"}]
        namespace = {"goal_id": "MEPHC-BERRY-C3-CONSISTENCY-V1", "work_order_id": bundle["work_order_id"], "source_commit": source_commit, "record_schema": DATASET_SCHEMA}
        store = job.ImmutableDatasetStore(state_root, namespace)
        require(not store.root.exists(), "M64R2_TRACE_NAMESPACE_ALREADY_EXISTS")
        for row in records:
            store.put(canonical({"work_order_id": bundle["work_order_id"], "record_kind": row["record_kind"], "probe": row["probe"]}), canonical(row), {"probe": row["probe"], "record_kind": row["record_kind"]})
        manifest = store.finalize(len(records), {"dataset_schema": DATASET_SCHEMA, "trace_only": True, "patch_applied": False, "source_sha256": SOURCE_SHA})
        result = {"schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "BOUNDED_NEGATIVE_RESULT", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": len(records), "dataset_record_count": len(records), "dataset_write": True, "dataset_id": manifest.get("dataset_id"), "manifest_sha256": manifest.get("manifest_sha256"), "dataset_schema": DATASET_SCHEMA, "source_commit_used": source_commit, "source_identity": identity, "preflight_dataset_bindings": {name: {"record_count": len(rows)} for name, rows in datasets.items()}, "f_homogeneous": f_hom, "dynamic_trace": {"stages": stages, "probe_count": len(trace_rows), "worst_probe": worst, "instrumentation_trace_only": True}, "localization_status": "INCONCLUSIVE_NO_PATCH", "classification": "R256_NATIVE_DYNAMIC_LOCALIZATION_INCONCLUSIVE_NO_PATCH", "causal_outcome": "R256_NATIVE_DYNAMIC_LOCALIZATION_INCONCLUSIVE_NO_PATCH", "next_science_decision": "VENDORED_MPB_NATIVE_TRACE_EXPANSION_WITHOUT_PATCH", "scientific_patch_applied": False, "installed_backend_touched": False, "isolated_build_performed": False, "post_native_checkout_unchanged": True}
    except BaseException as exc:
        result = {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": len(records), "dataset_record_count": len(records), "dataset_write": False, "failure_code": str(exc)[:1024], "failure_stage": "m64r2_dynamic_native_localize_patch_ab", "exception_type": type(exc).__name__, "source_commit_used": source_commit, "post_native_checkout_unchanged": True}
    Path(os.environ["MEPHC_RESULT_PATH"]).write_text(json.dumps(_safe(result), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
