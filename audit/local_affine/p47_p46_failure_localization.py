"""Localize the P46 STATE_01 failure with one unchanged production attempt."""
from __future__ import annotations

import faulthandler
import importlib.util
import inspect
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import traceback
from typing import Any

import numpy as np


WORK_ORDER_ID = "MEPHC-LOCALAFFINE-P47-P46-FAILURE-LOCALIZATION-20260830-411"
SOURCE_COMMIT = "02abcc78e0fe7d4ea67a4b03f969f1e0031c1c96"
ORIGINAL_P44_SOURCE_COMMIT = "43e934027bcf5947e6192004ddf7263bb6883757"
Q0 = (0.0, -0.6166666666666667)
SAFE_TOKEN = re.compile(r"^[A-Za-z0-9_.:-]+$")
PRODUCTION_PATHS = (
    "mephc/local_affine_state_provider.py",
    "mephc/mpb_spectral_provider.py",
    "audit/e10f/e8b_local_affine_model.py",
)
STAGES = (
    "STATE_CONSTRUCTION",
    "PROVIDER_CONSTRUCTION",
    "MPB_BUILD_ENTRY",
    "MPB_SOLVE_RETURN",
    "FREQUENCY_VALIDATION",
    "VECTOR_VALIDATION",
    "GRAM_VALIDATION",
    "SPATIAL_SHAPE_VALIDATION",
    "METADATA_EXTRACTION",
    "REPRESENTATION_VALIDATION",
    "RECIPROCAL_METADATA_VALIDATION",
    "REFERENCE_CELL_CONTRACT_VALIDATION",
    "FINAL_COMPLETION",
)


def canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def require(condition: bool, code: str) -> None:
    if not condition:
        raise RuntimeError(code)


