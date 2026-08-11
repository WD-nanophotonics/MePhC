from __future__ import annotations

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
from typing import Any
import pickle
import re


def _compact_number(value: Any) -> str:
    if isinstance(value, float):
        text = f"{value:g}"
    else:
        text = str(value)
    return text.replace(".", "p").replace("-", "m")


def _safe_token(value: Any) -> str:
    text = str(value).strip()
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", text)
    text = re.sub(r"_+", "_", text)
    return text.strip("_")


def timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def make_geometry_id(lattice_type: str, feature: str, *, a=None, d=None, n_eff=None) -> str:
    """Build the short directory identifier shared by data and image records."""
    lattice_tokens = {
        "square": "SQR_LATT",
        "sqr": "SQR_LATT",
        "triangular": "TRI_LATT",
        "tri": "TRI_LATT",
    }
    feature_tokens = {
        "square_hole": "SQR_HOLE",
        "sqr_hole": "SQR_HOLE",
        "circle_hole": "CIR_HOLE",
        "circular_hole": "CIR_HOLE",
        "polygon_hole": "POLY_HOLE",
    }
    parts = [lattice_tokens.get(str(lattice_type).lower(), _safe_token(lattice_type).upper())]
    parts.append(feature_tokens.get(str(feature).lower(), _safe_token(feature).upper()))
    if a is not None:
        parts.append(f"A{_compact_number(a)}")
    if d is not None:
        parts.append(f"D{_compact_number(d)}")
    if n_eff is not None:
        parts.append(f"NEFF{_compact_number(n_eff)}")
    return "_".join(parts)


def make_record_name(
    kind: str,
    *,
    polarization=None,
    num_bands=None,
    path=None,
    band_index=None,
    grid_n=None,
    grid_extent=None,
    symmetry=None,
    step=None,
    created_at=None,
) -> str:
    """Build a timestamped archive filename from task-defining parameters."""
    parts = [_safe_token(kind)]
    if polarization is not None:
        parts.append(_safe_token(polarization).lower())
    if kind == "band" and num_bands is not None:
        parts.append(f"nb{num_bands}")
    if kind in {"bc", "berry", "berry_curvature"} and band_index is None and num_bands is not None:
        parts.append(f"nb{num_bands}")
    if path is not None:
        parts.append(_safe_token(path).lower())
    if kind in {"bc", "berry", "berry_curvature", "efs"} and band_index is not None:
        parts.append(f"b{int(band_index) + 1}")
    if grid_n is not None:
        parts.append(f"n{grid_n}")
    if grid_extent is not None:
        parts.append(f"ext{_compact_number(grid_extent)}")
    if symmetry is not None:
        parts.append(_safe_token(symmetry).lower())
    if step is not None:
        parts.append(f"step{_compact_number(step)}")
    parts.append(created_at or timestamp())
    return "_".join(parts) + ".pkl"


def make_record(kind: str, geometry_id: str, *, task_params=None, compute_params=None, data=None, source_case=None, created_at=None) -> dict[str, Any]:
    """Create the standard pickle payload.

    ``task_params`` defines what data was requested and participates in the
    canonical filename. ``compute_params`` records numerical settings such as
    resolution but does not lengthen filenames. Plot settings belong in neither.
    """
    return {
        "kind": kind,
        "geometry_id": geometry_id,
        "task_params": dict(task_params or {}),
        "compute_params": dict(compute_params or {}),
        "data": data,
        "created_at": created_at or timestamp(),
        "source_case": source_case,
    }




def make_task_key(kind: str, task_params: dict[str, Any] | None = None) -> str:
    """Return a short stable filename stem for a simulation task, without timestamp."""
    params = dict(task_params or {})
    kind = _safe_token(kind)
    num_bands = params.get("num_bands")
    path_name = params.get("path")
    band_index = params.get("band_index")
    polarization = params.get("polarization")
    grid_n = params.get("grid_n")
    grid_extent = params.get("grid_extent")
    symmetry = params.get("symmetry")
    step = params.get("step")
    parts = [kind]
    if polarization is not None:
        parts.append(_safe_token(polarization).lower())
    if kind == "band" and num_bands is not None:
        parts.append(f"nb{num_bands}")
    if kind in {"bc", "berry", "berry_curvature"}:
        if band_index is None and num_bands is not None:
            parts.append(f"nb{num_bands}")
        elif band_index is not None:
            parts.append(f"b{int(band_index) + 1}")
    if kind == "efs" and band_index is not None:
        parts.append(f"b{int(band_index) + 1}")
    if path_name is not None:
        parts.append(_safe_token(path_name).lower())
    if grid_n is not None:
        parts.append(f"n{grid_n}")
    if grid_extent is not None:
        parts.append(f"ext{_compact_number(grid_extent)}")
    if symmetry is not None:
        parts.append(_safe_token(symmetry).lower())
    if step is not None:
        parts.append(f"step{_compact_number(step)}")
    return "_".join(parts)


