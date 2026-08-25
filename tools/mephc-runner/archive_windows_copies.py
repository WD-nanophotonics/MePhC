#!/home/icy/miniconda3/envs/mp/bin/python
"""Create a deterministic content-addressed archive for Windows legacy copies."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import tarfile
from typing import Any, BinaryIO

MEPHC_ROOT = Path("/home/icy/MePhC")
ARCHIVE_ROOT = MEPHC_ROOT / "audit" / "archive"
INVENTORY_ROOT = MEPHC_ROOT / ".relayctl" / "inventory"
COPY_ROOTS = {
    "AGENTRELAY": Path("/mnt/c/Users/icywo/PycharmProjects/AgentRelay"),
    "CHATSEQUENCERUNNER": Path("/mnt/c/Users/icywo/PycharmProjects/ChatSequenceRunner"),
    "MEPHC_WINDOWS": Path("/mnt/c/Users/icywo/PycharmProjects/MePhC-Windows"),
    "RETIRED_MEPHC": Path("/mnt/c/Users/icywo/PycharmProjects/_retired-windows-copies-20260818/MePhC"),
    "RETIRED_SQRLATT": Path("/mnt/c/Users/icywo/PycharmProjects/_retired-windows-copies-20260818/MePhC-SqrLatt"),
    "RETIRED_TRILATT": Path("/mnt/c/Users/icywo/PycharmProjects/_retired-windows-copies-20260818/MePhC-TriLatt"),
    "RETIRED_MEPHC_WINDOWS": Path("/mnt/c/Users/icywo/PycharmProjects/_retired-windows-copies-20260818/MePhC-Windows"),
}
BUNDLE_LIMIT = 32 * 1024 * 1024
PART_LIMIT = 80 * 1024 * 1024
SENSITIVE_PATH = re.compile(
    r"(?i)(^|/)(\.env(?:\.|$)|credentials?(?:\.|$)|token(?:\.|$)|"
    r"cookies?(?:\.|$)|id_rsa(?:\.|$)|[^/]+\.(?:pem|key|p12|pfx)$)"
)
SENSITIVE_CONTENT = re.compile(
    rb"(?i)(client_secret|refresh_token|access_token|api[_-]?key|"
    rb"authorization\s*[:=]\s*bearer|password\s*[:=])"
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_source(root: Path, relative: str) -> Path:
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts:
        raise RuntimeError(f"UNSAFE_ARCHIVE_PATH:{relative}")
    source = root.joinpath(*pure.parts)
    resolved_root = root.resolve()
    resolved_source = source.resolve()
    if resolved_source == resolved_root or resolved_root not in resolved_source.parents:
        raise RuntimeError(f"UNSAFE_ARCHIVE_PATH:{relative}")
    return source


def sensitive_content(path: Path) -> bool:
    overlap = b""
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            sample = overlap + chunk
            if SENSITIVE_CONTENT.search(sample):
                return True
            overlap = sample[-128:]
    return False


def candidate_entries(report: dict[str, Any], roots: dict[str, Path]) -> list[dict[str, Any]]:
    entries = []
    for copy in report.get("copy_roots", []):
        project_id = copy.get("project_id")
        if project_id not in roots:
            raise RuntimeError(f"UNAPPROVED_COPY_ROOT:{project_id}")
        if Path(copy.get("path", "")) != roots[project_id]:
            raise RuntimeError(f"COPY_ROOT_MISMATCH:{project_id}")
        for item in copy.get("files", []):
            if item.get("classification") != "AMBIGUOUS_FAIL_CLOSED":
                continue
            relative = str(item["path"]).replace("\\", "/")
            entries.append({
                "project_id": project_id,
                "original_path": relative,
                "source": safe_source(roots[project_id], relative),
                "bytes": int(item["bytes"]),
                "sha256": item["sha256"],
            })
    return sorted(entries, key=lambda item: (item["project_id"], item["original_path"]))


def scan(report: dict[str, Any], roots: dict[str, Path] | None = None) -> dict[str, Any]:
    roots = roots or COPY_ROOTS
    accepted, rejected = [], []
    for entry in candidate_entries(report, roots):
        source = entry["source"]
        public = {key: value for key, value in entry.items() if key != "source"}
        if not source.is_file() or source.is_symlink():
            rejected.append({**public, "reason": "NOT_REGULAR_FILE"})
            continue
        actual_bytes = source.stat().st_size
        actual_sha256 = sha256_file(source)
        if actual_bytes != entry["bytes"] or actual_sha256 != entry["sha256"]:
            rejected.append({
                **public, "reason": "SOURCE_BYTE_MISMATCH",
                "actual_bytes": actual_bytes, "actual_sha256": actual_sha256,
            })
        elif SENSITIVE_PATH.search(f"{entry['project_id']}/{entry['original_path']}"):
            rejected.append({**public, "reason": "SECRET_OR_CREDENTIAL_PATH"})
        elif sensitive_content(source):
            rejected.append({**public, "reason": "SECRET_OR_CREDENTIAL_CONTENT"})
        else:
            accepted.append(public)
    unique = {}
    for entry in accepted:
        unique.setdefault(entry["sha256"], entry)
    return {
        "schema": "mephc-windows-copy-sensitivity-v1",
        "accepted": accepted,
        "rejected": rejected,
        "accepted_count": len(accepted),
        "accepted_bytes": sum(item["bytes"] for item in accepted),
        "unique_blob_count": len(unique),
        "unique_blob_bytes": sum(item["bytes"] for item in unique.values()),
        "rejected_count": len(rejected),
    }


class SplitWriter:
    def __init__(self, directory: Path, stem: str, limit: int = PART_LIMIT):
        self.directory = directory
        self.stem = stem
        self.limit = limit
        self.parts: list[Path] = []
        self.handle: BinaryIO | None = None
        self.part_bytes = 0
        self.total = 0

    def _open(self) -> None:
        path = self.directory / f"{self.stem}.part-{len(self.parts):03d}"
        self.handle = path.open("wb")
        self.parts.append(path)
        self.part_bytes = 0

    def write(self, data: bytes) -> int:
        view = memoryview(data)
        written = 0
        while view:
            if self.handle is None or self.part_bytes == self.limit:
                if self.handle is not None:
                    self.handle.close()
                self._open()
            count = min(len(view), self.limit - self.part_bytes)
            assert self.handle is not None
            self.handle.write(view[:count])
            view = view[count:]
            written += count
            self.part_bytes += count
            self.total += count
        return written

    def flush(self) -> None:
        if self.handle is not None:
            self.handle.flush()

    def tell(self) -> int:
        return self.total

    def close(self) -> None:
        if self.handle is not None:
            self.handle.close()
            self.handle = None


def gzip_blob(source: Path, directory: Path, sha256: str) -> list[Path]:
    writer = SplitWriter(directory, f"{sha256}.gz")
    try:
        with gzip.GzipFile(filename="", mode="wb", fileobj=writer, mtime=0, compresslevel=6) as output:
            with source.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    output.write(chunk)
    finally:
        writer.close()
    return writer.parts


def tar_chunk(entries: list[dict[str, Any]], path: Path, roots: dict[str, Path]) -> None:
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=6) as zipped:
            with tarfile.open(fileobj=zipped, mode="w", format=tarfile.PAX_FORMAT) as archive:
                for entry in entries:
                    source = safe_source(roots[entry["project_id"]], entry["original_path"])
                    info = tarfile.TarInfo(f"blobs/{entry['sha256']}")
                    info.size = entry["bytes"]
                    info.mode, info.uid, info.gid, info.mtime = 0o600, 0, 0, 0
                    info.uname = info.gname = ""
                    with source.open("rb") as stream:
                        archive.addfile(info, stream)


def payload_record(output: Path, path: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(output).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def create_archive(
    report_path: Path,
    artifact_id: str,
    scan_result: dict[str, Any],
    roots: dict[str, Path] | None = None,
    archive_root: Path = ARCHIVE_ROOT,
) -> Path:
    roots = roots or COPY_ROOTS
    if scan_result["rejected_count"]:
        raise RuntimeError("AMBIGUOUS_FAIL_CLOSED:SENSITIVITY_SCAN_REJECTED")
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9._-]{7,99}", artifact_id):
        raise RuntimeError("INVALID_ARTIFACT_ID")
    output = archive_root / artifact_id
    if output.exists():
        raise RuntimeError("ARCHIVE_ALREADY_EXISTS")
    blobs_dir = output / "payload" / "blobs"
    chunks_dir = output / "payload" / "chunks"
    blobs_dir.mkdir(parents=True)
    chunks_dir.mkdir(parents=True)
    unique: dict[str, dict[str, Any]] = {}
    for entry in scan_result["accepted"]:
        unique.setdefault(entry["sha256"], entry)
    storage: dict[str, dict[str, Any]] = {}
    payloads: list[dict[str, Any]] = []
    small = [entry for entry in unique.values() if entry["bytes"] < BUNDLE_LIMIT]
    large = [entry for entry in unique.values() if entry["bytes"] >= BUNDLE_LIMIT]
    for entry in sorted(large, key=lambda item: item["sha256"]):
        source = safe_source(roots[entry["project_id"]], entry["original_path"])
        parts = gzip_blob(source, blobs_dir, entry["sha256"])
        records = [payload_record(output, path) for path in parts]
        payloads.extend(records)
        storage[entry["sha256"]] = {"format": "split-gzip", "parts": records}
    groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_bytes = 0
    for entry in sorted(small, key=lambda item: item["sha256"]):
        if current and current_bytes + entry["bytes"] > BUNDLE_LIMIT:
            groups.append(current)
            current, current_bytes = [], 0
        current.append(entry)
        current_bytes += entry["bytes"]
    if current:
        groups.append(current)
    for index, group in enumerate(groups):
        path = chunks_dir / f"chunk-{index:03d}.tar.gz"
        tar_chunk(group, path, roots)
        if path.stat().st_size > PART_LIMIT:
            raise RuntimeError(f"ARCHIVE_PART_TOO_LARGE:{path}")
        record = payload_record(output, path)
        payloads.append(record)
        for entry in group:
            storage[entry["sha256"]] = {
                "format": "tar-gzip",
                "payload": record,
                "member": f"blobs/{entry['sha256']}",
            }
    files = []
    for entry in scan_result["accepted"]:
        files.append({
            **entry,
            "storage": storage[entry["sha256"]],
        })
    manifest = {
        "schema": "mephc-windows-copy-archive-v1",
        "artifact_id": artifact_id,
        "archive_commit": None,
        "archive_remote_ref": "origin/sandbox",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "retention_report": str(report_path),
        "retention_report_sha256": sha256_file(report_path),
        "reference_count": scan_result["accepted_count"],
        "reference_bytes": scan_result["accepted_bytes"],
        "unique_blob_count": scan_result["unique_blob_count"],
        "unique_blob_bytes": scan_result["unique_blob_bytes"],
        "payloads": sorted(payloads, key=lambda item: item["path"]),
        "files": files,
        "recovery": "Restore each SHA-addressed blob from split-gzip parts or tar-gzip member, then map it to every project_id/original_path reference.",
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8",
    )
    (output / "RESTORE.md").write_text(
        f"# {artifact_id}\n\nVerify manifest.json and every payload SHA-256 before restoring paths.\n",
        encoding="utf-8",
    )
    return output


def write_scan(result: dict[str, Any]) -> Path:
    INVENTORY_ROOT.mkdir(parents=True, exist_ok=True)
    path = INVENTORY_ROOT / (
        "windows-copy-sensitivity-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + ".json"
    )
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--retention-report", type=Path, required=True)
    parser.add_argument("--artifact-id")
    parser.add_argument("--create", action="store_true")
    args = parser.parse_args()
    report = json.loads(args.retention_report.read_text(encoding="utf-8"))
    result = scan(report)
    print(write_scan(result))
    if args.create:
        if not args.artifact_id:
            raise RuntimeError("ARTIFACT_ID_REQUIRED")
        print(create_archive(args.retention_report, args.artifact_id, result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
