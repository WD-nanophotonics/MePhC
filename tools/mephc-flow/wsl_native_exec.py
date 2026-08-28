#!/home/icy/miniconda3/envs/mp/bin/python
"""Fixed WSL-side foreground process recorder used by mephc-flow."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path

RESULT_MARKER = b"MEPHC_NATIVE_RESULT_JSON="
MAX_RESULT_BYTES = 65536
TAIL_BYTES = MAX_RESULT_BYTES * 2 + len(RESULT_MARKER) + 4096
FORBIDDEN_SUMMARY_TOKENS = (
    "normalized_vectors", "raw H", "raw_h", "pickle", "/home/icy/",
    "C:\\Users\\", "username", "machine", "pid",
)


def atomic(path: Path, value: dict) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def stream_stats(path: Path) -> dict[str, int | str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
            size += len(block)
    return {"sha256": digest.hexdigest(), "size_bytes": size}


def _summary_is_safe(value: object) -> bool:
    if isinstance(value, dict):
        return all(
            isinstance(key, str)
            and not any(token in key.lower() for token in FORBIDDEN_SUMMARY_TOKENS)
            and _summary_is_safe(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return all(_summary_is_safe(item) for item in value)
    if isinstance(value, str):
        lowered = value.lower()
        return not any(token.lower() in lowered for token in FORBIDDEN_SUMMARY_TOKENS)
    return isinstance(value, (bool, int, float)) or value is None


def extract_result_summary(stdout_path: Path) -> dict:
    with stdout_path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        handle.seek(max(0, size - TAIL_BYTES), os.SEEK_SET)
        tail = handle.read(TAIL_BYTES)
    lines = [line.strip() for line in tail.splitlines() if line.strip().startswith(RESULT_MARKER)]
    if len(lines) != 1:
        raise ValueError("RESULT_SUMMARY_MARKER_COUNT_INVALID")
    payload = lines[0][len(RESULT_MARKER):]
    if len(payload) > MAX_RESULT_BYTES:
        raise ValueError("RESULT_SUMMARY_OVERSIZED")
    try:
        summary = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("RESULT_SUMMARY_MALFORMED") from exc
    if not isinstance(summary, dict) or not _summary_is_safe(summary):
        raise ValueError("RESULT_SUMMARY_UNSAFE")
    canonical = json.dumps(summary, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if canonical != payload:
        raise ValueError("RESULT_SUMMARY_NOT_CANONICAL")
    return summary


def finalize_child_result(record: dict, stdout_path: Path, stderr_path: Path, return_code: int) -> dict:
    stdout = stream_stats(stdout_path)
    stderr = stream_stats(stderr_path)
    result = dict(record)
    result.update({
        "stdout_sha256": stdout["sha256"],
        "stdout_size_bytes": stdout["size_bytes"],
        "stderr_sha256": stderr["sha256"],
        "stderr_size_bytes": stderr["size_bytes"],
        "return_code": return_code,
        "completed_at": time.time(),
    })
    if return_code != 0:
        result.update({"state": "failed", "result_error": "CHILD_RETURN_CODE_NONZERO"})
        return result
    try:
        summary = extract_result_summary(stdout_path)
    except ValueError as exc:
        result.update({"state": "failed", "result_error": str(exc)})
        result.pop("result_summary", None)
        return result
    result.update({"state": "succeeded", "result_summary": summary})
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True)
    parser.add_argument("--checkout", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("argv", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    argv = args.argv[1:] if args.argv and args.argv[0] == "--" else args.argv
    state_path = Path(args.state)
    value = json.loads(state_path.read_text(encoding="utf-8"))
    stdout_path = state_path.with_suffix(".stdout.log")
    stderr_path = state_path.with_suffix(".stderr.log")
    environment = os.environ.copy()
    environment["PATH"] = "/home/icy/miniconda3/envs/mp/bin:" + environment.get("PATH", "")
    environment["PYTHONPATH"] = args.checkout
    environment["MEPHC_SOURCE_COMMIT"] = Path(args.checkout).name
    with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
        process = subprocess.Popen(argv, cwd=args.project, env=environment, shell=False,
                                   stdout=stdout, stderr=stderr)
        stat = Path(f"/proc/{process.pid}/stat").read_text(encoding="ascii").split()
        value.update({"state": "running", "process_started": True, "pid": process.pid,
                      "linux_start_ticks": stat[21], "started_at": time.time()})
        atomic(state_path, value)
        return_code = process.wait()
    final = finalize_child_result(value, stdout_path, stderr_path, return_code)
    final.pop("pid", None)
    final.pop("linux_start_ticks", None)
    atomic(state_path, final)
    return 0 if final["state"] == "succeeded" else 2


if __name__ == "__main__":
    raise SystemExit(main())
