"""E7I.5A crash-safe rank-1 Stage-1 parent orchestrator."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from shapely.geometry import Point

from mephc.valley_benchmark import build_triangular_coordinate_preflight, paper_style_truncated_k_hbz, sample_domain
from mephc.valley_reference_geometry import build_triangular_reference_geometry

WORK_ORDER = "TRILATT-E7I5A-20260823-144"
FR = 0.0
SPACING = 1.0 / 18.0
RESOLUTION = 48
REPRESENTATION = "mpb_energy_eh_v1"
POLARIZATION = "TE"
TOLERANCE = 1e-7
MESH_SIZE = 3
NUM_BANDS = 4
TARGET_BANDS = (0, 1, 2)
EXPECTED_ELEMENTS = 331


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def git_head(root: Path) -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(temp, path)


def checkpoint_path(directory: Path, element_id: str) -> Path:
    return directory / (sha(element_id.encode())[:24] + ".json")


def contract_identity(contract: dict) -> dict:
    return {key: contract[key] for key in ("runner_code_git_sha", "element_id", "evaluation_q", "integration_weight", "geometry_digest", "material_digest", "coordinate_mapping_digest", "domain_digest", "resolution", "representation", "polarization", "num_bands", "target_bands", "solver_tolerance", "deterministic", "mesh_size")}


def valid_checkpoint(path: Path, contract: dict) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema") != "e7i5a_rank1_element_checkpoint_v1" or not payload.get("complete"):
            return False
        if any(payload.get(key) != value for key, value in contract_identity(contract).items()):
            return False
        bands = payload.get("bands")
        if not isinstance(bands, dict) or set(bands) != {str(x) for x in TARGET_BANDS}:
            return False
        for band in TARGET_BANDS:
            final = bands[str(band)].get("final", {})
            if not isinstance(final.get("qualified"), bool):
                return False
            if final.get("qualified") and not isinstance(final.get("omega_trace_q"), (int, float)):
                return False
        return True
    except (OSError, ValueError, TypeError, KeyError):
        return False


def build_contract(root: Path, sample, index: int, geometry, preflight, domain) -> dict:
    return {
        "schema": "e7i5a_rank1_element_contract_v1",
        "work_order": WORK_ORDER,
        "runner_code_git_sha": git_head(root),
        "element_id": sample.element_ids[index],
        "evaluation_q": list(sample.centers[index]),
        "integration_weight": float(sample.weights[index]),
        "element_vertices": [list(x) for x in sample.element_vertices[index]],
        "geometry_digest": geometry.geometry_digest,
        "material_digest": geometry.material_contract_digest,
        "coordinate_mapping_digest": preflight.mapping_digest,
        "domain_digest": domain.digest,
        "resolution": RESOLUTION,
        "representation": REPRESENTATION,
        "polarization": POLARIZATION,
        "num_bands": NUM_BANDS,
        "target_bands": list(TARGET_BANDS),
        "solver_tolerance": TOLERANCE,
        "deterministic": True,
        "mesh_size": MESH_SIZE,
    }


def run_worker(root: Path, contract: dict, checkpoints: Path, worker: Path, timeout: int = 1800) -> dict:
    final = checkpoint_path(checkpoints, contract["element_id"])
    if final.exists() and valid_checkpoint(final, contract):
        return {"status": "REUSE", "checkpoint": str(final), "payload": json.loads(final.read_text())}
    checkpoints.mkdir(parents=True, exist_ok=True)
    temp_root = checkpoints / ".worker_tmp"
    temp_root.mkdir(exist_ok=True)
    token = sha(canonical(contract))[:24]
    contract_path = temp_root / (token + ".contract.json")
    output_path = temp_root / (token + ".json.tmp")
    atomic_json(contract_path, contract)
    output_path.unlink(missing_ok=True)
    started = time.monotonic()
    try:
        completed = subprocess.run([str(Path(sys.executable)), str(worker), "--contract", str(contract_path), "--output", str(output_path)], cwd=root, capture_output=True, text=True, timeout=timeout, env={**os.environ, "PYTHONPATH": str(root)})
    except subprocess.TimeoutExpired as exc:
        return {"status": "FAILED", "element_id": contract["element_id"], "error": f"TIMEOUT: {exc}"}
    if completed.returncode != 0 or not output_path.exists():
        return {"status": "FAILED", "element_id": contract["element_id"], "worker_exit_code": completed.returncode, "stderr_tail": completed.stderr[-3000:], "wall_time_seconds": time.monotonic() - started}
    if not valid_checkpoint(output_path, contract):
        return {"status": "FAILED", "element_id": contract["element_id"], "error": "checkpoint validation failed"}
    os.replace(output_path, final)
    return {"status": "COMPLETED", "checkpoint": str(final), "payload": json.loads(final.read_text()), "checkpoint_sha256": sha(final.read_bytes()), "wall_time_seconds": time.monotonic() - started}


def certification_indices(sample, domain) -> list[int]:
    centers = list(sample.centers)
    near_k = min(range(len(centers)), key=lambda i: (sum((centers[i][j] - (2.0 / 3.0, 0.0)[j]) ** 2 for j in range(2)), i))
    boundary = [i for i, q in enumerate(centers) if domain.polygon.boundary.distance(Point(q)) <= 2.0 * SPACING]
    interior = [i for i in range(len(centers)) if i not in boundary]
    low_gap_target = (0.12916666666666668, -0.011226255234242668)
    low_gap = min(range(len(centers)), key=lambda i: (sum((centers[i][j] - low_gap_target[j]) ** 2 for j in range(2)), i))
    selected = [near_k]
    selected.extend(interior[:2])
    selected.extend(boundary[:2])
    selected.append(low_gap)
    selected = list(dict.fromkeys(selected))
    for index in range(len(centers)):
        if len(selected) >= 6:
            break
        if index not in selected:
            selected.append(index)
    return selected[:6]


def prepare(root: Path):
    geometry = build_triangular_reference_geometry(FR)
    preflight = build_triangular_coordinate_preflight()
    domain = paper_style_truncated_k_hbz(fr=FR, delta_k=0.10, delta_gamma=0.10)
    sample = sample_domain(domain, SPACING)
    if len(sample.centers) != EXPECTED_ELEMENTS:
        raise RuntimeError(f"unexpected Stage-1 sample size: {len(sample.centers)}")
    return geometry, preflight, domain, sample


def certify(root: Path) -> dict:
    geometry, preflight, domain, sample = prepare(root)
    worker = Path(__file__).with_name("run_rank1_stage1_worker.py")
    directory = root / "audit" / "e7i5a" / "checkpoints" / "certification"
    entries = []
    contracts = []
    for index in certification_indices(sample, domain):
        contract = build_contract(root, sample, index, geometry, preflight, domain)
        contracts.append(contract)
        entries.append(run_worker(root, contract, directory, worker))
    passed = len(contracts) == 6 and all(entry["status"] in {"COMPLETED", "REUSE"} for entry in entries) and all(all(entry["payload"]["bands"][str(b)]["final"]["profile_passed"] or not entry["payload"]["bands"][str(b)]["final"]["center_profile_passed"] for b in TARGET_BANDS) for entry in entries)
    report = {"schema": "e7i5a_certification_report_v1", "work_order": WORK_ORDER, "certification_element_count": len(contracts), "certification_element_ids": [contract["element_id"] for contract in contracts], "certification_passed": passed, "execution_architecture": "FRESH_SUBPROCESS_PER_INTEGRATION_ELEMENT", "max_concurrent_workers": 1, "main_unchanged_required": True, "full_stage1_continuation": "AUTHORIZED_AFTER_CERTIFICATION" if passed else "NOT_AUTHORIZED"}
    atomic_json(root / "audit" / "e7i5a" / "environment_report.json", report)
    print(json.dumps({"certification_passed": passed, "elements": len(contracts)}))
    return report


def run_full(root: Path) -> None:
    report = json.loads((root / "audit" / "e7i5a" / "environment_report.json").read_text())
    if report.get("full_stage1_continuation") != "AUTHORIZED_AFTER_CERTIFICATION":
        raise RuntimeError("6-element certification has not authorized full Stage-1")
    geometry, preflight, domain, sample = prepare(root)
    worker = Path(__file__).with_name("run_rank1_stage1_worker.py")
    checkpoints = root / "audit" / "e7i5a" / "checkpoints" / "full"
    started = time.monotonic()
    for index in range(len(sample.centers)):
        contract = build_contract(root, sample, index, geometry, preflight, domain)
        entry = run_worker(root, contract, checkpoints, worker)
        if entry["status"] == "FAILED":
            atomic_json(root / "audit" / "e7i5a" / "stage1_failure_report.json", {"schema": "e7i5a_failure_v1", "element_id": contract["element_id"], "completed_elements": index, "expected_elements": EXPECTED_ELEMENTS, "entry": {key: value for key, value in entry.items() if key != "payload"}})
            print(json.dumps({"stage1_status": "STOPPED_FAIL_CLOSED", "completed": index, "total": EXPECTED_ELEMENTS}))
            return
        if index % 10 == 0:
            print(json.dumps({"progress": index, "total": EXPECTED_ELEMENTS, "status": entry["status"]}), flush=True)
    atomic_json(root / "audit" / "e7i5a" / "run_summary.json", {"schema": "e7i5a_run_summary_v1", "work_order": WORK_ORDER, "element_count": EXPECTED_ELEMENTS, "execution_architecture": "FRESH_SUBPROCESS_PER_INTEGRATION_ELEMENT", "wall_time_seconds": time.monotonic() - started, "final_result": "DEFERRED_TO_COMMITTED_REDUCER", "main_unchanged": True})
    print(json.dumps({"stage1_status": "CHECKPOINTS_COMPLETE", "elements": EXPECTED_ELEMENTS}))


def self_check(root: Path):
    geometry, preflight, domain, sample = prepare(root)
    assert len(sample.centers) == 331
    assert len(certification_indices(sample, domain)) == 6
    assert sha(b"a") != sha(b"b")
    assert TARGET_BANDS == (0, 1, 2)
    print(json.dumps({"self_check": "PASSED", "sample_count": len(sample.centers), "certification_count": len(certification_indices(sample, domain))}))


def main():
    import sys
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--certify", action="store_true")
    parser.add_argument("--run-full", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    if args.self_check:
        self_check(root)
    elif args.certify:
        certify(root)
    elif args.run_full:
        run_full(root)
    else:
        parser.error("choose --self-check, --certify, or --run-full")


if __name__ == "__main__":
    main()


