from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from .profiles import validate_profile
from .plot_style import validate_plot_style
from .recording import validate_record


PROJECT_SCHEMA = "mephc-studio-project-v1"
PROJECT_EXTENSION = ".mephc-studio.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _project_root(document: dict) -> Path:
    value = document.get("project_root")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("project_root must be a non-empty path")
    return Path(value).expanduser().resolve()


def _relative_record_path(value: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("project record path must be non-empty")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("project record paths must stay inside the case project")
    return path


def new_project(profile: dict, project_root: str | Path | None = None) -> dict:
    profile = validate_profile(profile)
    root_value = project_root if project_root is not None else profile.get("project_root")
    if root_value is None:
        raise ValueError("a case project root is required")
    root = Path(root_value).expanduser().resolve()
    profile["project_root"] = str(root)
    return {
        "schema": PROJECT_SCHEMA,
        "case_id": profile["case_id"],
        "project_root": str(root),
        "current": deepcopy(profile),
        "results": [],
        "selected_result_id": None,
    }


def validate_project(document: dict) -> dict:
    if not isinstance(document, dict) or document.get("schema") != PROJECT_SCHEMA:
        raise ValueError(f"project schema must be {PROJECT_SCHEMA!r}")
    result = deepcopy(document)
    case_id = result.get("case_id")
    if case_id not in {"triangular", "square"}:
        raise ValueError("project case_id must be 'triangular' or 'square'")
    root = _project_root(result)
    current = validate_profile(result.get("current"), expected_case=case_id)
    if Path(current["project_root"]).expanduser().resolve() != root:
        raise ValueError("current profile project_root does not match the project")
    items = result.get("results")
    if not isinstance(items, list):
        raise ValueError("project results must be an array")
    identifiers = set()
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise ValueError("each project result requires an id")
        if item["id"] in identifiers:
            raise ValueError("project result ids must be unique")
        identifiers.add(item["id"])
        if item.get("operation") not in {"band_structure", "berry_curvature", "efs"}:
            raise ValueError("project result has an unsupported operation")
        reference = item.get("record")
        if not isinstance(reference, dict):
            raise ValueError("project result requires a record reference")
        _relative_record_path(reference.get("path", ""))
        digest = reference.get("sha256")
        if not isinstance(digest, str) or len(digest) != 64:
            raise ValueError("project record requires a SHA-256 digest")
        if not isinstance(reference.get("size"), int) or reference["size"] < 0:
            raise ValueError("project record requires a non-negative size")
        displayed_band = item.get("displayed_band")
        style = item.get("last_plot_style")
        if isinstance(style, dict):
            section_name = {"berry_curvature": "berry", "efs": "efs"}.get(item["operation"])
            legacy_section = style.get(section_name) if section_name else None
            if displayed_band is None and isinstance(legacy_section, dict) and isinstance(legacy_section.get("band_index"), int):
                displayed_band = legacy_section["band_index"] + 1
                item["displayed_band"] = displayed_band
            item["last_plot_style"] = validate_plot_style(style)
        if displayed_band is not None and (not isinstance(displayed_band, int) or displayed_band < 1):
            raise ValueError("project displayed_band must be a positive 1-based integer")
    selected = result.get("selected_result_id")
    if selected is not None and selected not in identifiers:
        result["selected_result_id"] = None
    result["project_root"] = str(root)
    result["current"] = current
    return result


def snapshot_result(
    document: dict,
    source: str | Path,
    *,
    operation: str,
    geometry: dict,
    calculation: dict,
    plot_style: dict,
    execution_disposition: str = "computed",
) -> tuple[dict, dict]:
    """Copy a record by content hash and return an updated project document."""
    document = validate_project(document)
    source = Path(source).expanduser().resolve()
    record, _ = validate_record(source, operation)
    root = _project_root(document)
    try:
        source.relative_to(root)
    except ValueError as exc:
        raise ValueError("scientific records must originate inside the case project") from exc
    digest = _sha256(source)
    destination = root / "data" / ".studio" / "records" / f"{digest}.pkl"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        fd, temporary = tempfile.mkstemp(prefix=f".{digest}.", dir=destination.parent)
        os.close(fd)
        try:
            shutil.copyfile(source, temporary)
            if _sha256(Path(temporary)) != digest:
                raise OSError("record changed while it was being snapshotted")
            os.replace(temporary, destination)
        except Exception:
            Path(temporary).unlink(missing_ok=True)
            raise
    elif _sha256(destination) != digest:
        raise OSError(f"content-addressed record is corrupt: {destination}")

    result_id = hashlib.sha256(
        f"{operation}\0{record.get('geometry_id')}\0{digest}".encode("utf-8")
    ).hexdigest()[:24]
    item = {
        "id": result_id,
        "operation": operation,
        "geometry_id": record.get("geometry_id"),
        "geometry": deepcopy(geometry),
        "calculation": deepcopy(calculation),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "execution_disposition": execution_disposition,
        "record": {
            "path": destination.relative_to(root).as_posix(),
            "sha256": digest,
            "size": destination.stat().st_size,
        },
        "last_plot_style": deepcopy(plot_style),
    }
    task_band = (record.get("task_params") or {}).get("band_index")
    if operation in {"berry_curvature", "efs"} and isinstance(task_band, int):
        item["displayed_band"] = task_band + 1
    existing = next((index for index, value in enumerate(document["results"]) if value["id"] == result_id), None)
    if existing is None:
        document["results"].append(item)
    else:
        item["created_at"] = document["results"][existing].get("created_at", item["created_at"])
        document["results"][existing] = item
    document["selected_result_id"] = result_id
    return document, item


def resolve_result(document: dict, item: dict) -> tuple[Path | None, str]:
    document = validate_project(document)
    root = _project_root(document)
    relative = _relative_record_path(item["record"]["path"])
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return None, "path_escape"
    if not path.is_file():
        return None, "missing"
    if path.stat().st_size != item["record"]["size"] or _sha256(path) != item["record"]["sha256"]:
        return None, "hash_mismatch"
    return path, "available"


class ProjectStore:
    @staticmethod
    def load(path: str | Path) -> dict:
        path = Path(path).expanduser().resolve()
        return validate_project(json.loads(path.read_text(encoding="utf-8")))

    @staticmethod
    def save(document: dict, path: str | Path) -> Path:
        document = validate_project(document)
        path = Path(path).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        except Exception:
            Path(temporary).unlink(missing_ok=True)
            raise
        return path
