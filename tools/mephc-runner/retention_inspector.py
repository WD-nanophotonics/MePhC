#!/home/icy/miniconda3/envs/mp/bin/python
"""Hash-bound, path-redacted inspection of registered MePhC retention roots."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import time
from typing import Any, Iterable

import runtime_config as config

SHA64 = re.compile(r"^[0-9a-f]{64}$")
ID = re.compile(r"^[A-Z0-9][A-Z0-9_.-]{2,127}$")
MAX_FILE_BYTES = 256 * 1024 * 1024
MAX_JSON_BYTES = 64 * 1024 * 1024
MAX_FILES = 100_000
MAX_HASH_BYTES = 16 * 1024 * 1024 * 1024
SEARCH_SECONDS = 300
PAGE_LIMIT = 200
PAGE_MAX_BYTES = 65536
ARCHIVE_SUFFIXES = (".tar", ".tar.gz", ".tgz")
SENSITIVE_PARTS = {"outbox", "receipts", "certificates", "secrets", "browser", ".git"}
HOST_TEXT = re.compile(r"(?:/home/[A-Za-z0-9_.-]+|[A-Za-z]:\\Users\\[^\\/]+|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,})")


class RetentionError(RuntimeError):
    def __init__(self, code: str, detail: str = "") -> None:
        self.code, self.detail = code, detail
        super().__init__(f"{code}:{detail}")


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        handle.write("\n"); handle.flush(); os.fsync(handle.fileno())
    os.replace(temporary, path)
    os.chmod(path, 0o600)


def registered_roots(execution_root: Path) -> list[tuple[str, Path]]:
    home = Path("/home/icy")
    roots = [
        ("HIDDEN_ARCHIVE", home / ".local/share/mephc-archive"),
        ("DURABLE_RETENTION", config.STATE_ROOT / "retention"),
        ("CACHE_RETENTION", config.GIT_CACHE.parent / "retention"),
        ("CONTROL_AUDIT_ARCHIVE", execution_root / "audit/infrastructure/local_replica_archive"),
    ]
    legacy = home / "MePhC"
    for pattern in (".rp3-*", ".c3-c5-*"):
        if legacy.is_dir():
            roots.extend(("LEGACY_RETENTION", path) for path in sorted(legacy.glob(pattern)))
    return roots


def _safe_file(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return (path.is_file() and not path.is_symlink()
            and not any(part.lower() in SENSITIVE_PARTS for part in path.relative_to(root).parts))


def _digest_stream(handle, limit: int = MAX_FILE_BYTES) -> tuple[str, int]:
    digest, total = hashlib.sha256(), 0
    while True:
        chunk = handle.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise RetentionError("RETENTION_OBJECT_TOO_LARGE", str(total))
        digest.update(chunk)
    return digest.hexdigest(), total


def _phase(job_dir: Path, phase: str, deadline: float, **fields: Any) -> None:
    atomic_json(job_dir / "retention-progress.json", {
        "phase": phase, "phase_started_at": int(time.time()),
        "phase_heartbeat_unix": time.time(), "deadline_unix": deadline, **fields,
    })


def _opaque(expected: str, index: int) -> str:
    return "RET-" + hashlib.sha256(f"{expected}:{index}".encode()).hexdigest()[:24].upper()


def _regular_candidates(roots: list[tuple[str, Path]]) -> Iterable[tuple[str, Path]]:
    # Two bounded-memory passes guarantee index/manifest inspection precedes
    # ordinary file hashing without retaining a potentially large path list.
    for priority in (True, False):
        for root_id, root in roots:
            if not root.is_dir() or root.is_symlink():
                continue
            for path in root.rglob("*"):
                if not _safe_file(path, root):
                    continue
                indexed = any(marker in path.name.lower() for marker in ("sha256", "manifest", "index"))
                if indexed == priority:
                    yield root_id, path


def search_bindings(bindings: list[dict[str, str]], roots: list[tuple[str, Path]], job_dir: Path,
                    deadline: float | None = None) -> dict[str, Any]:
    deadline = time.time() + SEARCH_SECONDS if deadline is None else deadline
    expected = {item["expected_sha256"]: item["retention_id"] for item in bindings}
    matches: dict[str, list[dict[str, Any]]] = {digest: [] for digest in expected}
    scanned_files = scanned_bytes = archives = 0
    _phase(job_dir, "index_scan", deadline)
    for root_id, path in _regular_candidates(roots):
        if time.time() >= deadline or scanned_files >= MAX_FILES or scanned_bytes >= MAX_HASH_BYTES:
            return _search_result(bindings, matches, False, "SEARCH_INCOMPLETE", scanned_files, scanned_bytes, archives)
        scanned_files += 1
        try:
            size = path.stat().st_size
            lower = path.name.lower()
            is_archive = lower.endswith(ARCHIVE_SUFFIXES) or lower.endswith(".bundle")
            if size > MAX_FILE_BYTES and not is_archive:
                continue
            count = 0
            if size <= MAX_FILE_BYTES:
                with path.open("rb") as handle:
                    digest, count = _digest_stream(handle)
                scanned_bytes += count
                if digest in matches:
                    matches[digest].append({"kind": "file", "path": str(path), "root_id": root_id, "bytes": count})
        except (OSError, RetentionError):
            continue
        if lower.endswith(ARCHIVE_SUFFIXES):
            archives += 1
            _phase(job_dir, "archive_scan", deadline, scanned_files=scanned_files, archive_count=archives)
            try:
                with tarfile.open(path, "r:*") as archive:
                    for member in archive:
                        member_path = Path(member.name)
                        if time.time() >= deadline or scanned_bytes >= MAX_HASH_BYTES:
                            break
                        if (not member.isfile() or member.size > MAX_FILE_BYTES
                                or member_path.is_absolute() or ".." in member_path.parts
                                or any(part.lower() in SENSITIVE_PARTS for part in member_path.parts)):
                            continue
                        stream = archive.extractfile(member)
                        if stream is None:
                            continue
                        member_digest, member_bytes = _digest_stream(stream)
                        scanned_bytes += member_bytes
                        if member_digest in matches:
                            matches[member_digest].append({"kind": "tar", "path": str(path),
                                                           "member": member.name, "root_id": root_id,
                                                           "bytes": member_bytes})
            except (OSError, tarfile.TarError, RetentionError):
                pass
        elif lower.endswith(".bundle"):
            archives += 1
            _phase(job_dir, "archive_scan", deadline, scanned_files=scanned_files, archive_count=archives)
            cache = job_dir / "bundle-cache" / hashlib.sha256(str(path).encode()).hexdigest()[:16]
            try:
                clone = subprocess.run(["/usr/bin/git", "clone", "--mirror", "--quiet", str(path), str(cache)],
                                       text=True, capture_output=True, check=False, timeout=60)
                if clone.returncode:
                    continue
                listing = subprocess.run(["/usr/bin/git", "-C", str(cache), "rev-list", "--objects", "--all"],
                                         text=True, capture_output=True, check=False, timeout=60)
                if listing.returncode:
                    continue
                for line in listing.stdout.splitlines():
                    if time.time() >= deadline or scanned_bytes >= MAX_HASH_BYTES:
                        break
                    oid = line.split(" ", 1)[0]
                    kind = subprocess.run(["/usr/bin/git", "-C", str(cache), "cat-file", "-t", oid],
                                          text=True, capture_output=True, check=False, timeout=10)
                    if kind.stdout.strip() != "blob":
                        continue
                    blob = subprocess.run(["/usr/bin/git", "-C", str(cache), "cat-file", "blob", oid],
                                          capture_output=True, check=False, timeout=30)
                    if blob.returncode or len(blob.stdout) > MAX_FILE_BYTES:
                        continue
                    scanned_bytes += len(blob.stdout)
                    blob_digest = hashlib.sha256(blob.stdout).hexdigest()
                    if blob_digest in matches:
                        matches[blob_digest].append({"kind": "git", "path": str(path),
                                                     "cache": str(cache), "oid": oid,
                                                     "root_id": root_id, "bytes": len(blob.stdout)})
            except (OSError, subprocess.TimeoutExpired):
                pass
        if scanned_files % 100 == 0:
            _phase(job_dir, "candidate_verify", deadline, scanned_files=scanned_files, scanned_bytes=scanned_bytes)
    if time.time() >= deadline or scanned_bytes >= MAX_HASH_BYTES:
        return _search_result(bindings, matches, False, "SEARCH_INCOMPLETE", scanned_files, scanned_bytes, archives)
    return _search_result(bindings, matches, True, None, scanned_files, scanned_bytes, archives)


def _search_result(bindings: list[dict[str, str]], matches: dict[str, list[dict[str, Any]]],
                   exhaustive: bool, error_code: str | None, scanned_files: int,
                   scanned_bytes: int, archives: int) -> dict[str, Any]:
    artifacts, internal = [], {}
    for binding in bindings:
        digest = binding["expected_sha256"]
        locators = matches[digest]
        public = []
        for index, locator in enumerate(locators):
            opaque = _opaque(digest, index)
            internal[opaque] = locator
            public.append(opaque)
        artifacts.append({"retention_id": binding["retention_id"], "expected_sha256": digest,
                          "status": "FOUND_EXACT" if public else
                                    ("NOT_FOUND_EXHAUSTIVE" if exhaustive else "SEARCH_INCOMPLETE"),
                          "copy_count": len(public), "opaque_locators": public})
    return {"schema": "mephc-retention-search-result-v1", "exhaustive": exhaustive,
            "error_code": error_code, "artifacts": artifacts, "internal_locators": internal,
            "statistics": {"files_hashed": scanned_files, "bytes_hashed": scanned_bytes,
                           "archives_scanned": archives}}


def run_search(job_dir: Path, execution_root: Path) -> int:
    job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    query = job["retention_query"]
    deadline = time.time() + int(query.get("deadline_seconds", SEARCH_SECONDS))
    result = search_bindings(query["bindings"], registered_roots(execution_root), job_dir, deadline)
    atomic_json(job_dir / "retention-search-result.json", result)
    _phase(job_dir, "terminal", deadline, exhaustive=result["exhaustive"])
    return 0 if result["exhaustive"] else 4


def _load_locator(job_dir: Path, retention_id: str) -> tuple[dict[str, Any], dict[str, Any], str]:
    if not job_dir.is_dir():
        raise RetentionError("RETENTION_SEARCH_JOB_NOT_FOUND")
    try:
        job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RetentionError("RETENTION_SEARCH_JOB_INVALID") from exc
    if job.get("schema") != "mephc-runner-job-v3" or job.get("operation") != "retention_search":
        raise RetentionError("RETENTION_SEARCH_JOB_INVALID")
    try:
        result = json.loads((job_dir / "retention-search-result.json").read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RetentionError("RETENTION_SEARCH_NOT_READY") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise RetentionError("RETENTION_SEARCH_RESULT_INVALID") from exc
    binding = next((item for item in job["retention_query"]["bindings"] if item["retention_id"] == retention_id), None)
    artifact = next((item for item in result["artifacts"] if item["retention_id"] == retention_id), None)
    if binding is None or artifact is None:
        raise RetentionError("RETENTION_ID_NOT_IN_SEARCH")
    if artifact["status"] != "FOUND_EXACT" or not artifact["opaque_locators"]:
        raise RetentionError(artifact["status"])
    opaque = artifact["opaque_locators"][0]
    return binding, result["internal_locators"][opaque], opaque


def _locator_bytes(locator: dict[str, Any]) -> bytes:
    path = Path(locator["path"])
    if path.is_symlink() or not path.is_file():
        raise RetentionError("RETENTION_BYTE_DRIFT", "locator unavailable")
    if locator["kind"] == "file":
        data = path.read_bytes()
    elif locator["kind"] == "tar":
        with tarfile.open(path, "r:*") as archive:
            member = archive.getmember(locator["member"])
            stream = archive.extractfile(member)
            if stream is None:
                raise RetentionError("RETENTION_BYTE_DRIFT", "archive member unavailable")
            data = stream.read(MAX_FILE_BYTES + 1)
    elif locator["kind"] == "git":
        result = subprocess.run(["/usr/bin/git", "-C", locator["cache"], "cat-file", "blob", locator["oid"]],
                                capture_output=True, check=False, timeout=30)
        if result.returncode:
            raise RetentionError("RETENTION_BYTE_DRIFT", "bundle object unavailable")
        data = result.stdout
    else:
        raise RetentionError("RETENTION_LOCATOR_INVALID")
    if len(data) > MAX_FILE_BYTES:
        raise RetentionError("RETENTION_OBJECT_TOO_LARGE")
    return data


def _redact(value: Any) -> Any:
    if isinstance(value, str):
        return HOST_TEXT.sub("<HOST_REDACTED>", value)
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, dict):
        return {HOST_TEXT.sub("<HOST_REDACTED>", str(key)): _redact(item) for key, item in value.items()}
    return value


def _pointer(value: Any, pointer: str) -> Any:
    if pointer in ("", "/"):
        return value
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise RetentionError("JSON_POINTER_INVALID")
    current = value
    for raw in pointer[1:].split("/"):
        part = raw.replace("~1", "/").replace("~0", "~")
        try:
            current = current[int(part)] if isinstance(current, list) else current[part]
        except (KeyError, IndexError, ValueError, TypeError) as exc:
            raise RetentionError("JSON_POINTER_NOT_FOUND", pointer) from exc
    return current


def _outline(value: Any, depth: int = 0) -> Any:
    if depth >= 4:
        return {"type": type(value).__name__}
    if isinstance(value, dict):
        return {"type": "object", "size": len(value),
                "keys": {str(key): _outline(item, depth + 1) for key, item in list(value.items())[:100]}}
    if isinstance(value, list):
        return {"type": "array", "size": len(value),
                "sample": [_outline(item, depth + 1) for item in value[:3]]}
    return {"type": "null" if value is None else type(value).__name__}


def _numeric_summary(value: Any) -> dict[str, Any]:
    stack, count, finite_count, nonzero_count = [value], 0, 0, 0
    minimum = maximum = None
    squares = 0.0
    while stack:
        item = stack.pop()
        if isinstance(item, (int, float)) and not isinstance(item, bool):
            count += 1
            if count > 1_000_000:
                raise RetentionError("RETENTION_NUMERIC_SUMMARY_TOO_LARGE")
            number = float(item)
            if math.isfinite(number):
                finite_count += 1; nonzero_count += number != 0
                minimum = number if minimum is None else min(minimum, number)
                maximum = number if maximum is None else max(maximum, number)
                squares += number * number
        elif isinstance(item, list):
            stack.extend(item)
        elif isinstance(item, dict):
            stack.extend(item.values())
    return {"numeric_count": count, "shape": _json_shape(value),
            "finite_count": finite_count, "nonzero_count": nonzero_count,
            "minimum": minimum, "maximum": maximum,
            "l2_norm": math.sqrt(squares) if finite_count else None}


def _json_shape(value: Any) -> list[int] | None:
    shape: list[int] = []
    current = value
    while isinstance(current, list):
        shape.append(len(current))
        if not current:
            return shape
        first_shape = _json_shape(current[0])
        if any(_json_shape(item) != first_shape for item in current[1:]):
            return None
        if first_shape:
            shape.extend(first_shape)
        return shape
    return []


def inspect(job_id: str, retention_id: str, operation: str, json_pointer: str = "",
            offset: int = 0, limit: int = PAGE_LIMIT) -> dict[str, Any]:
    if not isinstance(job_id, str) or not re.fullmatch(r"MEPHC-JOB-[A-Z0-9][A-Z0-9._-]{7,119}", job_id):
        raise RetentionError("RETENTION_JOB_ID_INVALID")
    if (not isinstance(retention_id, str) or not isinstance(operation, str)
            or not isinstance(json_pointer, str) or not ID.fullmatch(retention_id)
            or operation not in {"metadata", "outline", "json_page", "numeric_summary"}):
        raise RetentionError("RETENTION_INSPECT_SCHEMA_INVALID")
    if not isinstance(offset, int) or offset < 0 or not isinstance(limit, int) or not 1 <= limit <= PAGE_LIMIT:
        raise RetentionError("RETENTION_PAGE_INVALID")
    job_dir = config.JOBS / job_id
    binding, locator, opaque = _load_locator(job_dir, retention_id)
    data = _locator_bytes(locator)
    digest = hashlib.sha256(data).hexdigest()
    if digest != binding["expected_sha256"]:
        raise RetentionError("RETENTION_BYTE_DRIFT", f"expected={binding['expected_sha256']} actual={digest}")
    base = {"schema": "mephc-retention-inspect-v1", "retention_id": retention_id,
            "sha256": digest, "bytes": len(data), "opaque_locator": opaque, "redactions_applied": True}
    if operation == "metadata":
        try:
            parsed = json.loads(data.decode("utf-8"))
            kind = ("object" if isinstance(parsed, dict) else "array" if isinstance(parsed, list)
                    else "null" if parsed is None else "boolean" if isinstance(parsed, bool)
                    else "number" if isinstance(parsed, (int, float)) else "string")
        except (UnicodeDecodeError, json.JSONDecodeError): kind = "non_json"
        return {**base, "json_type": kind, "match_status": "EXACT_SHA256"}
    if len(data) > MAX_JSON_BYTES:
        raise RetentionError("RETENTION_JSON_TOO_LARGE")
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RetentionError("RETENTION_JSON_INVALID") from exc
    selected = _pointer(value, json_pointer)
    if operation == "outline":
        return {**base, "json_pointer": json_pointer, "outline": _outline(selected)}
    if operation == "numeric_summary":
        return {**base, "json_pointer": json_pointer, **_numeric_summary(selected)}
    if isinstance(selected, list):
        page, total = selected[offset:offset + limit], len(selected)
    elif isinstance(selected, dict):
        items = sorted(selected.items(), key=lambda item: str(item[0])); page, total = dict(items[offset:offset + limit]), len(items)
    else:
        page, total = selected, 1
    page = _redact(page)
    if len(canonical(page)) > PAGE_MAX_BYTES:
        raise RetentionError("RETENTION_PAGE_TOO_LARGE", "select a narrower JSON pointer or page")
    return {**base, "json_pointer": json_pointer, "offset": offset,
            "next_offset": offset + limit if offset + limit < total else None,
            "total_items": total, "value": page}


def main(argv: list[str] | None = None) -> int:
    if argv is None: argv = sys.argv[1:]
    if len(argv) != 3 or argv[0] != "search":
        raise SystemExit("usage: retention_inspector.py search JOB_DIR EXECUTION_ROOT")
    return run_search(Path(argv[1]), Path(argv[2]))


if __name__ == "__main__":
    raise SystemExit(main())
