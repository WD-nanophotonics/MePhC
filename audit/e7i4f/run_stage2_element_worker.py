"""One-element E7I.4F Stage-2 worker."""
from __future__ import annotations
import argparse, hashlib, json, os, resource, subprocess, sys, time, traceback
from pathlib import Path

from audit.e7i3c.run_representation_bridge import (
    build_reference_mpb_adapter, build_triangular_coordinate_preflight,
    build_triangular_reference_geometry,
)
from audit.e7i4e.run_complete_stage1_chern import evaluate

FR = 0.0
RES = 48
PRIMARY = 1.0 / 36.0
REPRESENTATION = "mpb_energy_eh_v1"
POLARIZATION = "TE"
TOLERANCE = 1e-7
MESH_SIZE = 3
NUM_BANDS = 4

def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()

def _contract_sha(contract: dict) -> str:
    return _sha(json.dumps(contract, sort_keys=True, separators=(",", ":"), allow_nan=False).encode())

def _git_head(root: Path) -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()

def _compact(value):
    if isinstance(value, dict):
        return {str(k): _compact(v) for k, v in value.items() if k != "solve_records"}
    if isinstance(value, (tuple, list)):
        return [_compact(v) for v in value]
    return value

def _peak_rss_kib() -> int:
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)

def run(contract: dict, output: Path) -> dict:
    root = Path(__file__).resolve().parents[2]
    if contract["runner_code_git_sha"] != _git_head(root):
        raise RuntimeError("runner code SHA does not match contract")
    geometry = build_triangular_reference_geometry(FR)
    preflight = build_triangular_coordinate_preflight()
    adapter = build_reference_mpb_adapter(geometry, preflight)
    identity = {
        "geometry_digest": geometry.geometry_digest,
        "material_digest": geometry.material_contract_digest,
        "coordinate_mapping_digest": preflight.mapping_digest,
        "domain_digest": contract["domain_digest"],
    }
    for key in ("geometry_digest", "material_digest", "coordinate_mapping_digest"):
        if contract[key] != identity[key]:
            raise RuntimeError(f"provenance mismatch: {key}")
    from mephc.valley_benchmark import PhysicalSolveCache
    cache = {}
    identities = PhysicalSolveCache()
    counters = {"raw_requests": 0, "unique_solves": 0, "cache_hits": 0, "solver_failures": 0}
    row = {"element_id": contract["element_id"], "evaluation_q": contract["evaluation_q"], "weight_q2": contract["integration_weight"]}
    attempts = []
    started = time.monotonic()
    final = None
    for delta in (PRIMARY, PRIMARY / 2.0, PRIMARY / 4.0):
        ref_delta = delta / 2.0
        ev = evaluate(row, delta, ref_delta, adapter, preflight, geometry, cache, identities, counters, {})
        attempts.append({
            "primary_delta": delta,
            "reference_delta": ref_delta,
            "qualified": bool(ev["qualified"]),
            "profile_passed": bool(ev["profile_passed"]),
            "refinement_status": None if ev["refinement"] is None else ev["refinement"]["status"],
        })
        final = ev
        if ev["qualified"]:
            break
    result = _compact(final)
    payload = {
        "schema": "e7i4f_element_checkpoint_v1",
        "complete": True,
        "runner_code_git_sha": contract["runner_code_git_sha"],
        "contract_sha256": _contract_sha(contract),
        "element_id": contract["element_id"],
        "evaluation_q": contract["evaluation_q"],
        "integration_weight": contract["integration_weight"],
        "geometry_digest": geometry.geometry_digest,
        "material_digest": geometry.material_contract_digest,
        "coordinate_mapping_digest": preflight.mapping_digest,
        "domain_digest": contract["domain_digest"],
        "resolution": RES,
        "representation": REPRESENTATION,
        "polarization": POLARIZATION,
        "num_bands": NUM_BANDS,
        "solver_tolerance": TOLERANCE,
        "deterministic": True,
        "mesh_size": MESH_SIZE,
        "adaptive_attempts": attempts,
        "result": result,
        "telemetry": {
            "worker_exit_code": 0,
            "worker_peak_rss_kib": _peak_rss_kib(),
            "worker_wall_time_seconds": time.monotonic() - started,
            "worker_solve_requests": counters["raw_requests"],
            "worker_unique_r48_solves": counters["unique_solves"],
            "worker_unique_r64_solves": sum(1 for x in result.get("low_gap_profile_flat", []) if x.get("R64_G34") is not None),
            "solver_failures": counters["solver_failures"],
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    with output.open("wb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    return payload

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        contract = json.loads(Path(args.contract).read_text(encoding="utf-8"))
        run(contract, Path(args.output))
    except BaseException:
        traceback.print_exc()
        raise

if __name__ == "__main__":
    main()
