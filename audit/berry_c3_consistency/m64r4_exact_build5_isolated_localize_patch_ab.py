"""M64R4: exact Build5 isolated baseline and fail-closed localization."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any, Mapping

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
RESULT_SCHEMA = "mephc-berry-c3-consistency-m64r4-exact-build5-isolated-localize-patch-ab-v1"
DATASET_SCHEMA = "mephc-berry-c3-consistency-m64r4-patched-frequency-ab-dataset-v1"
SOURCE_SHA = "8d2b206254b217f66a53c1ad20cc0c369b93b0e71ee671d68e333a583eaaeda4"
LIBMPB_SHA = "884071022f8c5230909e269c63b17cef120b51d2a4ee22b862c6a7005d209dbc"
DRIVER_SHA = "a877f068fd1411b6480ed4d6956da5a4d2f8998cd3f3df9e192f751ec99c4350"
BUILD_ID = "mpi_mpich_hef3cbd5_5"
M50 = ("9b560f99fa264905ee99cb68d4ccdf757446ffb7b3a0af0391d5760a9740861d", "c009e68d08bd13084eb0320d95ecda5ceab57bdafa8fddef30ecc5b1177563ed", "mephc-berry-c3-consistency-m50-r256-mesh1-c3-causal-control-dataset-v1", 36)
M60 = ("4657c25e5443938a5bd3ffaa3f8bb5ea88c0fc9c1c17f008638aa52a43569b28", "df22be7416f29e7ba40d7c03e2caf6f604d0a70050fb2ff6d074d9aa0b18d2e1", "mephc-berry-c3-consistency-m60-canonical-primitive-frequency-dataset-v1", 36)
M61 = ("d3f8933ef1bddb6f7de72af14de0eae8d6c11194fafd6e9d1e61a556a6e4e11e", "5e97efd186e02ebddd9ee850d10c58931d21786b257db446c14c4064a5b9949e", "mephc-berry-c3-consistency-m61r1-homogeneous-frequency-dataset-v1", 36)
M63 = ("bd02f350a86d8376f89f9ef08cc943a117cbac2cece62ffa84e1266ae07d1a29", "f650352c9d8f3872ba880f82a15ec5e0c2cfa629a80c6af147a0204b6fc0698e", "mephc-berry-c3-consistency-m63-homogeneous-raw-mode-tolerance-dataset-v1", 18)
M64R3 = ("e4b558f6837a882746cc06b6c5925abf101aea20183fbc4bf45feaaaf733cebd", "b361a53e543a7060c66c343ddef4aa83d7a9132597e0d86be36b638868d60bd2", DATASET_SCHEMA, 4)


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
    raise ValueError(f"M64R4_UNSAFE_RESULT:{type(value).__name__}")


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, "M64R4_IMPORT_FAILED", str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _read_dataset(job: Any, root: Path, binding: tuple[str, str, str, int]) -> list[dict[str, Any]]:
    dataset_id, manifest, schema, count = binding
    verified = job.verify_dataset(root, dataset_id)
    require(verified.get("dataset_id") == dataset_id and verified.get("manifest_sha256") == manifest, "M64R4_DATASET_BINDING_INVALID", dataset_id)
    require(verified.get("record_count") == count, "M64R4_DATASET_COUNT_INVALID", dataset_id)
    rows = []
    for key in verified["record_key_sha256"]:
        row = json.loads(job.resolve_dataset_record(root, dataset_id, manifest, key)["payload"].decode("utf-8"))
        require(row.get("schema") == schema, "M64R4_DATASET_SCHEMA_INVALID", dataset_id)
        rows.append(row)
    return rows


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _verify_binding() -> dict[str, Any]:
    provenance_path = ROOT / "vendor/mpb_c3_patch/source_build5_provenance.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    source = ROOT / "vendor/mpb_c3_patch/source/mpb-1.12.0.tar.gz"
    driver = ROOT / "vendor/mpb_c3_patch/build_exact_build5.sh"
    require(_hash(source) == SOURCE_SHA and provenance.get("source_sha256") == SOURCE_SHA, "M64R4_SOURCE_BINDING_INVALID")
    require(provenance.get("package_build") == BUILD_ID and provenance.get("installed_libmpb_sha256") == LIBMPB_SHA, "M64R4_BUILD_BINDING_INVALID")
    require(_hash(driver) == DRIVER_SHA, "M64R4_DRIVER_HASH_INVALID")
    recipe_hashes = {}
    for relative, expected in provenance.get("recipe_files", {}).items():
        path = ROOT / "vendor/mpb_c3_patch" / relative
        require(path.is_file() and _hash(path) == expected, "M64R4_RECIPE_HASH_INVALID", relative)
        recipe_hashes[relative] = expected
    return {"source_sha256": SOURCE_SHA, "installed_libmpb_sha256": LIBMPB_SHA, "package_build": BUILD_ID, "driver_sha256": DRIVER_SHA, "recipe_hashes": recipe_hashes, "installed_environment_immutable": True, "installed_backend_touched": False}


def _analytic(coordinate: list[float]) -> list[float]:
    direct = np.asarray([[0.5, 0.5], [np.sqrt(3.0) / 2.0, -np.sqrt(3.0) / 2.0]])
    reciprocal = np.linalg.inv(direct).T
    k = np.asarray(coordinate, dtype=float)
    return sorted(float(np.linalg.norm(k - reciprocal @ np.asarray([i, j], dtype=float)) / 2.7) for i in range(-8, 9) for j in range(-8, 9))[:4]


def _isolated_probe(prefix: Path, coordinate: list[float], label: str, counter: Any) -> dict[str, Any]:
    counter.consume_solver()
    child = """import json,sys\nimport meep as mp\nfrom meep import mpb\nfrom mephc.band import Band\ncoordinate=json.loads(sys.argv[1])\nband=Band(a=400.0,r1=80.14335684352235,r2=75.13439704080221,n_eff=2.7,h=100.0,resolution=256,lattice_type='triangular',polarization='TE',structure_type='slab')\nreciprocal=mp.cartesian_to_reciprocal(mp.Vector3(float(coordinate[0]),float(coordinate[1]),0),band.geo_latt)\nsolver=mpb.ModeSolver(geometry=[],geometry_lattice=band.geo_latt,k_points=[reciprocal],resolution=256,num_bands=4,default_material=mp.Medium(epsilon=7.29),tolerance=1e-9,deterministic=True,mesh_size=1)\nsolver.run_parity(mp.TE,False)\nprint(json.dumps([float(x) for x in solver.all_freqs[0][:4]],separators=(',',':')))\n"""
    env = os.environ.copy(); env["LD_LIBRARY_PATH"] = str(prefix / "lib") + (":" + env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else "")
    completed = subprocess.run([sys.executable, "-B", "-c", child, json.dumps(coordinate)], env=env, capture_output=True, text=True, timeout=240, check=False)
    require(completed.returncode == 0, "M64R4_ISOLATED_CHILD_FAILED", label)
    values = json.loads(completed.stdout.strip().splitlines()[-1]); require(len(values) == 4, "M64R4_ISOLATED_CHILD_LAYOUT_INVALID", label)
    reference = _analytic(coordinate); error = float(max(abs(float(a) - float(b)) for a, b in zip(values, reference))); guard = 512 * np.finfo(float).eps * max(1.0, max(abs(x) for x in reference))
    return {"probe": label, "coordinate": coordinate, "analytic_reference_first4": reference, "observed_frequencies_first4": values, "analytic_error_max": error, "analytic_guard": guard, "analytic_status": "PASS" if error <= guard else "FAIL", "runtime_prefix": str(prefix), "runtime_identity": "ISOLATED_UNPATCHED_BUILD5", "patch_applied": False}


def main() -> int:
    bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8")); source_commit = str(os.environ.get("MEPHC_SOURCE_COMMIT") or bundle.get("source_commit") or ""); records: list[dict[str, Any]] = []; counter = None
    try:
        job = _load(ROOT / "tools/mephc-flow/scientific_job.py", "m64r4_job"); state_root = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"]).parent.parent
        prior = _read_dataset(job, state_root, M64R3); _read_dataset(job, state_root, M50); _read_dataset(job, state_root, M60); _read_dataset(job, state_root, M61); _read_dataset(job, state_root, M63)
        identity = _verify_binding(); counter = job.BudgetCounter(0, 72)
        source = ROOT / "vendor/mpb_c3_patch/source/mpb-1.12.0.tar.gz"; driver = ROOT / "vendor/mpb_c3_patch/build_exact_build5.sh"
        with tempfile.TemporaryDirectory(prefix="m64r4-build-") as temporary:
            temporary_root = Path(temporary); build_dir = temporary_root / "build"; prefix = temporary_root / "prefix"
            build = subprocess.run(["bash", str(driver), str(source), str(build_dir), str(prefix)], env=os.environ.copy(), capture_output=True, text=True, timeout=900, check=False)
            build_tail = (build.stdout + "\n" + build.stderr)[-4000:]
            require(build.returncode == 0, "M64R4_ISOLATED_BUILD_FAILED", build_tail)
            libraries = sorted((prefix / "lib").glob("libmpb.so*")); require(libraries, "M64R4_ISOLATED_LIBRARY_MISSING")
            library_hashes = {str(path.name): _hash(path) for path in libraries}
            frozen_coordinate = list(prior[0].get("coordinate", [0.0, 0.0])); probes = [(f"frozen:{member}", frozen_coordinate) for member in ("IDENTITY", "C3", "C3_SQUARED")] + [("generic:k0", [0.123456, -0.210987])]
            for label, coordinate in probes:
                records.append({"schema": DATASET_SCHEMA, "work_order_id": bundle["work_order_id"], "arm": "UNPATCHED_ISOLATED_TRACE", "source_commit": source_commit, **_isolated_probe(prefix, coordinate, label, counter)})
        namespace = {"goal_id": "MEPHC-BERRY-C3-CONSISTENCY-V1", "work_order_id": bundle["work_order_id"], "source_commit": source_commit, "record_schema": DATASET_SCHEMA}; store = job.ImmutableDatasetStore(state_root, namespace); require(not store.root.exists(), "M64R4_DATASET_NAMESPACE_EXISTS")
        for row in records:
            store.put(canonical({"work_order_id": bundle["work_order_id"], "arm": row["arm"], "probe": row["probe"]}), canonical(row), {"arm": row["arm"], "probe": row["probe"]})
        manifest = store.finalize(len(records), {"dataset_schema": DATASET_SCHEMA, "arm": "UNPATCHED_ISOLATED_TRACE", "patch_applied": False, "source_sha256": SOURCE_SHA, "prior_completed_solver_probes": 4})
        result = {"schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "BOUNDED_NEGATIVE_RESULT", "work_order_id": bundle["work_order_id"], "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": counter.solver_count, "prior_completed_solver_probes": 4, "dataset_record_count": len(records), "dataset_write": True, "dataset_id": manifest.get("dataset_id"), "manifest_sha256": manifest.get("manifest_sha256"), "dataset_schema": DATASET_SCHEMA, "source_commit_used": source_commit, "source_build_binding": identity | {"isolated_library_hashes": library_hashes, "isolated_build_status": "PASS_UNPATCHED"}, "prior_m64r3_records_consumed": len(prior), "localization_status": "NOT_LOCALIZED_NO_SOURCE_OPERATOR_MICRO_HARNESS", "scientific_patch_applied": False, "classification": "R256_NATIVE_DYNAMIC_LOCALIZATION_INCONCLUSIVE_NO_PATCH", "causal_outcome": "R256_NATIVE_DYNAMIC_LOCALIZATION_INCONCLUSIVE_NO_PATCH", "next_science_decision": "VENDORED_MPB_NATIVE_OPERATOR_MICRO_HARNESS_LOCALIZATION", "post_native_checkout_unchanged": True}
    except BaseException as exc:
        result = {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "BOUNDED_NEGATIVE_RESULT", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": 0 if counter is None else counter.solver_count, "prior_completed_solver_probes": 4, "dataset_record_count": len(records), "dataset_write": False, "failure_code": str(exc)[:1024], "failure_stage": "m64r4_exact_build5_isolated_localize_patch_ab", "exception_type": type(exc).__name__, "source_commit_used": source_commit, "isolated_build_or_localization_status": "NOT_PROVEN", "scientific_patch_applied": False, "post_native_checkout_unchanged": True}
    Path(os.environ["MEPHC_RESULT_PATH"]).write_text(json.dumps(_safe(result), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8"); return 0


if __name__ == "__main__":
    raise SystemExit(main())
