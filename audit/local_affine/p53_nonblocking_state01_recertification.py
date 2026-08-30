"""Transport the P52 STATE_01 diagnostic without masking its scientific result."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any

from audit.local_affine.p52_state01_full_p44_recertification import worker as p52_worker


WORK_ORDER_ID = "MEPHC-LOCALAFFINE-P53-NONBLOCKING-STATE01-RECERTIFICATION-20260830-417"
PARENT_WORK_ORDER_ID = "MEPHC-LOCALAFFINE-P52-STATE01-FULL-P44-RECERTIFICATION-20260830-416"
ORIGINAL_P44_SOURCE_COMMIT = "43e934027bcf5947e6192004ddf7263bb6883757"
P52_SOURCE_COMMIT = "877df2323f9e10e7610c8a69cb6a7d7de1a845d4"
SAFE_TOKEN = re.compile(r"^[A-Za-z0-9_.:-]+$")


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def require(condition: bool, code: str) -> None:
    if not condition:
        raise RuntimeError(code)


def write_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(canonical(value))
    os.replace(temporary, path)


def sanitize_text(value: bytes | str) -> str:
    raw = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)
    return re.sub(r"(?:[A-Za-z]:)?[\\/][^ ]+", "<path>", " ".join(raw.split()))[:512]


def safe_code(value: Any) -> str:
    text = str(value).strip()
    return text if text and SAFE_TOKEN.fullmatch(text) else type(value).__name__


def load_budget_counter() -> Any:
    root = Path(__file__).resolve().parents[2]
    path = root / "tools" / "mephc-flow" / "scientific_job.py"
    spec = importlib.util.spec_from_file_location("_mephc_p53_scientific_job", path)
    require(spec is not None and spec.loader is not None, "SCIENTIFIC_JOB_MODULE_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.BudgetCounter


def git_blob(commit: str, path: str) -> str:
    root = Path(__file__).resolve().parents[2]
    return subprocess.run(
        ["git", "rev-parse", f"{commit}:{path}"], cwd=root,
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def verify_production_blobs() -> bool:
    for path in (
        "mephc/local_affine_state_provider.py",
        "mephc/mpb_spectral_provider.py",
        "audit/e10f/e8b_local_affine_model.py",
    ):
        require(
            git_blob(P52_SOURCE_COMMIT, path) == git_blob(ORIGINAL_P44_SOURCE_COMMIT, path),
            f"PRODUCTION_BLOB_CHANGED:{path}",
        )
    return True


def fallback() -> dict[str, Any]:
    return {
        "state01_provider_solve_returned": False,
        "failure_side": "child_process",
        "exact_failing_stage": "STATE_CONSTRUCTION",
        "exception_type": None,
        "exception_code": "CHILD_RESULT_MISSING",
        "exception_message": None,
        "last_successful_stage": "NONE",
        "next_pending_stage": "STATE_CONSTRUCTION",
        "ordered_stage_markers": "",
        "field_payload_retained": False,
        "status": "FAIL",
    }


def write_result(value: dict[str, Any]) -> None:
    write_json(Path(os.environ["MEPHC_RESULT_PATH"]), value)


def main() -> int:
    # The worker is the unchanged P52 acceptance matrix. This branch exists
    # only for the bounded child process and never performs a second solve.
    if len(sys.argv) == 4 and sys.argv[1] == "--worker":
        return p52_worker(Path(sys.argv[2]), Path(sys.argv[3]))

    child = fallback()
    completed: subprocess.CompletedProcess[bytes] | None = None
    parent_error: BaseException | None = None
    child_result_loaded = False
    production_blobs_equivalent = False
    try:
        production_blobs_equivalent = verify_production_blobs()
        BudgetCounter = load_budget_counter()
        counter = BudgetCounter(1, 1)
        with tempfile.TemporaryDirectory(prefix="mephc-p53-") as temporary:
            root = Path(temporary)
            trace = root / "state01.trace"
            output = root / "worker.json"
            counter.consume_provider()
            counter.consume_solver()
            completed = subprocess.run(
                [sys.executable, "-B", str(Path(__file__).resolve()), "--worker", str(trace), str(output)],
                cwd=Path(__file__).resolve().parents[2], capture_output=True, check=False, timeout=3600,
            )
            if output.is_file():
                try:
                    loaded = json.loads(output.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict):
                        child = loaded
                        child_result_loaded = True
                except Exception as exc:
                    parent_error = exc
    except Exception as exc:
        parent_error = exc

    structured_result_written = parent_error is None and completed is not None and child_result_loaded
    scientific_pass = structured_result_written and completed.returncode == 0 and child.get("status") == "PASS"
    if parent_error is not None:
        child.update({
            "failure_side": "parent_transport",
            "exact_failing_stage": "DIAGNOSTIC_TRANSPORT",
            "exception_type": type(parent_error).__name__,
            "exception_code": safe_code(parent_error),
            "exception_message": sanitize_text(str(parent_error)),
            "status": "FAIL",
        })

    result = {
        "schema": "mephc-local-affine-p53-nonblocking-state01-recertification-v1",
        "work_order_id": WORK_ORDER_ID,
        "parent_work_order_id": PARENT_WORK_ORDER_ID,
        "source_commit": os.environ.get("MEPHC_SOURCE_COMMIT", ""),
        "original_p44_source_commit": ORIGINAL_P44_SOURCE_COMMIT,
        "p52_source_commit": P52_SOURCE_COMMIT,
        "production_blob_equivalence_to_original_p44": production_blobs_equivalent,
        "production_code_changed": False,
        "diagnostic_contract_completed": structured_result_written,
        "scientific_acceptance_status": "PASS" if scientific_pass else "FAIL",
        "child_return_code": completed.returncode if completed is not None else None,
        "child_stderr_bounded_and_sanitized": True,
        "child_stderr_excerpt_sanitized": sanitize_text(completed.stderr if completed is not None else b""),
        "parent_exception_type": type(parent_error).__name__ if parent_error else None,
        "parent_exception_code": safe_code(parent_error) if parent_error else None,
        "parent_exception_message": sanitize_text(str(parent_error)) if parent_error else None,
        "native_invocation_count": 1 if completed is not None else 0,
        "provider_execution_count": 1 if completed is not None else 0,
        "solver_execution_count": 1 if completed is not None else 0,
        "diagnostic_child_process_count": 1 if completed is not None else 0,
        "formal_scientific_dataset_records": 0,
        "field_payload_retained": False,
        "retry_count": 0,
        "cache_reuse_count": 0,
        "top_level_scalar_result_only": True,
        "sanitized_result_safe": True,
        "result_written_to_mephc_result_path": True,
        **child,
        "diagnostic_contract_completed": structured_result_written,
        "scientific_acceptance_status": "PASS" if scientific_pass else "FAIL",
        "status": "PASS" if structured_result_written else "FAIL",
    }
    try:
        write_result(result)
    except Exception:
        return 1
    # A completed P53 diagnostic is transport-successful even when its one
    # scientific attempt produced a structured FAIL result.
    return 0 if structured_result_written else 1


if __name__ == "__main__":
    raise SystemExit(main())