def canonical_record_path(project_root: str | Path, geometry_id: str, kind: str, task_params: dict[str, Any] | None = None) -> Path:
    """Return the stable, overwriteable path used by automatic record reuse."""
    return data_dir(project_root, geometry_id) / f"{make_task_key(kind, task_params)}.pkl"


def _records_match(
    record: dict[str, Any],
    *,
    kind: str,
    geometry_id: str,
    task_params: dict[str, Any] | None = None,
    compute_params: dict[str, Any] | None = None,
    require_compute_match: bool = True,
) -> bool:
    if record.get("kind") != kind or record.get("geometry_id") != geometry_id:
        return False
    if dict(record.get("task_params") or {}) != dict(task_params or {}):
        return False
    if require_compute_match and dict(record.get("compute_params") or {}) != dict(compute_params or {}):
        return False
    return True


def find_matching_record(
    project_root: str | Path,
    geometry_id: str,
    kind: str,
    *,
    task_params: dict[str, Any] | None = None,
    compute_params: dict[str, Any] | None = None,
    require_compute_match: bool = True,
):
    """Return (record, path) when the canonical record matches the requested metadata."""
    path = canonical_record_path(project_root, geometry_id, kind, task_params)
    if not path.exists():
        return None, None
    try:
        record = load_record(path)
    except Exception:
        return None, None
    if _records_match(
        record,
        kind=kind,
        geometry_id=geometry_id,
        task_params=task_params,
        compute_params=compute_params,
        require_compute_match=require_compute_match,
    ):
        return record, path
    return None, None


def save_record(record: dict[str, Any], path: str | Path) -> Path:
    """Pickle a record, creating parent directories and enforcing ``.pkl``."""
    path = Path(path)
    if path.suffix != ".pkl":
        path = path.with_suffix(".pkl")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as file:
        pickle.dump(record, file)
    return path


def load_record(path: str | Path) -> dict[str, Any]:
    """Load and return a previously saved pickle record."""
    path = Path(path)
    with path.open("rb") as file:
        return pickle.load(file)


def data_dir(project_root: str | Path, geometry_id: str) -> Path:
    return Path(project_root) / "data" / geometry_id


def tmp_dir(project_root: str | Path) -> Path:
    return Path(project_root) / "data" / "_tmp"


def image_dir(project_root: str | Path, geometry_id: str) -> Path:
    return Path(project_root) / "image" / geometry_id


def make_image_path(project_root: str | Path, record_path: str | Path, geometry_id: str, suffix: str = ".png") -> Path:
    """Derive a reproducible image path from a record basename."""
    record_path = Path(record_path)
    return image_dir(project_root, geometry_id) / (record_path.stem + suffix)


def archive_manifest_path(project_root: str | Path) -> Path:
    """Return the tracked metadata index for local binary records."""
    return Path(project_root) / "archive_manifest.json"


def _record_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def update_archive_manifest(
    project_root: str | Path,
    record_path: str | Path,
    record: dict[str, Any],
    *,
    include_hash: bool = True,
) -> Path:
    """Upsert lightweight metadata for a local pickle record.

    The pickle itself remains local and is never copied into the manifest.
    Paths are stored relative to ``project_root`` so the manifest is portable.
    """
    project_root = Path(project_root)
    record_path = Path(record_path)
    manifest_path = archive_manifest_path(project_root)
    try:
        relative_path = Path(os.path.relpath(record_path, project_root)).as_posix()
    except ValueError:
        relative_path = record_path.name

    payload = {"schema_version": 1, "records": []}
    if manifest_path.exists():
        try:
            loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and isinstance(loaded.get("records"), list):
                payload = loaded
        except (OSError, json.JSONDecodeError):
            pass

    entry = {
        "record": relative_path,
        "kind": record.get("kind"),
        "geometry_id": record.get("geometry_id"),
        "task_params": dict(record.get("task_params") or {}),
        "compute_params": dict(record.get("compute_params") or {}),
        "created_at": record.get("created_at"),
    }
    if include_hash and record_path.exists():
        entry["sha256"] = _record_sha256(record_path)

    records = [item for item in payload["records"] if item.get("record") != relative_path]
    records.append(entry)
    payload["records"] = sorted(records, key=lambda item: item.get("record", ""))
    manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest_path
