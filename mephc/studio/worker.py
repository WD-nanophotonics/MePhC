from __future__ import annotations

import argparse
import json
import os
import time
import traceback
from pathlib import Path

import numpy as np

from .cases import case_root, get_geometry_id, load_case_module, load_config
from .profiles import validate_profile
from .recording import expected_kind, validate_record


def _record_snapshot(root: Path) -> dict[Path, tuple[int, int]]:
    data_root = root / "data"
    if not data_root.is_dir():
        return {}
    result = {}
    for path in data_root.rglob("*.pkl"):
        if ".studio" in path.relative_to(data_root).parts:
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        result[path.resolve()] = (stat.st_mtime_ns, stat.st_size)
    return result


def _common(profile: dict, operation: str) -> tuple[object, object, dict, Path]:
    case_id = profile["case_id"]
    root = case_root(case_id, profile.get("project_root"))
    config = load_config(case_id, profile["geometry"], root)
    module = load_case_module(case_id, operation, root)
    parameters = dict(profile["operations"][operation])
    return config, module, parameters, root


def _data_value(record: dict, name: str, default=None):
    data = record.get("data")
    if isinstance(data, dict):
        return data.get(name, default)
    if hasattr(data, name):
        return getattr(data, name)
    metadata = getattr(data, "metadata", None)
    return metadata.get(name, default) if isinstance(metadata, dict) else default


def run_request(request: dict) -> dict:
    started = time.perf_counter()
    profile = validate_profile(request["profile"])
    operation = request["operation"]
    if operation not in {"band_structure", "berry_curvature", "efs", "frequency_at_k", "mpb_preview"}:
        raise ValueError(f"unsupported operation: {operation}")
    case_id = profile["case_id"]
    root = case_root(case_id, profile.get("project_root"))
    config = load_config(case_id, profile["geometry"], root)

    if operation == "mpb_preview":
        module = load_case_module(case_id, "band_structure", root)
        parameters = profile["operations"]["band_structure"]
        module.preview_unit_cell(
            config,
            resolution=int(parameters["resolution"]),
            numpy_preview=False,
            mpb_preview=True,
            show=True,
            preview_num_bands=1,
        )
        return {"status": "succeeded", "operation": operation, "geometry_id": get_geometry_id(case_id, config)}

    if operation == "frequency_at_k":
        parameters = dict(profile["operations"][operation])
        band = config.make_band(resolution=int(parameters["resolution"]))
        result = band.compute_efs(
            config.build_pattern(),
            k_points=[(float(parameters["kx"]), float(parameters["ky"]))],
            num_bands=int(parameters["num_bands"]),
        )
        return {
            "status": "succeeded",
            "operation": operation,
            "geometry_id": get_geometry_id(case_id, config),
            "k_point": [float(parameters["kx"]), float(parameters["ky"])],
            "freqs": np.asarray(result.freqs[0], dtype=float).tolist(),
            "actual_freqs": np.asarray(result.actual_freqs[0], dtype=float).tolist(),
            "elapsed_seconds": time.perf_counter() - started,
        }

    config, module, parameters, root = _common(profile, operation)
    geometry_id = get_geometry_id(case_id, config)
    before_records = _record_snapshot(root)
    target_band = int(parameters["target_band"]) if operation in {"berry_curvature", "efs"} else None
    num_bands = target_band if target_band is not None else int(parameters["num_bands"])
    common = {
        "resolution": int(parameters["resolution"]),
        "num_bands": num_bands,
        "run_mode": str(parameters.get("run_mode", "auto")),
        "archive": False,
        "reuse_requires_compute_match": True,
        # Record selection belongs exclusively to Studio's Plot action.
        # Compute/auto resolve only their own canonical, metadata-matched
        # record; plot_only follows the same downstream matcher.
        "record_path": None,
        "save": True,
        "save_tmp": True,
        "source_case": str(root),
    }
    if operation == "band_structure":
        record, record_path, temporary = module.compute_band_structure(
            config,
            n_per_segment=int(parameters["n_per_segment"]),
            compute_bc=bool(parameters.get("compute_bc", False)),
            berry_step=float(parameters.get("berry_step", 0.0005)),
            **common,
        )
    elif operation == "berry_curvature":
        kwargs = dict(
            grid_n=int(parameters["grid_n"]),
            step=float(parameters["step"]),
            band_index=target_band - 1,
            **common,
        )
        if case_id == "triangular":
            kwargs.update(shrinking=float(parameters["shrinking"]), symmetry_mode="auto")
            record, record_path, temporary = module.compute_berry_curvature(config, **kwargs)
        else:
            record, record_path, temporary = module.compute_berry_curvature(config, symmetry=None, raw_full_grid=False, **kwargs)
    else:
        kwargs = dict(grid_n=int(parameters["grid_n"]), band_index=target_band - 1, **common)
        if case_id == "triangular":
            kwargs.update(shrinking=float(parameters["shrinking"]), symmetry_mode="auto")
        record, record_path, temporary = module.compute_efs(config, **kwargs)

    validated, validated_path = validate_record(
        record,
        operation,
        expected_geometry_id=geometry_id,
    )
    if record_path is None or validated_path is not None:
        resolved_path = validated_path
    else:
        resolved_path = Path(record_path).resolve()
        validate_record(resolved_path, operation, expected_geometry_id=geometry_id)
    if resolved_path is None or not resolved_path.is_file():
        raise RuntimeError(f"{operation} succeeded without a durable record path")
    after_stat = resolved_path.stat()
    after_signature = (after_stat.st_mtime_ns, after_stat.st_size)
    disposition = "reused" if before_records.get(resolved_path) == after_signature else "computed"
    if str(parameters.get("run_mode", "auto")) == "compute":
        disposition = "computed"

    k_points = _data_value(validated, "k_points")
    return {
        "status": "succeeded",
        "operation": operation,
        "record_kind": expected_kind(operation),
        "geometry_id": validated["geometry_id"],
        "record_path": str(resolved_path),
        "temporary_record_path": str(temporary) if temporary is not None else None,
        "execution_disposition": disposition,
        "target_band": target_band,
        "sampling_domain": validated.get("task_params", {}).get("domain", _data_value(validated, "domain", "unspecified")),
        "symmetry_used": validated.get("task_params", {}).get("symmetry", _data_value(validated, "symmetry", "unspecified")),
        "sample_count": int(len(k_points)) if k_points is not None else None,
        "elapsed_seconds": time.perf_counter() - started,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one MePhC Studio calculation.")
    parser.add_argument("--request", required=True)
    parser.add_argument("--result", required=True)
    args = parser.parse_args(argv)
    result_path = Path(args.result)
    try:
        request = json.loads(Path(args.request).read_text(encoding="utf-8"))
        result = run_request(request)
        return_code = 0
    except Exception as exc:
        traceback.print_exc()
        result = {"status": "failed", "error_type": type(exc).__name__, "error": str(exc)}
        return_code = 1
    result_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = result_path.with_suffix(result_path.suffix + ".tmp")
    temporary.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, result_path)
    print(json.dumps(result, sort_keys=True), flush=True)
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
