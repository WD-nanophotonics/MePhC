#!/usr/bin/env python3
"""Archive unresolved legacy residue without deleting source files."""
from __future__ import annotations
import argparse, gzip, hashlib, io, json, re, tarfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

MEPHC_ROOT = Path("/home/icy/MePhC")
REPOSITORY_ROOTS = {
    "TRILATT": Path("/home/icy/TriLatt"),
    "GMAILCOURIER": Path("/mnt/c/Users/icywo/PycharmProjects/GmailCourier"),
}
SENSITIVE_PATH = re.compile(
    r"(?i)(^|/)(\.env(?:\.|$)|credentials?(?:\.|$)|token(?:\.|$)|"
    r"cookies?(?:\.|$)|id_rsa(?:\.|$)|[^/]+\.(?:pem|key|p12|pfx)$)"
)
SENSITIVE_CONTENT = re.compile(
    rb"(?i)(client_secret|refresh_token|access_token|api[_-]?key|"
    rb"authorization\s*[:=]\s*bearer|password\s*[:=])"
)

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def sensitive_content(path: Path) -> bool:
    overlap = b""
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            sample = overlap + chunk
            if SENSITIVE_CONTENT.search(sample):
                return True
            overlap = sample[-128:]
    return False

def safe_source(root: Path, relative: str) -> Path:
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts:
        raise RuntimeError(f"UNSAFE_ARCHIVE_PATH:{relative}")
    source = root.joinpath(*pure.parts)
    resolved_root, resolved_source = root.resolve(), source.resolve()
    if resolved_source == resolved_root or resolved_root not in resolved_source.parents:
        raise RuntimeError(f"UNSAFE_ARCHIVE_PATH:{relative}")
    return source

def candidate_entries(report: dict, roots: dict[str, Path]) -> list[dict]:
    entries = []
    for repository in report.get("repositories", []):
        project_id = repository.get("project_id")
        if project_id not in roots:
            continue
        for residue in repository.get("residues", []):
            if residue.get("classification") != "AMBIGUOUS_FAIL_CLOSED":
                continue
            relative = str(residue["path"]).replace("\\", "/")
            entries.append({
                "project_id": project_id,
                "original_path": relative,
                "source": safe_source(roots[project_id], relative),
                "bytes": int(residue["bytes"]),
                "sha256": residue["sha256"],
                "archive_member": f"{project_id}/{relative}",
            })
    return sorted(entries, key=lambda item: (item["project_id"], item["original_path"]))

def scan(report: dict, roots: dict[str, Path] | None = None) -> dict:
    roots = roots or REPOSITORY_ROOTS
    accepted, rejected = [], []
    for entry in candidate_entries(report, roots):
        source = entry["source"]
        public = {key: value for key, value in entry.items() if key != "source"}
        if not source.is_file() or source.is_symlink():
            rejected.append({**public, "reason": "NOT_REGULAR_FILE"})
            continue
        actual_size, actual_sha = source.stat().st_size, sha256_file(source)
        if actual_size != entry["bytes"] or actual_sha != entry["sha256"]:
            rejected.append({**public, "reason": "SOURCE_BYTE_MISMATCH",
                             "actual_bytes": actual_size, "actual_sha256": actual_sha})
        elif SENSITIVE_PATH.search(entry["archive_member"]):
            rejected.append({**public, "reason": "SECRET_OR_CREDENTIAL_PATH"})
        elif sensitive_content(source):
            rejected.append({**public, "reason": "SECRET_OR_CREDENTIAL_CONTENT"})
        else:
            accepted.append(public)
    return {"schema": "mephc-residue-sensitivity-scan-v1",
            "accepted": accepted, "rejected": rejected,
            "accepted_count": len(accepted), "rejected_count": len(rejected),
            "accepted_bytes": sum(item["bytes"] for item in accepted)}

def deterministic_tar_gz(entries: list[dict], roots: dict[str, Path]) -> bytes:
    raw = io.BytesIO()
    with gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as gz:
        with tarfile.open(fileobj=gz, mode="w", format=tarfile.PAX_FORMAT) as output:
            for entry in entries:
                source = safe_source(roots[entry["project_id"]], entry["original_path"])
                data = source.read_bytes()
                if len(data) != entry["bytes"] or sha256_bytes(data) != entry["sha256"]:
                    raise RuntimeError(f"SOURCE_BYTE_MISMATCH:{entry['archive_member']}")
                info = tarfile.TarInfo(entry["archive_member"])
                info.size, info.mode, info.uid, info.gid, info.mtime = len(data), 0o600, 0, 0, 0
                info.uname = info.gname = ""
                output.addfile(info, io.BytesIO(data))
    return raw.getvalue()

def write_scan(result: dict) -> Path:
    root = MEPHC_ROOT / ".relayctl" / "inventory"
    root.mkdir(parents=True, exist_ok=True)
    path = root / ("sensitivity-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + ".json")
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path

def create_archive(report_path: Path, artifact_id: str, result: dict) -> Path:
    if result["rejected_count"]:
        raise RuntimeError("AMBIGUOUS_FAIL_CLOSED:SENSITIVITY_SCAN_REJECTED")
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9._-]{7,79}", artifact_id):
        raise RuntimeError("INVALID_ARTIFACT_ID")
    output = MEPHC_ROOT / "audit" / "archive" / artifact_id
    if output.exists():
        raise RuntimeError("ARCHIVE_ALREADY_EXISTS")
    output.mkdir(parents=True)
    payload = deterministic_tar_gz(result["accepted"], REPOSITORY_ROOTS)
    (output / "payload.tar.gz").write_bytes(payload)
    manifest = {
        "schema": "mephc-residue-archive-v1", "artifact_id": artifact_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "retention_report": str(report_path),
        "retention_report_sha256": sha256_file(report_path),
        "payload": "payload.tar.gz", "payload_sha256": sha256_bytes(payload),
        "file_count": result["accepted_count"], "bytes_uncompressed": result["accepted_bytes"],
        "files": result["accepted"],
        "recovery": "Extract payload.tar.gz from the producing Git commit and verify every member.",
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "RESTORE.md").write_text(
        f"# {artifact_id}\n\nThis commit preserves legacy local residue before exact-path cleanup.\n"
        "Verify payload.tar.gz and each extracted member against manifest.json.\n", encoding="utf-8")
    return output

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
