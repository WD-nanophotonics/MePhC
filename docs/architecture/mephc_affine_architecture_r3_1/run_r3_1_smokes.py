"""Replay the four accepted non-identity TriLatt MPB production smokes.

The driver is intentionally stored inside the R3.1 evidence bundle so the
smoke command does not depend on an untracked temporary file. It writes only
its machine-readable summary below the explicitly supplied output root; all
MePhC/TriLatt record writers are disabled.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np


def _repo_roots() -> tuple[Path, Path]:
    mephc_root = Path(__file__).resolve().parents[3]
    trilatt_root = mephc_root.parent / "TriLatt"
    return mephc_root, trilatt_root


def _load_production_modules():
    mephc_root, trilatt_root = _repo_roots()
    sys.path.insert(0, str(trilatt_root))
    sys.path.insert(0, str(mephc_root))
    import band_structure
    import berry_curvature
    import config
    import efs
    import frequency_at_k

    return config, band_structure, berry_curvature, efs, frequency_at_k


def _finite(value) -> bool:
    return bool(np.all(np.isfinite(np.asarray(value, dtype=float))))


def _entry(status: str, started: float, parameters: dict, assertions: dict, shape) -> dict:
    return {
        "status": status,
        "duration_seconds": round(time.perf_counter() - started, 6),
        "parameters": parameters,
        "assertions": assertions,
        "shape": list(shape),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-root",
        type=Path,
        required=True,
        help="isolated directory for the smoke summary; no repository records are written",
    )
    parser.add_argument("--resolution", type=int, default=2)
    parser.add_argument("--num-bands", type=int, default=1)
    parser.add_argument("--stretch-factor", type=float, default=1.05)
    parser.add_argument("--stretch-angle-degrees", type=float, default=17.0)
    args = parser.parse_args()
    if args.resolution < 1 or args.num_bands < 1:
        raise ValueError("resolution and num-bands must be positive")
    args.output_root.mkdir(parents=True, exist_ok=True)

    config, band_structure, berry_curvature, efs, frequency_at_k = _load_production_modules()
    config.stretch_factor = args.stretch_factor
    config.stretch_angle_degrees = args.stretch_angle_degrees
    results = {}
    started_all = time.perf_counter()

    started = time.perf_counter()
    band_record, _, _ = band_structure.compute_band_structure(
        config,
        resolution=args.resolution,
        num_bands=args.num_bands,
        n_per_segment=1,
        compute_bc=False,
        run_mode="compute",
        save=False,
        save_tmp=False,
        source_case="r3.1-closure-smoke",
    )
    band_data = band_record["data"]
    band_assertions = {
        "finite_freqs": _finite(band_data["freqs"]),
        "generic_current_bz_path": band_record["task_params"]["path"] == "generic_bz",
        "deformation_metadata": band_record["compute_params"]["geometry"]["stretch_factor"] == args.stretch_factor,
        "c3_legacy_disabled": not config.canonical_lattice().supports_legacy("gkm"),
    }
    assert all(band_assertions.values()), band_assertions
    results["band_non_identity_low_resolution"] = _entry(
        "PASS", started,
        {"resolution": args.resolution, "num_bands": args.num_bands, "n_per_segment": 1},
        band_assertions,
        band_data["freqs"].shape,
    )

    started = time.perf_counter()
    berry_record, _, _ = berry_curvature.compute_berry_curvature(
        config,
        resolution=args.resolution,
        num_bands=args.num_bands,
        grid_n=2,
        shrinking=0.01,
        step=0.01,
        band_index=None,
        symmetry_mode="auto",
        run_mode="compute",
        save=False,
        save_tmp=False,
        source_case="r3.1-closure-smoke",
    )
    berry_data = berry_record["data"]
    berry_assertions = {
        "finite_bcs": _finite(berry_data["bcs"]),
        "current_full_bz_domain": berry_record["task_params"]["domain"] == "first_bz",
        "deformation_metadata": berry_data["lattice"]["current_symmetry"] == "generic_affine",
        "c3_reduction_disabled": berry_record["task_params"]["symmetry"] != "c3",
    }
    assert all(berry_assertions.values()), berry_assertions
    results["berry_non_identity_low_resolution"] = _entry(
        "PASS", started,
        {"resolution": args.resolution, "num_bands": args.num_bands, "grid_n": 2, "step": 0.01},
        berry_assertions,
        np.asarray(berry_data["bcs"]).shape,
    )

    started = time.perf_counter()
    efs_record, _, _ = efs.compute_efs(
        config,
        resolution=args.resolution,
        num_bands=args.num_bands,
        grid_n=2,
        shrinking=0.01,
        band_index=0,
        symmetry_mode="auto",
        run_mode="compute",
        save=False,
        save_tmp=False,
        source_case="r3.1-closure-smoke",
    )
    efs_data = efs_record["data"]
    efs_assertions = {
        "finite_freqs": _finite(efs_data.freqs),
        "current_full_bz_domain": efs_record["task_params"]["domain"] == "first_bz",
        "deformation_metadata": efs_data.metadata["lattice"]["current_symmetry"] == "generic_affine",
        "c3_reduction_disabled": efs_record["task_params"]["symmetry"] != "c3",
    }
    assert all(efs_assertions.values()), efs_assertions
    results["efs_non_identity_low_resolution"] = _entry(
        "PASS", started,
        {"resolution": args.resolution, "num_bands": args.num_bands, "grid_n": 2},
        efs_assertions,
        efs_data.freqs.shape,
    )

    started = time.perf_counter()
    landmark_result = frequency_at_k.compute_k_frequencies(
        config,
        resolution=args.resolution,
        num_bands=args.num_bands,
    )
    frequency_assertions = {
        "finite_freqs": _finite(landmark_result["freqs"]),
        "tracked_K1": landmark_result["landmark_kind"] == "tracked_K1",
        "landmark_metadata": landmark_result["display_label"] == "tracked_K1",
    }
    assert all(frequency_assertions.values()), frequency_assertions
    results["frequency_at_tracked_K1_non_identity_low_resolution"] = _entry(
        "PASS", started,
        {"resolution": args.resolution, "num_bands": args.num_bands},
        frequency_assertions,
        np.asarray(landmark_result["freqs"]).shape,
    )

    summary = {
        "status": "PASS",
        "parameters": {
            "resolution": args.resolution,
            "num_bands": args.num_bands,
            "stretch_factor": args.stretch_factor,
            "stretch_angle_degrees": args.stretch_angle_degrees,
            "record_writes": False,
            "output_root": str(args.output_root),
        },
        "total_duration_seconds": round(time.perf_counter() - started_all, 6),
        "entries": results,
    }
    summary_path = args.output_root / "r3_1_smoke_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
