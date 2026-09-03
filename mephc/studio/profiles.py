from __future__ import annotations

import json
import os
import re
import tempfile
from copy import deepcopy
from pathlib import Path

from .plot_style import normalize_plot_style, validate_plot_style

PROFILE_SCHEMA = "mephc-studio-profile-v3"
PREVIOUS_PROFILE_SCHEMA = "mephc-studio-profile-v2"
LEGACY_PROFILE_SCHEMA = "mephc-studio-profile-v1"
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


def default_profile_root() -> Path:
    override = os.environ.get("MEPHC_STUDIO_PROFILE_ROOT")
    return Path(override).expanduser() if override else Path.home() / ".config" / "mephc-studio" / "profiles"


def migrate_profile(profile: dict) -> dict:
    if not isinstance(profile, dict):
        raise ValueError("profile must be an object")
    profile = deepcopy(profile)
    schema = profile.get("schema")
    if schema not in {PROFILE_SCHEMA, PREVIOUS_PROFILE_SCHEMA, LEGACY_PROFILE_SCHEMA}:
        raise ValueError(f"profile schema must be {PROFILE_SCHEMA!r}")
    old_plot = deepcopy(profile.get("plot")) if isinstance(profile.get("plot"), dict) else {}
    old_display_band = int(old_plot.get("band_index", 0)) + 1 if "band_index" in old_plot else 1
    profile["schema"] = PROFILE_SCHEMA
    profile["plot"] = normalize_plot_style(profile.get("plot"))
    operations = profile.setdefault("operations", {})
    if isinstance(operations, dict):
        for operation in ("berry_curvature", "efs"):
            values = operations.setdefault(operation, {})
            if not isinstance(values, dict):
                continue
            if "target_band" not in values:
                values["target_band"] = int(values.get("band_index", old_display_band - 1)) + 1
            values.pop("band_index", None)
            values.pop("num_bands", None)
            if schema != PROFILE_SCHEMA:
                shrinking = values.get("shrinking", 0.0)
                try:
                    shrinking = float(shrinking)
                except (TypeError, ValueError):
                    shrinking = 0.0
                values["shrinking"] = shrinking if 0 <= shrinking < 2.0 / 3.0 else 0.0
    preview = profile.setdefault("preview", {})
    if "span" not in preview:
        preview["span"] = float(max(preview.pop("cells_x", 7), preview.pop("cells_y", 5)))
    else:
        preview.pop("cells_x", None)
        preview.pop("cells_y", None)
    ui = profile.setdefault("ui", {})
    ui.setdefault("plot_after_run", True)
    return profile


def validate_profile(profile: dict, *, expected_case: str | None = None) -> dict:
    profile = migrate_profile(profile)
    case_id = profile.get("case_id")
    if case_id not in {"triangular", "square"}:
        raise ValueError("case_id must be 'triangular' or 'square'")
    if expected_case is not None and case_id != expected_case:
        raise ValueError(f"profile belongs to {case_id}, not {expected_case}")
    name = profile.get("name")
    if not isinstance(name, str) or not _SAFE_NAME.fullmatch(name):
        raise ValueError("profile name may contain only letters, digits, '.', '_' and '-'")
    for key in ("geometry", "operations", "plot", "preview", "ui"):
        if not isinstance(profile.get(key), dict):
            raise ValueError(f"{key} must be an object")
    span = profile["preview"].get("span")
    if isinstance(span, bool) or not isinstance(span, (int, float)) or not 1 <= float(span) <= 31:
        raise ValueError("preview span must be a number from 1 to 31")
    profile["preview"]["span"] = float(span)
    if not isinstance(profile["ui"].get("plot_after_run"), bool):
        raise ValueError("ui plot_after_run must be a boolean")
    for operation in ("berry_curvature", "efs"):
        values = profile["operations"].get(operation)
        if not isinstance(values, dict):
            raise ValueError(f"operations.{operation} must be an object")
        target_band = values.get("target_band")
        if isinstance(target_band, bool) or not isinstance(target_band, int) or target_band < 1:
            raise ValueError(f"{operation} target_band must be an integer >= 1")
        shrinking = values.get("shrinking", 0.0)
        if not isinstance(shrinking, (int, float)) or isinstance(shrinking, bool) or not 0 <= float(shrinking) < 2.0 / 3.0:
            raise ValueError(f"{operation} boundary inset must satisfy 0 <= value < 2/3")
    profile["plot"] = validate_plot_style(profile["plot"])
    return profile


class ProfileStore:
    def __init__(self, root: str | Path | None = None):
        self.root = Path(root) if root is not None else default_profile_root()

    def path_for(self, case_id: str, name: str) -> Path:
        if case_id not in {"triangular", "square"}:
            raise ValueError("case_id must be 'triangular' or 'square'")
        if not isinstance(name, str) or not _SAFE_NAME.fullmatch(name):
            raise ValueError("profile name may contain only letters, digits, '.', '_' and '-'")
        case_root = (self.root / case_id).resolve()
        path = (case_root / f"{name}.json").resolve()
        if path.parent != case_root:
            raise ValueError("profile path escapes its case directory")
        return path

    def list(self, case_id: str) -> list[str]:
        case_root = self.root / case_id
        if not case_root.exists():
            return []
        return sorted(path.stem for path in case_root.glob("*.json") if _SAFE_NAME.fullmatch(path.stem))

    def load(self, case_id: str, name: str) -> dict:
        path = self.path_for(case_id, name)
        return validate_profile(json.loads(path.read_text(encoding="utf-8")), expected_case=case_id)

    def save(self, profile: dict) -> Path:
        profile = validate_profile(profile)
        path = self.path_for(profile["case_id"], profile["name"])
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(profile, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
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

    def import_file(self, source: str | Path) -> dict:
        source = Path(source)
        profile = validate_profile(json.loads(source.read_text(encoding="utf-8")))
        self.save(profile)
        return profile

    @staticmethod
    def export_file(profile: dict, destination: str | Path) -> Path:
        profile = validate_profile(profile)
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(profile, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
        return destination
