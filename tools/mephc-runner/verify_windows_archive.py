#!/home/icy/miniconda3/envs/mp/bin/python
"""Verify every compressed and restored byte in a Windows-copy archive."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile
from typing import Any, BinaryIO


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stream_identity(stream: BinaryIO) -> tuple[int, str]:
    count = 0
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        count += len(chunk)
        digest.update(chunk)
    return count, digest.hexdigest()


class PartReader:
    def __init__(self, paths: list[Path]):
        self.paths = paths
        self.index = 0
        self.handle: BinaryIO | None = None

    def _advance(self) -> bool:
        if self.handle is not None:
            self.handle.close()
        if self.index >= len(self.paths):
            self.handle = None
            return False
        self.handle = self.paths[self.index].open("rb")
        self.index += 1
        return True

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            chunks = []
            while True:
                if self.handle is None and not self._advance():
                    break
                assert self.handle is not None
                data = self.handle.read()
                if data:
                    chunks.append(data)
                self.handle = None
            return b"".join(chunks)
        output = bytearray()
        while len(output) < size:
            if self.handle is None and not self._advance():
                break
            assert self.handle is not None
            data = self.handle.read(size - len(output))
            if data:
                output.extend(data)
            else:
                self.handle.close()
                self.handle = None
        return bytes(output)

    def close(self) -> None:
        if self.handle is not None:
            self.handle.close()
            self.handle = None


def verify_archive(root: Path) -> dict[str, Any]:
    manifest_path = root / "manifest.json"
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    if manifest.get("schema") != "mephc-windows-copy-archive-v1":
        raise RuntimeError("ARCHIVE_SCHEMA_MISMATCH")
    payload_records = {item["path"]: item for item in manifest["payloads"]}
    actual_payloads = {
        path.relative_to(root).as_posix()
        for path in (root / "payload").rglob("*")
        if path.is_file()
    }
    if actual_payloads != set(payload_records):
        raise RuntimeError("ARCHIVE_PAYLOAD_SET_MISMATCH")
    for relative, item in payload_records.items():
        path = root / relative
        if path.stat().st_size != item["bytes"] or sha256_file(path) != item["sha256"]:
            raise RuntimeError(f"ARCHIVE_PAYLOAD_BYTE_MISMATCH:{relative}")
    expected: dict[str, dict[str, Any]] = {}
    for item in manifest["files"]:
        prior = expected.setdefault(item["sha256"], {
            "bytes": item["bytes"],
            "storage": item["storage"],
        })
        if prior["bytes"] != item["bytes"] or prior["storage"] != item["storage"]:
            raise RuntimeError(f"ARCHIVE_BLOB_MAPPING_CONFLICT:{item['sha256']}")
    recovered: dict[str, tuple[int, str]] = {}
    tar_payloads = sorted({
        item["storage"]["payload"]["path"]
        for item in manifest["files"]
        if item["storage"]["format"] == "tar-gzip"
    })
    for relative in tar_payloads:
        with tarfile.open(root / relative, "r:gz") as archive:
            for member in archive:
                if not member.isfile():
                    continue
                sha256 = PurePosixPath(member.name).name
                if sha256 in recovered:
                    raise RuntimeError(f"ARCHIVE_DUPLICATE_BLOB:{sha256}")
                stream = archive.extractfile(member)
                if stream is None:
                    raise RuntimeError(f"ARCHIVE_MEMBER_UNREADABLE:{member.name}")
                recovered[sha256] = stream_identity(stream)
    for sha256, item in expected.items():
        storage = item["storage"]
        if storage["format"] != "split-gzip":
            continue
        reader = PartReader([root / part["path"] for part in storage["parts"]])
        try:
            with gzip.GzipFile(fileobj=reader, mode="rb") as stream:
                recovered[sha256] = stream_identity(stream)
        finally:
            reader.close()
    if set(recovered) != set(expected):
        raise RuntimeError("ARCHIVE_RECOVERED_BLOB_SET_MISMATCH")
    for sha256, (count, actual_sha256) in recovered.items():
        if count != expected[sha256]["bytes"] or actual_sha256 != sha256:
            raise RuntimeError(f"ARCHIVE_RESTORED_BYTE_MISMATCH:{sha256}")
    return {
        "schema": "mephc-windows-copy-archive-verification-v1",
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "artifact_id": manifest["artifact_id"],
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "payload_count": len(payload_records),
        "reference_count": manifest["reference_count"],
        "reference_bytes": manifest["reference_bytes"],
        "unique_blob_count": len(expected),
        "unique_blob_bytes": sum(item["bytes"] for item in expected.values()),
        "status": "VERIFIED",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    result = verify_archive(args.archive)
    temporary = args.receipt.with_suffix(args.receipt.suffix + ".tmp")
    temporary.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(args.receipt)
    print(args.receipt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