def load_budget_counter() -> Any:
    root = Path(__file__).resolve().parents[2]
    path = root / "tools" / "mephc-flow" / "scientific_job.py"
    spec = importlib.util.spec_from_file_location("_mephc_p47_scientific_job", path)
    require(spec is not None and spec.loader is not None, "SCIENTIFIC_JOB_MODULE_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.BudgetCounter


def write_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(canonical(value))
    os.replace(temporary, path)


def git_blob(commit: str, path: str) -> str:
    root = Path(__file__).resolve().parents[2]
    completed = subprocess.run(
        ["git", "rev-parse", f"{commit}:{path}"], cwd=root,
        capture_output=True, text=True, check=True,
    )
    return completed.stdout.strip()


def verify_production_blobs() -> bool:
    for path in PRODUCTION_PATHS:
        require(git_blob(SOURCE_COMMIT, path) == git_blob(ORIGINAL_P44_SOURCE_COMMIT, path),
                f"PRODUCTION_BLOB_CHANGED:{path}")
    return True


def stage(path: Path, name: str) -> None:
    with path.open("ab", buffering=0) as handle:
        handle.write((name + "\n").encode("ascii"))
        os.fsync(handle.fileno())


def read_lines(path: Path) -> list[str]:
    if not path.is_file():
        return []
    return [line for line in path.read_text(encoding="ascii", errors="replace").splitlines() if line]


def sanitize_text(value: bytes | str) -> str:
    raw = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value
    text = " ".join(raw.split())
    text = re.sub(r"(?:[A-Za-z]:)?[\\/][^ ]+", "<path>", text)
    return text[:512]


def classify_layer(exc: BaseException | None, frames: traceback.StackSummary, sigsegv: bool) -> str | None:
    if sigsegv:
        return "native_failure"
    if exc is None:
        return None
    deepest = frames[-1] if frames else None
    filename = deepest.filename.replace("\\", "/") if deepest else ""
    function = deepest.name if deepest else ""
    code = str(exc)
    if "local_affine_state_provider.py" in filename and function == "_validate_snapshot":
        return "metadata_validation" if "METADATA" in code or "REPRESENTATION" in code else "snapshot_validation"
    if "mpb_spectral_provider.py" in filename and function == "_build_solver":
        return "mpb_build"
    if "mpb_spectral_provider.py" in filename and function == "solve":
        return "mpb_solve"
    if "local_affine_state_provider.py" in filename and function == "solve":
        return "provider_wrapper"
    if "e8b_local_affine_model.py" in filename:
        return "python_contract"
    return "other"


def worker(trace: Path, output: Path) -> int:
    with trace.with_suffix(".fault").open("ab", buffering=0) as fault_file:
        faulthandler.enable(file=fault_file, all_threads=True)
        last_successful = "NONE"
        pending = STAGES[0]

        def reached(name: str) -> None:
            nonlocal last_successful, pending
            stage(trace, name)
            last_successful = name
            index = STAGES.index(name)
            pending = STAGES[index + 1] if index + 1 < len(STAGES) else "NONE"

        try:
            import meep as mp

            from audit.e10f.e8b_local_affine_model import canonical_state_identity, geometry_anchor_status, make_state
            from mephc.local_affine_state_provider import LocalAffineStateProvider, _metadata, local_affine_reference_cell_contract
            from mephc.mpb_spectral_provider import MPBLiveSpectralProvider

            reached("STATE_CONSTRUCTION")
            require(geometry_anchor_status(), "E8B_GEOMETRY_ANCHOR_INVALID")
            spec = make_state(Q0, 0.0)
            identity_before = canonical_state_identity(spec)
            require(identity_before["public_q"] == [0.0, Q0[1]] and identity_before["s"] == 0.0,
                    "STATE_01_IDENTITY_INVALID")
            require(isinstance(spec.geometry, tuple), "AFFINE_GEOMETRY_STATE_GEOMETRY_NOT_TUPLE")
            reached("PROVIDER_CONSTRUCTION")
            provider_source = inspect.getsource(MPBLiveSpectralProvider._build_solver)
            require("geometry=list(self.geometry)" in provider_source,
                    "MPB_BOUNDARY_LIST_CONVERSION_MISSING")
            provider = LocalAffineStateProvider(
                resolution=64,
                num_bands=6,
                eigensolver_tolerance=1e-7,
                mesh_size=3,
                deterministic=True,
                polarization=mp.TM,
                polarization_identity="TM",
                default_material=mp.air,
            )
            reached("MPB_BUILD_ENTRY")
            snapshot = provider.solve(spec)
            reached("MPB_SOLVE_RETURN")
            frequencies = np.asarray(snapshot.frequencies, dtype=float)
            require(frequencies.shape == (6,) and np.all(np.isfinite(frequencies)) and np.all(frequencies > 0.0),
                    "FULL_SNAPSHOT_FREQUENCIES_INVALID")
            reached("FREQUENCY_VALIDATION")
            require(len(snapshot.normalized_vectors) == 6, "FULL_SNAPSHOT_VECTOR_COUNT_INVALID")
            for vector in snapshot.normalized_vectors:
                values = np.asarray(vector, dtype=np.complex128)
                require(np.all(np.isfinite(values)) and np.isclose(float(np.linalg.norm(values)), 1.0,
                        rtol=0.0, atol=1e-10), "FULL_SNAPSHOT_VECTOR_INVALID")
            reached("VECTOR_VALIDATION")
            gram = np.asarray(snapshot.gram_matrix, dtype=np.complex128)
            require(gram.shape == (6, 6) and np.all(np.isfinite(gram)), "FULL_SNAPSHOT_GRAM_INVALID")
            reached("GRAM_VALIDATION")
            require(tuple(snapshot.spatial_shape) == (64, 64) and snapshot.component_count == 3,
                    "FULL_SNAPSHOT_SHAPE_INVALID")
            reached("SPATIAL_SHAPE_VALIDATION")
            metadata = _metadata(snapshot)
            reached("METADATA_EXTRACTION")
            require(metadata.get("representation") == "mpb_periodic_h_l2_v1",
                    "CANONICAL_REPRESENTATION_PRECEDENCE_INVALID")
            require(metadata.get("resolution") == 64, "SOLVER_SETTINGS_RESOLUTION_MISSING")
            reached("REPRESENTATION_VALIDATION")
            reciprocal = snapshot.provenance.get("mpb_k_point")
            require(isinstance(reciprocal, (list, tuple)) and len(reciprocal) == 3
                    and np.allclose(np.asarray(reciprocal[:2], dtype=float),
                                    np.asarray(identity_before["derived_kappa"]), rtol=0.0, atol=1e-9)
                    and float(reciprocal[2]) == 0.0, "CANONICAL_RECIPROCAL_METADATA_INVALID")
            reached("RECIPROCAL_METADATA_VALIDATION")
            expected_contract = local_affine_reference_cell_contract(
                spec, spatial_shape=tuple(snapshot.spatial_shape), identity=identity_before,
                lattice_size=(float(spec.geometry_lattice.size.x), float(spec.geometry_lattice.size.y)),
            )
            require(snapshot.provenance.get("local_affine_reference_cell_contract") == expected_contract,
                    "REFERENCE_CELL_METADATA_INVALID")
            reached("REFERENCE_CELL_CONTRACT_VALIDATION")
            require(snapshot.provenance.get("local_affine_solver_polarization_identity") == "TM",
                    "POLARIZATION_IDENTITY_INVALID")
            require(snapshot.provenance.get("phase_callback") in (None, "None")
                    or "phase_callback" not in snapshot.provenance,
                    "PHASE_CALLBACK_PRODUCTION_PATH_INVALID")
            reached("FINAL_COMPLETION")
            write_json(output, {
                "child_return_code": 0, "child_signal": None, "deepest_failure_layer": None,
                "exception_type": None, "exception_message": None, "exception_code": None,
                "last_successful_stage": last_successful, "next_pending_stage": pending,
                "ordered_stage_markers": ",".join(read_lines(trace)),
                "stderr_excerpt_sanitized": "", "field_payload_retained": False,
            })
            return 0
        except Exception as exc:
            frames = traceback.extract_tb(exc.__traceback__)
            code = str(exc).strip() or type(exc).__name__
            if not SAFE_TOKEN.fullmatch(code):
                code = type(exc).__name__
            layer = classify_layer(exc, frames, False)
            write_json(output, {
                "child_return_code": 1, "child_signal": None, "deepest_failure_layer": layer,
                "exception_type": type(exc).__name__, "exception_message": sanitize_text(str(exc)),
                "exception_code": code, "last_successful_stage": last_successful,
                "next_pending_stage": pending, "ordered_stage_markers": ",".join(read_lines(trace)),
                "stderr_excerpt_sanitized": "", "field_payload_retained": False,
            })
            stage(trace, "CHILD_OUTCOME_RECORDED")
            return 1


def main() -> int:
    if len(sys.argv) == 4 and sys.argv[1] == "--worker":
        return worker(Path(sys.argv[2]), Path(sys.argv[3]))
    production_blobs_equivalent = verify_production_blobs()
    BudgetCounter = load_budget_counter()
    counter = BudgetCounter(1, 1)
    with tempfile.TemporaryDirectory(prefix="mephc-p47-") as temporary:
        root = Path(temporary)
        trace = root / "state01.trace"
        output = root / "child.json"
        counter.consume_provider()
        counter.consume_solver()
        completed = subprocess.run(
            [sys.executable, "-B", str(Path(__file__).resolve()), "--worker", str(trace), str(output)],
            cwd=Path(__file__).resolve().parents[2], capture_output=True, check=False, timeout=3600,
        )
        stages = read_lines(trace)
        child = json.loads(output.read_text(encoding="utf-8")) if output.is_file() else {
            "child_return_code": completed.returncode,
            "child_signal": "SIGSEGV" if completed.returncode == -11 else None,
            "deepest_failure_layer": "native_failure" if completed.returncode == -11 else "other",
            "exception_type": None, "exception_message": None, "exception_code": None,
            "last_successful_stage": stages[-1] if stages else "NONE",
            "next_pending_stage": "UNKNOWN", "ordered_stage_markers": ",".join(stages),
            "stderr_excerpt_sanitized": sanitize_text(completed.stderr),
            "field_payload_retained": False,
        }
        fault = trace.with_suffix(".fault")
        fault_text = fault.read_text(encoding="utf-8", errors="replace") if fault.is_file() else ""
        fault_lines = [line for line in fault_text.splitlines() if line]
    completed_ok = child.get("child_return_code") == 0
    write_result({
        "schema": "mephc-local-affine-p47-p46-failure-localization-v1",
        "work_order_id": WORK_ORDER_ID,
        "parent_work_order_id": "MEPHC-LOCALAFFINE-P46-STATE01-P44-EXACT-RECERTIFICATION-20260830-410",
        "source_commit": SOURCE_COMMIT,
        "execution_source_commit": os.environ.get("MEPHC_SOURCE_COMMIT", ""),
        "original_p44_source_commit": ORIGINAL_P44_SOURCE_COMMIT,
        "production_blob_equivalence_to_p44": production_blobs_equivalent,
        "production_code_changed": False,
        "exact_single_state01_attempt": True,
        "prior_p46_failure_classification": "UNREPRODUCED" if completed_ok else "REPRODUCED_AT_DIRECTLY_EVIDENCED_LAYER",
        "root_cause_directly_identified": False,
        "child_return_code": child.get("child_return_code"),
        "child_signal": child.get("child_signal"),
        "deepest_failure_layer": child.get("deepest_failure_layer"),
        "exception_type": child.get("exception_type"),
        "exception_message": child.get("exception_message"),
        "exception_code": child.get("exception_code"),
        "last_successful_stage": child.get("last_successful_stage"),
        "next_pending_stage": child.get("next_pending_stage"),
        "ordered_stage_markers": child.get("ordered_stage_markers"),
        "stderr_excerpt_sanitized": child.get("stderr_excerpt_sanitized"),
        "stderr_bounded_and_sanitized": True,
        "faulthandler_bounded_and_sanitized": True,
        "faulthandler_output_present": bool(fault_lines),
        "faulthandler_line_count": len(fault_lines),
        "native_invocation_count": 1,
        "provider_execution_count": 1,
        "solver_execution_count": 1,
        "diagnostic_child_process_count": 1,
        "formal_scientific_dataset_records": 0,
        "field_payload_retained": False,
        "retry_count": 0,
        "cache_reuse_count": 0,
        "top_level_scalar_result_only": True,
        "sanitized_result_safe": True,
        "result_written_to_mephc_result_path": True,
        "status": "PASS",
    })
    return 0


def write_result(value: dict[str, Any]) -> None:
    write_json(Path(os.environ["MEPHC_RESULT_PATH"]), value)


if __name__ == "__main__":
    raise SystemExit(main())
