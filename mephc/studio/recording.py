from __future__ import annotations

from pathlib import Path

from mephc.records import load_record


OPERATION_KIND = {
    "band_structure": "band",
    "berry_curvature": "bc",
    "efs": "efs",
}

_LATEST_NAMES = {
    "band_structure": "band_latest.pkl",
    "berry_curvature": "bc_latest.pkl",
    "efs": "efs_latest.pkl",
}

_FILE_PATTERNS = {
    "band_structure": "band*.pkl",
    "berry_curvature": "bc*.pkl",
    "efs": "efs*.pkl",
}


def expected_kind(operation: str) -> str:
    try:
        return OPERATION_KIND[operation]
    except KeyError as exc:
        raise ValueError(f"{operation!r} does not produce a plottable record") from exc


def validate_record(
    record_or_path,
    operation: str,
    *,
    expected_geometry_id: str | None = None,
) -> tuple[dict, Path | None]:
    path = None
    if isinstance(record_or_path, (str, Path)):
        path = Path(record_or_path).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        record = load_record(path)
    else:
        record = record_or_path
    if not isinstance(record, dict):
        raise ValueError("record must be a dictionary")
    kind = expected_kind(operation)
    if record.get("kind") != kind:
        raise ValueError(
            f"Selected record is {record.get('kind')!r}; {operation} requires {kind!r}."
        )
    if expected_geometry_id is not None and record.get("geometry_id") != expected_geometry_id:
        raise ValueError(
            "Record geometry does not match the current Geometry inputs: "
            f"{record.get('geometry_id')!r} != {expected_geometry_id!r}."
        )
    return record, path


def browse_directory(project_root: str | Path, geometry_id: str) -> Path:
    root = Path(project_root)
    geometry_root = root / "data" / geometry_id
    return geometry_root if geometry_root.is_dir() else root / "data"


def browse_pattern(operation: str) -> str:
    try:
        return _FILE_PATTERNS[operation]
    except KeyError as exc:
        raise ValueError(f"{operation!r} has no record file pattern") from exc


def discover_records(project_root: str | Path, geometry_id: str, operation: str) -> list[Path]:
    root = Path(project_root)
    candidates = list((root / "data" / geometry_id).glob(browse_pattern(operation)))
    latest = root / "data" / "_tmp" / _LATEST_NAMES[operation]
    if latest.is_file():
        candidates.append(latest)
    valid = []
    for path in candidates:
        try:
            validate_record(path, operation, expected_geometry_id=geometry_id)
        except (OSError, ValueError, TypeError):
            continue
        valid.append(path.resolve())
    return sorted(set(valid), key=lambda path: path.stat().st_mtime_ns, reverse=True)
