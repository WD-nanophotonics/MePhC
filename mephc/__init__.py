"""Generic helpers for building Meep/MPB photonic crystal models."""

__all__ = [
    "Band",
    "BerryCurvatureCalculator",
    "EFSInterpolator",
    "EFSResult",
    "HighSymmetryPath",
    "Lattice",
    "plot_band_path",
    "plot_scalar_field",
    "save_record",
    "load_record",
    "archive_manifest_path",
    "update_archive_manifest",
    "resolve_record",
    "save_record_outputs",
    "preview_pattern",
    "preview_mpb_dielectric",
]


def __getattr__(name):
    if name == "Band":
        from .band import Band

        return Band
    if name == "BerryCurvatureCalculator":
        from .berry import BerryCurvatureCalculator

        return BerryCurvatureCalculator
    if name == "EFSInterpolator":
        from .efs import EFSInterpolator

        return EFSInterpolator
    if name == "EFSResult":
        from .efs import EFSResult

        return EFSResult
    if name == "HighSymmetryPath":
        from .kspace import HighSymmetryPath

        return HighSymmetryPath
    if name == "Lattice":
        from .lattice import Lattice

        return Lattice
    if name == "plot_band_path":
        from .plotting import plot_band_path

        return plot_band_path
    if name == "plot_scalar_field":
        from .plotting import plot_scalar_field

        return plot_scalar_field
    if name == "save_record":
        from .records import save_record

        return save_record
    if name == "load_record":
        from .records import load_record

        return load_record
    if name == "archive_manifest_path":
        from .records import archive_manifest_path

        return archive_manifest_path
    if name == "update_archive_manifest":
        from .records import update_archive_manifest

        return update_archive_manifest
    if name == "resolve_record":
        from .workflows import resolve_record

        return resolve_record
    if name == "save_record_outputs":
        from .workflows import save_record_outputs

        return save_record_outputs
    if name == "preview_pattern":
        from .preview import preview_pattern

        return preview_pattern
    if name == "preview_mpb_dielectric":
        from .preview import preview_mpb_dielectric

        return preview_mpb_dielectric
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
