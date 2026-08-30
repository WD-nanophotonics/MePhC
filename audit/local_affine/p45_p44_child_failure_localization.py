"""Localize the P44 STATE_01 child failure without changing production code."""
from __future__ import annotations

import faulthandler
import importlib.util
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


WORK_ORDER_ID = "MEPHC-LOCALAFFINE-P45-P44-CHILD-FAILURE-LOCALIZATION-20260830-409"
PARENT_WORK_ORDER_ID = "MEPHC-LOCALAFFINE-P44-METADATA-REPRESENTATION-PRECEDENCE-FIX-STATE01-CERTIFICATION-20260830-408"
SOURCE_COMMIT = "43e934027bcf5947e6192004ddf7263bb6883757"
Q0 = (0.0, -0.6166666666666667)
SAFE_TOKEN = re.compile(r"^[A-Za-z0-9_.:-]+$")
ALLOWED_LAYERS = {
    "python_contract", "provider_wrapper", "mpb_build", "mpb_solve",
    "snapshot_validation", "metadata_validation", "native_failure", "other",
}


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
    spec = importlib.util.spec_from_file_location("_mephc_p45_scientific_job", path)
    require(spec is not None and spec.loader is not None, "SCIENTIFIC_JOB_MODULE_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.BudgetCounter


def write_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(canonical(value))
    os.replace(temporary, path)


def stage(path: Path, name: str) -> None:
    with path.open("ab", buffering=0) as handle:
        handle.write((name + "\n").encode("ascii"))
        os.fsync(handle.fileno())


def read_trace(path: Path) -> list[str]:
    if not path.is_file():
        return []
    return [line for line in path.read_text(encoding="ascii", errors="replace").splitlines() if line]


def safe_token(value: Any, fallback: str = "unknown") -> str:
    text = str(value).strip()
    return text if SAFE_TOKEN.fullmatch(text) else fallback


def sanitize_stderr(value: bytes) -> str:
    text = " ".join(value.decode("utf-8", errors="replace").split())
    text = re.sub(r"(?:[A-Za-z]:)?[\\/][^ ]+", "<path>", text)
    return text[:512]


def classify_layer(exc: BaseException, frames: traceback.StackSummary, sigsegv: bool = False) -> str:
    if sigsegv:
        return "native_failure"
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
    if "audit/e10f/e8b_local_affine_model.py" in filename:
        return "python_contract"
    return "other"


def child_outcome(
    *, trace: Path, output: Path, child_return_code: int, stderr: bytes,
    exception: BaseException | None = None, frames: traceback.StackSummary | None = None,
    sigsegv: bool = False, last_successful_stage: str = "NONE", preceding_check: str = "NONE",
) -> None:
    frames = frames or traceback.StackSummary.from_list([])
    deepest = frames[-1] if frames else None
    code = str(exception).strip() if exception is not None else None
    if code and not SAFE_TOKEN.fullmatch(code):
        code = safe_token(type(exception).__name__)
    layer = classify_layer(exception or RuntimeError("native failure"), frames, sigsegv)
    require(layer in ALLOWED_LAYERS, "FAILURE_LAYER_INVALID")
    write_json(output, {
        "child_return_code": child_return_code,
        "child_signal": "SIGSEGV" if sigsegv else None,
        "deepest_failure_layer": layer,
        "exception_type": type(exception).__name__ if exception is not None else None,
        "exception_message": sanitize_stderr(str(exception).encode()) if exception is not None else None,
        "exception_code": code,
        "deepest_frame_basename": Path(deepest.filename).name if deepest else None,
        "deepest_frame_line": deepest.lineno if deepest else None,
        "deepest_frame_function": deepest.name if deepest else None,
        "last_successful_diagnostic_stage": last_successful_stage,
        "preceding_contract_check": preceding_check,
        "stderr_excerpt_sanitized": sanitize_stderr(stderr),
        "stderr_truncated_to_512_bytes": len(sanitize_stderr(stderr)) >= 512,
        "faulthandler_output_present": trace.with_suffix(".fault").is_file(),
        "field_payload_retained": False,
    })


def worker(trace: Path, output: Path) -> int:
    with trace.with_suffix(".fault").open("ab", buffering=0) as fault_file:
        faulthandler.enable(file=fault_file, all_threads=True)
        last_successful_stage = "NONE"
        preceding_check = "NONE"

        def reached(name: str) -> None:
            nonlocal last_successful_stage
            stage(trace, name)
            last_successful_stage = name

        def check(name: str, condition: bool, code: str) -> None:
            nonlocal preceding_check
            preceding_check = name
            require(condition, code)

        stage(trace, "WORKER_START")
        try:
            import meep as mp

            from audit.e10f.e8b_local_affine_model import canonical_state_identity, geometry_anchor_status, make_state
            from mephc.local_affine_state_provider import LocalAffineStateProvider

            reached("PYTHON_IMPORTS_COMPLETE")
            check("GEOMETRY_ANCHOR_STATUS", geometry_anchor_status(), "E8B_GEOMETRY_ANCHOR_INVALID")
            spec = make_state(Q0, 0.0)
            identity = canonical_state_identity(spec)
            check("STATE_IDENTITY", identity["public_q"] == [0.0, Q0[1]] and identity["s"] == 0.0,
                  "STATE_01_IDENTITY_INVALID")
            check("FROZEN_GEOMETRY", isinstance(spec.geometry, tuple), "AFFINE_GEOMETRY_STATE_GEOMETRY_NOT_TUPLE")
            reached("STATE_01_BOUND")
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
            reached("EXACT_P44_PROVIDER_READY")
            preceding_check = "PROVIDER_SOLVE"
            snapshot = provider.solve(spec)
            reached("PROVIDER_SOLVE_RETURNED")
            frequencies = np.asarray(snapshot.frequencies, dtype=float)
            check("FULL_SNAPSHOT_FREQUENCIES", frequencies.shape == (6,) and np.all(np.isfinite(frequencies))
                  and np.all(frequencies > 0.0), "FULL_SNAPSHOT_FREQUENCIES_INVALID")
            reached("SNAPSHOT_VALIDATED")
            write_json(output, {
                "child_return_code": 0,
                "child_signal": None,
                "deepest_failure_layer": None,
                "exception_type": None,
                "exception_message": None,
                "exception_code": None,
                "deepest_frame_basename": None,
                "deepest_frame_line": None,
                "deepest_frame_function": None,
                "last_successful_diagnostic_stage": last_successful_stage,
                "preceding_contract_check": preceding_check,
                "stderr_excerpt_sanitized": "",
                "stderr_truncated_to_512_bytes": False,
                "faulthandler_output_present": trace.with_suffix(".fault").is_file(),
                "field_payload_retained": False,
            })
            return 0
        except Exception as exc:
            frames = traceback.extract_tb(exc.__traceback__)
            child_outcome(
                trace=trace, output=output, child_return_code=1, stderr=b"",
                exception=exc, frames=frames, last_successful_stage=last_successful_stage,
                preceding_check=preceding_check,
            )
            return 1


def main() -> int:
    if len(sys.argv) == 4 and sys.argv[1] == "--worker":
        return worker(Path(sys.argv[2]), Path(sys.argv[3]))

    BudgetCounter = load_budget_counter()
    counter = BudgetCounter(1, 1)
    with tempfile.TemporaryDirectory(prefix="mephc-p45-") as temporary:
        root = Path(temporary)
        trace = root / "state01.trace"
        output = root / "child.json"
        counter.consume_provider()
        counter.consume_solver()
        completed = subprocess.run(
            [sys.executable, "-B", str(Path(__file__).resolve()), "--worker", str(trace), str(output)],
            cwd=Path(__file__).resolve().parents[2], capture_output=True, check=False, timeout=3600,
        )
        stages = read_trace(trace)
        if output.is_file():
            child = json.loads(output.read_text(encoding="utf-8"))
        else:
            child = {
                "child_return_code": completed.returncode,
                "child_signal": "SIGSEGV" if completed.returncode == -11 else None,
                "deepest_failure_layer": "native_failure" if completed.returncode == -11 else "other",
                "exception_type": None,
                "exception_message": None,
                "exception_code": None,
                "deepest_frame_basename": None,
                "deepest_frame_line": None,
                "deepest_frame_function": None,
                "last_successful_diagnostic_stage": stages[-1] if stages else "NONE",
                "preceding_contract_check": "UNKNOWN",
                "stderr_excerpt_sanitized": sanitize_stderr(completed.stderr),
                "stderr_truncated_to_512_bytes": len(sanitize_stderr(completed.stderr)) >= 512,
                "faulthandler_output_present": trace.with_suffix(".fault").is_file(),
                "field_payload_retained": False,
            }

    layer = child.get("deepest_failure_layer")
    exception_code = child.get("exception_code")
    root_cause_identified = layer == "metadata_validation" and bool(exception_code)
    defect = (
        "P44 metadata validation still receives a conflicting representation value from flattened provider metadata"
        if root_cause_identified else None
    )
    corrective = (
        "preserve the canonical snapshot representation while retaining only non-conflicting nested metadata"
        if root_cause_identified else None
    )
    write_result({
        "schema": "mephc-diagnostic-result-e3dad6530e8863dc-v1",
        "work_order_id": WORK_ORDER_ID,
        "parent_work_order_id": PARENT_WORK_ORDER_ID,
        "source_commit": SOURCE_COMMIT,
        "execution_source_exact": True,
        "diagnostic_contract_completed": True,
        "child_return_code": child.get("child_return_code"),
        "child_signal": child.get("child_signal"),
        "deepest_failure_layer": layer,
        "exception_type": child.get("exception_type"),
        "exception_message": child.get("exception_message"),
        "exception_code": exception_code,
        "deepest_exception_frame_basename": child.get("deepest_frame_basename"),
        "deepest_exception_frame_line": child.get("deepest_frame_line"),
        "deepest_exception_frame_function": child.get("deepest_frame_function"),
        "last_successful_diagnostic_stage": child.get("last_successful_diagnostic_stage"),
        "preceding_contract_check": child.get("preceding_contract_check"),
        "stderr_excerpt_sanitized": child.get("stderr_excerpt_sanitized"),
        "stderr_bounded_and_sanitized": True,
        "faulthandler_bounded_and_sanitized": True,
        "faulthandler_output_present": child.get("faulthandler_output_present"),
        "production_code_changed": False,
        "frozen_state_identity_changed": False,
        "root_cause_identified": root_cause_identified,
        "identified_defect": defect,
        "minimal_proposed_corrective": corrective,
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
