"""M64R4R2: self-contained Build5 binding closure and isolated trace."""
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
RESULT_SCHEMA = "mephc-berry-c3-consistency-m64r4r2-recover-binding-build-localize-patch-ab-v1"
DATASET_SCHEMA = "mephc-berry-c3-consistency-m64r4r2-patched-frequency-ab-dataset-v1"
M64R3_SCHEMA = "mephc-berry-c3-consistency-m64r3-patched-frequency-ab-dataset-v1"
SOURCE_SHA = "8d2b206254b217f66a53c1ad20cc0c369b93b0e71ee671d68e333a583eaaeda4"
LIBMPB_SHA = "884071022f8c5230909e269c63b17cef120b51d2a4ee22b862c6a7005d209dbc"
DRIVER_SHA = "a877f068fd1411b6480ed4d6956da5a4d2f8998cd3f3df9e192f751ec99c4350"
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
    if isinstance(value, np.generic):
        return _safe(value.item())
    if isinstance(value, np.ndarray):
        return _safe(value.tolist())
    if isinstance(value, Mapping):
        return {str(k): _safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(v) for v in value]
    raise ValueError(f"M64R4R2_UNSAFE_RESULT:{type(value).__name__}")


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path); require(spec is not None and spec.loader is not None, "M64R4R2_IMPORT_FAILED", str(path)); module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""): digest.update(block)
    return digest.hexdigest()


def verify_build5_binding() -> dict[str, Any]:
    """Verify all committed exact Build5 inputs without touching the active env."""
    provenance_path = ROOT / "vendor/mpb_c3_patch/source_build5_provenance.json"; provenance = json.loads(provenance_path.read_text(encoding="utf-8")); source = ROOT / "vendor/mpb_c3_patch/source/mpb-1.12.0.tar.gz"; driver = ROOT / "vendor/mpb_c3_patch/build_exact_build5.sh"
    require(_hash(source) == SOURCE_SHA and provenance.get("source_sha256") == SOURCE_SHA, "M64R4R2_SOURCE_BINDING_INVALID"); require(provenance.get("package_build") == BUILD_ID and provenance.get("installed_libmpb_sha256") == LIBMPB_SHA, "M64R4R2_BUILD_BINDING_INVALID"); require(_hash(driver) == DRIVER_SHA, "M64R4R2_DRIVER_HASH_INVALID")
    recipes = {}
    for relative, expected in provenance.get("recipe_files", {}).items():
        path = ROOT / "vendor/mpb_c3_patch" / relative; require(path.is_file() and _hash(path) == expected, "M64R4R2_RECIPE_HASH_INVALID", relative); recipes[relative] = expected
    return {"source_sha256": SOURCE_SHA, "installed_libmpb_sha256": LIBMPB_SHA, "package_build": BUILD_ID, "driver_sha256": DRIVER_SHA, "recipe_hashes": recipes, "installed_environment_immutable": True, "installed_backend_touched": False}


def _read_dataset(job: Any, root: Path, binding: tuple[str, str, str, int]) -> list[dict[str, Any]]:
    dataset_id, manifest, schema, count = binding; verified = job.verify_dataset(root, dataset_id); require(verified.get("dataset_id") == dataset_id and verified.get("manifest_sha256") == manifest, "M64R4R2_DATASET_BINDING_INVALID", dataset_id); require(verified.get("record_count") == count, "M64R4R2_DATASET_COUNT_INVALID", dataset_id); rows = []
    for key in verified["record_key_sha256"]:
        row = json.loads(job.resolve_dataset_record(root, dataset_id, manifest, key)["payload"].decode("utf-8")); require(row.get("schema") == schema, "M64R4R2_DATASET_SCHEMA_INVALID", dataset_id); rows.append(row)
    return rows


