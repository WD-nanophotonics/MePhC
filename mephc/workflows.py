"""Shared record lookup and output helpers for lattice projects."""

from pathlib import Path

from .records import (
    canonical_record_path,
    data_dir,
    find_matching_record,
    load_record,
    make_record_name,
    save_record,
    tmp_dir,
    update_archive_manifest,
)


def resolve_record(
    project_root,
    geometry_id,
    kind,
    *,
    task_params,
    compute_params,
    run_mode="auto",
    record_path=None,
    reuse_requires_compute_match=True,
):
    """Resolve an explicit, reusable, or missing record.

    ``record_path`` has highest priority. ``auto`` and ``plot_only`` search the
    canonical path; ``plot_only`` raises ``FileNotFoundError`` when it is
    absent, while ``auto`` returns ``(None, None)`` so the caller can compute.
    ``compute_params`` are matched only when the corresponding flag is true.
    """
    project_root = Path(project_root)
    if record_path is not None:
        path = Path(record_path)
        return load_record(path), path
    if run_mode not in {"auto", "compute", "plot_only"}:
        raise ValueError("run_mode must be 'auto', 'compute', or 'plot_only'.")
    if run_mode in {"auto", "plot_only"}:
        record, path = find_matching_record(
            project_root,
            geometry_id,
            kind,
            task_params=task_params,
            compute_params=compute_params,
            require_compute_match=reuse_requires_compute_match,
        )
        if record is not None:
            return record, path
        if run_mode == "plot_only":
            expected = canonical_record_path(project_root, geometry_id, kind, task_params)
            raise FileNotFoundError(
                f"No matching {kind!r} record found. Expected canonical path: {expected}"
            )
    return None, None


def save_record_outputs(
    project_root,
    geometry_id,
    kind,
    task_params,
    record,
    *,
    archive=False,
    archive_params=None,
    save=True,
    save_tmp=True,
    tmp_name=None,
):
    """Write canonical, optional archive, and optional temporary outputs.

    Returns ``(canonical_path, tmp_path_or_none)``. Only canonical and archive
    records update ``archive_manifest.json``; temporary records are deliberately
    excluded from the tracked audit index.
    """
    project_root = Path(project_root)
    canonical_path = canonical_record_path(project_root, geometry_id, kind, task_params)
    tmp_path = tmp_dir(project_root) / (tmp_name or f"{kind}_latest.pkl")
    if save:
        save_record(record, canonical_path)
        update_archive_manifest(project_root, canonical_path, record)
    if archive:
        params = dict(archive_params or {})
        archive_name = make_record_name(kind, created_at=record["created_at"], **params)
        archive_path = data_dir(project_root, geometry_id) / archive_name
        save_record(record, archive_path)
        update_archive_manifest(project_root, archive_path, record)
    if save_tmp:
        save_record(record, tmp_path)
    return canonical_path, tmp_path if save_tmp else None
