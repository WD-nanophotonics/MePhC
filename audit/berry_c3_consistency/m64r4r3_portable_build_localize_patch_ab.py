"""M64R4R3: portable exact-Build5 dependency resolution and trace boundary."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
RESULT_SCHEMA = "mephc-berry-c3-consistency-m64r4r3-portable-build-localize-patch-ab-v1"
DATASET_SCHEMA = "mephc-berry-c3-consistency-m64r4r3-patched-frequency-ab-dataset-v1"
M64R3_SCHEMA = "mephc-berry-c3-consistency-m64r3-patched-frequency-ab-dataset-v1"
SOURCE_SHA = "8d2b206254b217f66a53c1ad20cc0c369b93b0e71ee671d68e333a583eaaeda4"
LIBMPB_SHA = "884071022f8c5230909e269c63b17cef120b51d2a4ee22b862c6a7005d209dbc"
DRIVER_SHA = "b1c343e8568f361ba633ccba5d9ef36cbee74ffc2e46773c2d32a845bb187c83"
BUILD_ID = "mpi_mpich_hef3cbd5_5"
MEMBERS = ("IDENTITY", "C3", "C3_SQUARED")
M50 = ("9b560f99fa264905ee99cb68d4ccdf757446ffb7b3a0af0391d5760a9740861d", "c009e68d08bd13084eb0320d95ecda5ceab57bdafa8fddef30ecc5b1177563ed", "mephc-berry-c3-consistency-m50-r256-mesh1-c3-causal-control-dataset-v1", 36)
M60 = ("4657c25e5443938a5bd3ffaa3f8bb5ea88c0fc9c1c17f008638aa52a43569b28", "df22be7416f29e7ba40d7c03e2caf6f604d0a70050fb2ff6d074d9aa0b18d2e1", "mephc-berry-c3-consistency-m60-canonical-primitive-frequency-dataset-v1", 36)
M61 = ("d3f8933ef1bddb6f7de72af14de0eae8d6c11194fafd6e9d1e61a556a6e4e11e", "5e97efd186e02ebddd9ee850d10c58931d21786b257db446c14c4064a5b9949e", "mephc-berry-c3-consistency-m61r1-homogeneous-frequency-dataset-v1", 36)
M63 = ("bd02f350a86d8376f89f9ef08cc943a117cbac2cece62ffa84e1266ae07d1a29", "f650352c9d8f3872ba880f82a15ec5e0c2cfa629a80c6af147a0204b6fc0698e", "mephc-berry-c3-consistency-m63-homogeneous-raw-mode-tolerance-dataset-v1", 18)
M64R3 = ("e4b558f6837a882746cc06b6c5925abf101aea20183fbc4bf45feaaaf733cebd", "b361a53e543a7060c66c343ddef4aa83d7a9132597e0d86be36b638868d60bd2", M64R3_SCHEMA, 4)


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
    if isinstance(value, np.generic): return _safe(value.item())
    if isinstance(value, np.ndarray): return _safe(value.tolist())
    if isinstance(value, Mapping): return {str(k): _safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)): return [_safe(v) for v in value]
    raise ValueError(f"M64R4R3_UNSAFE_RESULT:{type(value).__name__}")


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path); require(spec is not None and spec.loader is not None, "M64R4R3_IMPORT_FAILED", str(path)); module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""): digest.update(block)
    return digest.hexdigest()


def resolve_gnuconfig() -> dict[str, Any]:
    candidates = []
    if os.environ.get("MPB_GNUCONFIG_ROOT"): candidates.append(("EXPLICIT_ROOT", Path(os.environ["MPB_GNUCONFIG_ROOT"])))
    if os.environ.get("MPB_BUILD_PREFIX"): candidates.append(("BUILD_PREFIX", Path(os.environ["MPB_BUILD_PREFIX"]) / "share" / "gnuconfig"))
    if os.environ.get("MPB_DEP_PREFIX"): candidates.append(("DEP_PREFIX", Path(os.environ["MPB_DEP_PREFIX"]) / "share" / "gnuconfig"))
    for category, root in candidates:
        sub, guess = root / "config.sub", root / "config.guess"
        if sub.is_file() and guess.is_file():
            return {"category": category, "root": str(root.resolve()), "config_sub_sha256": _hash(sub), "config_guess_sha256": _hash(guess)}
    raise ValueError("R256_EXACT_BUILD5_GNUCONFIG_DEPENDENCY_UNAVAILABLE")


def verify_build5_binding() -> dict[str, Any]:
    provenance = json.loads((ROOT / "vendor/mpb_c3_patch/source_build5_provenance.json").read_text(encoding="utf-8")); source = ROOT / "vendor/mpb_c3_patch/source/mpb-1.12.0.tar.gz"; driver = ROOT / "vendor/mpb_c3_patch/build_exact_build5.sh"; require(_hash(source) == SOURCE_SHA and provenance.get("source_sha256") == SOURCE_SHA, "M64R4R3_SOURCE_BINDING_INVALID"); require(provenance.get("isolated_build_driver_sha256") == DRIVER_SHA and _hash(driver) == DRIVER_SHA, "M64R4R3_DRIVER_BINDING_INVALID"); require(provenance.get("package_build") == BUILD_ID and provenance.get("installed_libmpb_sha256") == LIBMPB_SHA, "M64R4R3_BUILD_BINDING_INVALID"); recipes = {}
    for relative, expected in provenance.get("recipe_files", {}).items():
        path = ROOT / "vendor/mpb_c3_patch" / relative; require(path.is_file() and _hash(path) == expected, "M64R4R3_RECIPE_HASH_INVALID", relative); recipes[relative] = expected
    return {"source_sha256": SOURCE_SHA, "driver_sha256": DRIVER_SHA, "recipe_hashes": recipes, "package_build": BUILD_ID, "installed_libmpb_sha256": LIBMPB_SHA, "gnuconfig_resolution": provenance.get("gnuconfig_resolution"), "installed_backend_touched": False}


def _read_dataset(job: Any, root: Path, binding: tuple[str, str, str, int]) -> list[dict[str, Any]]:
    dataset_id, manifest, schema, count = binding; verified = job.verify_dataset(root, dataset_id); require(verified.get("dataset_id") == dataset_id and verified.get("manifest_sha256") == manifest and verified.get("record_count") == count, "M64R4R3_DATASET_BINDING_INVALID", dataset_id); rows = []
    for key in verified["record_key_sha256"]:
        row = json.loads(job.resolve_dataset_record(root, dataset_id, manifest, key)["payload"].decode("utf-8")); require(row.get("schema") == schema, "M64R4R3_DATASET_SCHEMA_INVALID", dataset_id); rows.append(row)
    return rows


def _index_prior(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result = {str(row["probe"]): row for row in rows}; require(len(result) == 4, "M64R4R3_PRIOR_PROBE_KEYS_INVALID"); return result


def _failure_set(rows: Mapping[tuple[int, int, str], Mapping[str, Any]]) -> list[dict[str, Any]]:
    failures = []
    for vertex in range(4):
        for source, target in zip(MEMBERS, MEMBERS[1:] + MEMBERS[:1]):
            for band in range(4):
                left = np.asarray([float(rows[(vertex, repeat, source)]["frequencies_bands_1_to_4"][band]) for repeat in range(3)]); right = np.asarray([float(rows[(vertex, repeat, target)]["frequencies_bands_1_to_4"][band]) for repeat in range(3)]); lm, rm = float(np.median(left)), float(np.median(right)); lu, ru = float(np.max(np.abs(left - lm))), float(np.max(np.abs(right - rm)))
                if abs(lm - rm) > lu + ru: failures.append({"vertex": vertex, "band": band + 1, "source_member": source, "target_member": target, "residual": abs(lm - rm), "combined_repeat_uncertainty": lu + ru})
    return failures


def _child_probe(prefix: Path, coordinate: list[float], label: str, counter: Any, frozen: bool) -> dict[str, Any]:
    counter.consume_solver(); child = """import hashlib,json,sys\nfrom pathlib import Path\nimport meep as mp\nfrom meep import mpb\nfrom mephc.band import Band\nc=json.loads(sys.argv[1]); band=Band(a=400.0,r1=80.14335684352235,r2=75.13439704080221,n_eff=2.7,h=100.0,resolution=256,lattice_type='triangular',polarization='TE',structure_type='slab'); k=mp.cartesian_to_reciprocal(mp.Vector3(float(c[0]),float(c[1]),0),band.geo_latt); s=mpb.ModeSolver(geometry=[],geometry_lattice=band.geo_latt,k_points=[k],resolution=256,num_bands=4,default_material=mp.Medium(epsilon=7.29),tolerance=1e-9,deterministic=True,mesh_size=1); s.run_parity(mp.TE,False); raw=s.get_eigenvectors(1,4) if sys.argv[2]=='1' else None; paths=[]\nfor line in Path('/proc/self/maps').read_text().splitlines():\n p=line.split(maxsplit=5)[-1] if len(line.split(maxsplit=5))>=6 else '';\n if 'libmpb.so' in p and Path(p).is_file(): paths.append(str(Path(p).resolve()))\npaths=sorted(set(paths)); print(json.dumps({'frequencies':[float(x) for x in s.all_freqs[0][:4]],'mapped_paths':paths,'raw_sha256':hashlib.sha256(raw.tobytes()).hexdigest() if raw is not None else None,'raw_shape':list(raw.shape) if raw is not None else None},separators=(',',':')))\n"""; env = os.environ.copy(); env["LD_LIBRARY_PATH"] = str(prefix / "lib") + (":" + env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else ""); completed = subprocess.run([sys.executable, "-B", "-c", child, json.dumps(coordinate), "1" if frozen else "0"], env=env, capture_output=True, text=True, timeout=240, check=False); require(completed.returncode == 0, "M64R4R3_ISOLATED_CHILD_FAILED", label); payload = json.loads(completed.stdout.strip().splitlines()[-1]); paths = {str(Path(path).resolve()) for path in payload["mapped_paths"] if Path(path).is_file()}; require(len(paths) == 1 and str(next(iter(paths))).startswith(str(prefix.resolve()) + os.sep), "M64R4R3_LOADED_LIB_PATH_INVALID", label); mapped = next(iter(paths)); return {"probe": label, "coordinate": coordinate, "observed_frequencies_first4": payload["frequencies"], "raw_sha256": payload["raw_sha256"], "raw_shape": payload["raw_shape"], "mapped_library_path": mapped, "mapped_library_sha256": _hash(Path(mapped)), "runtime_identity": "ISOLATED_TRACE", "patch_applied": False}


def main() -> int:
    bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8")); source_commit = str(os.environ.get("MEPHC_SOURCE_COMMIT") or bundle.get("source_commit") or ""); records: list[dict[str, Any]] = []; counter = None
    try:
        job = _load(ROOT / "tools/mephc-flow/scientific_job.py", "m64r4r3_job"); state_root = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"]).parent.parent; prior = _index_prior(_read_dataset(job, state_root, M64R3)); _read_dataset(job, state_root, M50); _read_dataset(job, state_root, M60); m61_rows = _read_dataset(job, state_root, M61); _read_dataset(job, state_root, M63); m61 = {(int(row["vertex_index"]), int(row["repeat_index"]), str(row["c3_member_identity"])): row for row in m61_rows}; failures = _failure_set(m61); require(failures, "M64R4R3_M63_FAILURE_NOT_REPRODUCED"); worst = sorted(failures, key=lambda item: (-(item["residual"] - item["combined_repeat_uncertainty"]), -item["residual"], item["vertex"], item["band"], item["source_member"], item["target_member"]))[0]; coordinates = {member: list(m61[(worst["vertex"], 0, member)]["coordinate"]) for member in MEMBERS}; require(len({tuple(value) for value in coordinates.values()}) == 3, "M64R4R3_MEMBER_COORDINATES_NOT_DISTINCT"); require(all(prior[f"unpatched:frozen:v{worst['vertex']}:{member}"]["coordinate"] == coordinates[member] for member in MEMBERS), "M64R4R3_PRIOR_COORDINATE_MISMATCH"); binding = verify_build5_binding(); gnuconfig = resolve_gnuconfig(); discovery = _load(ROOT / "audit/berry_c3_consistency/m64r3_dynamic_source_discovery_localize_patch_ab.py", "m64r3_discovery").discover_source(); counter = job.BudgetCounter(0, 80); source = ROOT / "vendor/mpb_c3_patch/source/mpb-1.12.0.tar.gz"; driver = ROOT / "vendor/mpb_c3_patch/build_exact_build5.sh"
        with tempfile.TemporaryDirectory(prefix="m64r4r3-build-") as temporary:
            root = Path(temporary); build_dir = root / "build"; prefix = root / "prefix"; env = os.environ.copy(); env["MPB_GNUCONFIG_ROOT"] = gnuconfig["root"]; completed = subprocess.run(["bash", str(driver), str(source), str(build_dir), str(prefix)], env=env, capture_output=True, text=True, timeout=900, check=False); require(completed.returncode == 0, "M64R4R3_ISOLATED_BUILD_FAILED", (completed.stdout + "\n" + completed.stderr)[-4000:]); libraries = sorted({path.resolve() for path in (prefix / "lib").glob("libmpb.so*") if path.is_file()}); require(libraries, "M64R4R3_ISOLATED_LIBRARY_MISSING"); built_hash = _hash(libraries[-1]); probes = [(f"unpatched:frozen:v{worst['vertex']}:{member}", coordinates[member], True) for member in MEMBERS] + [("unpatched:generic:k0", [0.123456, -0.210987], False)]
            for label, coordinate, frozen in probes:
                row = _child_probe(prefix, coordinate, label, counter, frozen); row["built_trace_lib_sha256"] = built_hash; row["installed_reference_libmpb_sha256"] = LIBMPB_SHA; row["installed_baseline_frequencies_first4"] = prior[label]["observed_frequencies_first4"]; row["baseline_difference"] = float(max(abs(float(a) - float(b)) for a, b in zip(row["observed_frequencies_first4"], row["installed_baseline_frequencies_first4"])))
                records.append({"schema": DATASET_SCHEMA, "work_order_id": bundle["work_order_id"], "arm": "UNPATCHED_TRACE", "source_commit": source_commit, **row});
        namespace = {"goal_id": "MEPHC-BERRY-C3-CONSISTENCY-V1", "work_order_id": bundle["work_order_id"], "source_commit": source_commit, "record_schema": DATASET_SCHEMA}; store = job.ImmutableDatasetStore(state_root, namespace); require(not store.root.exists(), "M64R4R3_DATASET_NAMESPACE_EXISTS")
        for row in records: store.put(canonical({"work_order_id": bundle["work_order_id"], "arm": row["arm"], "probe": row["probe"]}), canonical(row), {"arm": row["arm"], "probe": row["probe"]})
        manifest = store.finalize(len(records), {"dataset_schema": DATASET_SCHEMA, "arm": "UNPATCHED_TRACE", "gnuconfig": gnuconfig, "source_sha256": SOURCE_SHA}); result = {"schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "BOUNDED_NEGATIVE_RESULT", "work_order_id": bundle["work_order_id"], "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": counter.solver_count, "dataset_record_count": len(records), "dataset_write": True, "dataset_id": manifest.get("dataset_id"), "manifest_sha256": manifest.get("manifest_sha256"), "dataset_schema": DATASET_SCHEMA, "source_commit_used": source_commit, "source_build_binding": binding, "gnuconfig": gnuconfig, "source_discovery": discovery, "m64r3_probe_reference_count": len(prior), "frozen_worst_triplet": worst, "member_coordinates": coordinates, "baseline_probes": records, "localization_status": "INCONCLUSIVE_OPERATOR_HARNESS_NOT_AVAILABLE", "classification": "R256_NATIVE_DYNAMIC_LOCALIZATION_INCONCLUSIVE_NO_PATCH", "causal_outcome": "R256_NATIVE_DYNAMIC_LOCALIZATION_INCONCLUSIVE_NO_PATCH", "next_science_decision": "VENDORED_MPB_NATIVE_OPERATOR_MICRO_HARNESS_LOCALIZATION", "scientific_patch_applied": False, "post_native_checkout_unchanged": True}
    except BaseException as exc:
        result = {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "BOUNDED_NEGATIVE_RESULT", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": 0 if counter is None else counter.solver_count, "dataset_record_count": len(records), "dataset_write": bool(records), "failure_code": str(exc)[:1024], "failure_stage": "m64r4r3_portable_build_localize_patch_ab", "exception_type": type(exc).__name__, "source_commit_used": source_commit, "scientific_patch_applied": False, "post_native_checkout_unchanged": True}
    Path(os.environ["MEPHC_RESULT_PATH"]).write_text(json.dumps(_safe(result), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8"); return 0


if __name__ == "__main__":
    raise SystemExit(main())