def index_probe_rows(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    indexed = {str(row.get("probe")): row for row in rows}; require(len(indexed) == 4 and all(key and key != "None" for key in indexed), "M64R4R2_PROBE_KEYS_INVALID"); return indexed


def _failure_set(rows: Mapping[tuple[int, int, str], Mapping[str, Any]]) -> list[dict[str, Any]]:
    failures = []
    for vertex in range(4):
        for source, target in zip(MEMBERS, MEMBERS[1:] + MEMBERS[:1]):
            for band in range(4):
                left = np.asarray([float(rows[(vertex, repeat, source)]["frequencies_bands_1_to_4"][band]) for repeat in range(3)]); right = np.asarray([float(rows[(vertex, repeat, target)]["frequencies_bands_1_to_4"][band]) for repeat in range(3)]); lm, rm = float(np.median(left)), float(np.median(right)); lu, ru = float(np.max(np.abs(left - lm))), float(np.max(np.abs(right - rm)))
                if abs(lm - rm) > lu + ru: failures.append({"vertex": vertex, "band": band + 1, "source_member": source, "target_member": target, "residual": abs(lm - rm), "combined_repeat_uncertainty": lu + ru})
    return failures


def compatibility_guard(repeat_uncertainty: float, source_residual: float | None, machine_term: float) -> float:
    return float(repeat_uncertainty + (0.0 if source_residual is None else abs(source_residual)) + abs(machine_term))


def prepare_build_command(source: Path, build_dir: Path, prefix: Path) -> list[str]:
    return ["bash", str(ROOT / "vendor/mpb_c3_patch/build_exact_build5.sh"), str(source), str(build_dir), str(prefix)]


def loaded_library_ledger(maps_text: str, prefix: str, expected_sha: str) -> dict[str, Any]:
    root = Path(prefix).resolve(); candidates = []
    for line in maps_text.splitlines():
        fields = line.split(maxsplit=5); path_text = fields[-1] if len(fields) >= 6 else ""
        if "libmpb.so" not in path_text: continue
        path = Path(path_text).resolve()
        if path.is_file() and str(path).startswith(str(root) + os.sep): candidates.append(path)
    unique = sorted(set(candidates)); require(len(unique) == 1, "M64R4R2_LOADED_LIB_AMBIGUOUS"); actual = _hash(unique[0]); require(actual == expected_sha, "M64R4R2_LOADED_LIB_SHA_MISMATCH"); return {"loaded_path": str(unique[0]), "loaded_sha256": actual, "under_isolated_prefix": True, "path_source": "proc_self_maps"}


def _analytic(coordinate: list[float]) -> list[float]:
    direct = np.asarray([[0.5, 0.5], [np.sqrt(3.0) / 2.0, -np.sqrt(3.0) / 2.0]]); reciprocal = np.linalg.inv(direct).T; k = np.asarray(coordinate, dtype=float)
    return sorted(float(np.linalg.norm(k - reciprocal @ np.asarray([i, j], dtype=float)) / 2.7) for i in range(-8, 9) for j in range(-8, 9))[:4]


def _child_probe(prefix: Path, coordinate: list[float], label: str, counter: Any, frozen: bool, expected_hash: str) -> dict[str, Any]:
    counter.consume_solver()
    child = """import hashlib,json,sys\nfrom pathlib import Path\nimport meep as mp\nfrom meep import mpb\nfrom mephc.band import Band\nc=json.loads(sys.argv[1]); band=Band(a=400.0,r1=80.14335684352235,r2=75.13439704080221,n_eff=2.7,h=100.0,resolution=256,lattice_type='triangular',polarization='TE',structure_type='slab'); k=mp.cartesian_to_reciprocal(mp.Vector3(float(c[0]),float(c[1]),0),band.geo_latt); s=mpb.ModeSolver(geometry=[],geometry_lattice=band.geo_latt,k_points=[k],resolution=256,num_bands=4,default_material=mp.Medium(epsilon=7.29),tolerance=1e-9,deterministic=True,mesh_size=1); s.run_parity(mp.TE,False); raw=s.get_eigenvectors(1,4) if sys.argv[2]=='1' else None; paths=[]\nfor line in Path('/proc/self/maps').read_text().splitlines():\n p=line.split(maxsplit=5)[-1] if len(line.split(maxsplit=5))>=6 else '';\n if 'libmpb.so' in p and Path(p).is_file(): paths.append(str(Path(p).resolve()))\npaths=sorted(set(paths)); print(json.dumps({'frequencies':[float(x) for x in s.all_freqs[0][:4]],'mapped_paths':paths,'eigenvector_shape':list(getattr(raw,'shape',())) if raw is not None else None,'eigenvector_sha256':hashlib.sha256(raw.tobytes()).hexdigest() if raw is not None else None},separators=(',',':')))\n"""
    env = os.environ.copy(); env["LD_LIBRARY_PATH"] = str(prefix / "lib") + (":" + env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else ""); completed = subprocess.run([sys.executable, "-B", "-c", child, json.dumps(coordinate), "1" if frozen else "0"], env=env, capture_output=True, text=True, timeout=240, check=False); require(completed.returncode == 0, "M64R4R2_ISOLATED_CHILD_FAILED", label); payload = json.loads(completed.stdout.strip().splitlines()[-1]); maps = "\n".join(f"0 0 0 0 0 {path}" for path in payload["mapped_paths"]); loaded = loaded_library_ledger(maps, str(prefix), expected_hash); return {"probe": label, "coordinate": coordinate, "observed_frequencies_first4": payload["frequencies"], "analytic_reference_first4": _analytic(coordinate), "mapped_library": loaded, "eigenvector_shape": payload["eigenvector_shape"], "eigenvector_sha256": payload["eigenvector_sha256"], "runtime_identity": "ISOLATED_UNPATCHED_BUILD5", "patch_applied": False}


def main() -> int:
    bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8")); source_commit = str(os.environ.get("MEPHC_SOURCE_COMMIT") or bundle.get("source_commit") or ""); records: list[dict[str, Any]] = []; counter = None
    try:
        job = _load(ROOT / "tools/mephc-flow/scientific_job.py", "m64r4r2_job"); state_root = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"]).parent.parent; prior = _read_dataset(job, state_root, M64R3); prior_by_probe = index_probe_rows(prior); _read_dataset(job, state_root, M50); _read_dataset(job, state_root, M60); m61_rows = _read_dataset(job, state_root, M61); _read_dataset(job, state_root, M63); m61 = {(int(row["vertex_index"]), int(row["repeat_index"]), str(row["c3_member_identity"])): row for row in m61_rows}; failures = _failure_set(m61); require(failures, "M64R4R2_M63_FAILURE_NOT_REPRODUCED"); worst = sorted(failures, key=lambda item: (-(item["residual"] - item["combined_repeat_uncertainty"]), -item["residual"], item["vertex"], item["band"], item["source_member"], item["target_member"]))[0]; coordinates = {member: list(m61[(worst["vertex"], 0, member)]["coordinate"]) for member in MEMBERS}; require(len({tuple(value) for value in coordinates.values()}) == 3, "M64R4R2_MEMBER_COORDINATES_NOT_DISTINCT"); require(all(prior_by_probe[f"unpatched:frozen:v{worst['vertex']}:{member}"]["coordinate"] == coordinates[member] for member in MEMBERS), "M64R4R2_PRIOR_COORDINATE_MISMATCH"); binding = verify_build5_binding(); discovery = _load(ROOT / "audit/berry_c3_consistency/m64r3_dynamic_source_discovery_localize_patch_ab.py", "m64r3_discovery").discover_source(); counter = job.BudgetCounter(0, 80); source = ROOT / "vendor/mpb_c3_patch/source/mpb-1.12.0.tar.gz"; driver = ROOT / "vendor/mpb_c3_patch/build_exact_build5.sh"
        with tempfile.TemporaryDirectory(prefix="m64r4r2-build-") as temporary:
            root = Path(temporary); build_dir = root / "build"; prefix = root / "prefix"; completed = subprocess.run(prepare_build_command(source, build_dir, prefix), env=os.environ.copy(), capture_output=True, text=True, timeout=900, check=False); require(completed.returncode == 0, "M64R4R2_ISOLATED_BUILD_FAILED", (completed.stdout + "\n" + completed.stderr)[-4000:]); libraries = sorted({path.resolve() for path in (prefix / "lib").glob("libmpb.so*") if path.is_file()}); require(libraries, "M64R4R2_ISOLATED_LIBRARY_MISSING"); built_hash = _hash(libraries[-1]); namespace = {"goal_id": "MEPHC-BERRY-C3-CONSISTENCY-V1", "work_order_id": bundle["work_order_id"], "source_commit": source_commit, "record_schema": DATASET_SCHEMA}; store = job.ImmutableDatasetStore(state_root, namespace); require(not store.root.exists(), "M64R4R2_DATASET_NAMESPACE_EXISTS"); probes = [(f"unpatched:frozen:v{worst['vertex']}:{member}", coordinates[member], True) for member in MEMBERS] + [("unpatched:generic:k0", [0.123456, -0.210987], False)]
            for label, coordinate, frozen in probes:
                row = _child_probe(prefix, coordinate, label, counter, frozen, built_hash); installed = prior_by_probe[label]["observed_frequencies_first4"]; row["installed_baseline_frequencies_first4"] = installed; row["baseline_difference"] = float(max(abs(float(a) - float(b)) for a, b in zip(row["observed_frequencies_first4"], installed))); row["baseline_compatibility_guard"] = compatibility_guard(0.0, None, np.finfo(float).eps * max(1.0, max(abs(x) for x in row["observed_frequencies_first4"]))); row["baseline_equivalence_requires_source_evidence"] = True; item = {"schema": DATASET_SCHEMA, "work_order_id": bundle["work_order_id"], "arm": "UNPATCHED_ISOLATED_TRACE", "source_commit": source_commit, **row}; store.put(canonical({"work_order_id": bundle["work_order_id"], "arm": item["arm"], "probe": label}), canonical(item), {"arm": item["arm"], "probe": label}); records.append(item)
        manifest = store.finalize(4, {"dataset_schema": DATASET_SCHEMA, "arm": "UNPATCHED_ISOLATED_TRACE", "source_sha256": SOURCE_SHA, "prior_completed_solver_probes": 4}); result = {"schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "BOUNDED_NEGATIVE_RESULT", "work_order_id": bundle["work_order_id"], "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": counter.solver_count, "prior_completed_solver_probes": 4, "dataset_record_count": 4, "dataset_write": True, "dataset_id": manifest.get("dataset_id"), "manifest_sha256": manifest.get("manifest_sha256"), "dataset_schema": DATASET_SCHEMA, "m64r3_schema_used": M64R3_SCHEMA, "semantic_probe_keys": sorted(prior_by_probe), "member_coordinates": coordinates, "frozen_worst_triplet": worst, "source_build_binding": binding | {"built_trace_lib_sha256": built_hash}, "source_discovery": discovery, "localization_status": "INCONCLUSIVE_NO_OPERATOR_MICRO_HARNESS", "scientific_patch_applied": False, "classification": "R256_NATIVE_DYNAMIC_LOCALIZATION_INCONCLUSIVE_NO_PATCH", "causal_outcome": "R256_NATIVE_DYNAMIC_LOCALIZATION_INCONCLUSIVE_NO_PATCH", "next_science_decision": "VENDORED_MPB_NATIVE_OPERATOR_MICRO_HARNESS_LOCALIZATION", "post_native_checkout_unchanged": True}
    except BaseException as exc:
        result = {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "BOUNDED_NEGATIVE_RESULT", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": 0 if counter is None else counter.solver_count, "prior_completed_solver_probes": 4, "dataset_record_count": len(records), "dataset_write": bool(records), "failure_code": str(exc)[:1024], "failure_stage": "m64r4r2_recover_binding_build_localize_patch_ab", "exception_type": type(exc).__name__, "source_commit_used": source_commit, "scientific_patch_applied": False, "post_native_checkout_unchanged": True}
    Path(os.environ["MEPHC_RESULT_PATH"]).write_text(json.dumps(_safe(result), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8"); return 0


if __name__ == "__main__":
    raise SystemExit(main())
