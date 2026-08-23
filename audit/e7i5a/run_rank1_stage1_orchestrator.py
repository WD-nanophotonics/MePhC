"""E7I.5A.C1 crash-safe rank-1 Stage-1 orchestrator."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from shapely.geometry import Point

from mephc.valley_benchmark import (
    build_triangular_coordinate_preflight,
    paper_style_truncated_k_hbz,
    sample_domain,
)
from mephc.valley_reference_geometry import build_triangular_reference_geometry

WORK_ORDER = "TRILATT-E7I5A-C1-20260823-146"
FR = 0.0
SPACING = 1.0 / 18.0
RESOLUTION = 48
R64_RESOLUTION = 64
REPRESENTATION = "mpb_energy_eh_v1"
POLARIZATION = "TE"
TOLERANCE = 1e-7
MESH_SIZE = 3
NUM_BANDS = 4
TARGET_BANDS = (0, 1, 2)
EXPECTED_ELEMENTS = 331
CHECKPOINT_SCHEMA_VERSION = "e7i5a_rank1_element_checkpoint_c1_v1"
PRIMARY_DELTAS = (1.0 / 36.0, 1.0 / 72.0, 1.0 / 144.0)
TRANSPORT_THRESHOLDS = {
    "min_singular_value": 0.9,
    "max_principal_angle": 0.45,
    "max_projector_distance": 0.3,
    "min_external_gap": 0.0,
}
RANK1_PROFILE = {
    "low_gap_threshold": 0.05,
    "relative_gap_min": 0.01,
    "stability_ratio_min": 10.0,
}


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def git_head(root: Path) -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()


def source_sha(path: Path) -> str:
    return sha(path.read_bytes())


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + chr(10), encoding="utf-8")
    os.replace(temp, path)


def checkpoint_path(directory: Path, element_id: str) -> Path:
    return directory / (sha(element_id.encode())[:24] + ".json")


def scientific_contract(geometry, preflight, domain) -> dict:
    return {
        "fr": FR,
        "geometry_digest": geometry.geometry_digest,
        "material_digest": geometry.material_contract_digest,
        "coordinate_mapping_digest": preflight.mapping_digest,
        "domain_digest": domain.digest,
        "integration_grid_spacing": SPACING,
        "resolution": RESOLUTION,
        "r64_resolution": R64_RESOLUTION,
        "representation": REPRESENTATION,
        "polarization": POLARIZATION,
        "num_bands": NUM_BANDS,
        "target_bands": list(TARGET_BANDS),
        "solver_tolerance": TOLERANCE,
        "deterministic": True,
        "mesh_size": MESH_SIZE,
        "primary_delta_ladder": list(PRIMARY_DELTAS),
        "rank1_profile": RANK1_PROFILE,
        "transport_thresholds": TRANSPORT_THRESHOLDS,
        "checkpoint_schema_version": CHECKPOINT_SCHEMA_VERSION,
    }


def calculation_bundle_sha(worker_source_sha256: str, scientific_contract_sha256: str) -> str:
    return sha(canonical({
        "worker_source_sha256": worker_source_sha256,
        "scientific_contract_sha256": scientific_contract_sha256,
        "checkpoint_schema_version": CHECKPOINT_SCHEMA_VERSION,
    }))


def contract_identity(contract: dict) -> dict:
    keys = (
        "checkpoint_schema_version",
        "worker_source_sha256",
        "scientific_contract_sha256",
        "calculation_bundle_sha256",
        "element_id",
        "evaluation_q",
        "integration_weight",
        "geometry_digest",
        "material_digest",
        "coordinate_mapping_digest",
        "domain_digest",
        "resolution",
        "representation",
        "polarization",
        "num_bands",
        "target_bands",
        "solver_tolerance",
        "deterministic",
        "mesh_size",
    )
    return {key: contract[key] for key in keys}


def result_invariants(final: dict) -> bool:
    qualified = final.get("qualified")
    omega = final.get("omega_trace_q")
    if not isinstance(qualified, bool):
        return False
    if qualified != isinstance(omega, (int, float)):
        return False
    fully_qualified = (
        final.get("profile_passed") is True
        and final.get("reference_profile_passed") is True
        and final.get("path_status") == "PATH_SINGLE_BAND_QUALIFIED"
        and final.get("wilson_status") == "WILSON_LOOP_QUALIFIED"
        and final.get("boundary_status") == "PLAQUETTE_BOUNDARY_SINGLE_BAND_QUALIFIED"
        and final.get("interior_status") == "PLAQUETTE_INTERIOR_SINGLE_BAND_QUALIFIED"
        and (
            final.get("refinement") is None
            or final["refinement"].get("status") == "PLAQUETTE_REFINEMENT_SINGLE_BAND_QUALIFIED"
        )
    )
    return not fully_qualified or qualified


def valid_checkpoint(path: Path, contract: dict) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema") != CHECKPOINT_SCHEMA_VERSION or not payload.get("complete"):
            return False
        if any(payload.get(key) != value for key, value in contract_identity(contract).items()):
            return False
        bands = payload.get("bands")
        if not isinstance(bands, dict) or set(bands) != {str(x) for x in TARGET_BANDS}:
            return False
        for band in TARGET_BANDS:
            final = bands[str(band)].get("final", {})
            if not result_invariants(final):
                return False
        return True
    except (OSError, ValueError, TypeError, KeyError):
        return False


def build_contract(root: Path, sample, index: int, geometry, preflight, domain, worker: Path) -> dict:
    scientific = scientific_contract(geometry, preflight, domain)
    worker_sha = source_sha(worker)
    scientific_sha = sha(canonical(scientific))
    return {
        "schema": "e7i5a_rank1_element_contract_c1_v1",
        "work_order": WORK_ORDER,
        "checkpoint_schema_version": CHECKPOINT_SCHEMA_VERSION,
        "worker_source_sha256": worker_sha,
        "worker_code_git_sha": git_head(root),
        "scientific_contract_sha256": scientific_sha,
        "calculation_bundle_sha256": calculation_bundle_sha(worker_sha, scientific_sha),
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
        return {"status": "REUSE", "checkpoint": str(final), "payload": json.loads(final.read_text(encoding="utf-8"))}
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
        completed = subprocess.run(
            [str(Path(sys.executable)), str(worker), "--contract", str(contract_path), "--output", str(output_path)],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "PYTHONPATH": str(root)},
        )
    except subprocess.TimeoutExpired as exc:
        return {"status": "FAILED", "element_id": contract["element_id"], "error": f"TIMEOUT: {exc}"}
    if completed.returncode != 0 or not output_path.exists():
        return {
            "status": "FAILED",
            "element_id": contract["element_id"],
            "worker_exit_code": completed.returncode,
            "stderr_tail": completed.stderr[-3000:],
            "wall_time_seconds": time.monotonic() - started,
        }
    if not valid_checkpoint(output_path, contract):
        return {"status": "FAILED", "element_id": contract["element_id"], "error": "checkpoint validation failed"}
    os.replace(output_path, final)
    return {
        "status": "COMPLETED",
        "checkpoint": str(final),
        "payload": json.loads(final.read_text(encoding="utf-8")),
        "checkpoint_sha256": sha(final.read_bytes()),
        "wall_time_seconds": time.monotonic() - started,
    }


def nearest_index(centers, target, candidates=None) -> int:
    pool = list(range(len(centers))) if candidates is None else list(candidates)
    return min(pool, key=lambda i: (sum((float(centers[i][j]) - float(target[j])) ** 2 for j in range(2)), i))


def nearest_available(centers, target, used, candidates=None) -> int:
    pool = list(range(len(centers))) if candidates is None else list(candidates)
    ordered = sorted(pool, key=lambda i: (sum((float(centers[i][j]) - float(target[j])) ** 2 for j in range(2)), i))
    return next(index for index in ordered if index not in used)

def certification_candidate_pool(sample, domain) -> list[dict]:
    centers = list(sample.centers)
    boundary = sorted(
        (i for i, q in enumerate(centers) if domain.polygon.boundary.distance(Point(q)) <= 2.0 * SPACING),
        key=lambda i: i,
    )
    interior = sorted(
        (i for i, q in enumerate(centers) if domain.polygon.boundary.distance(Point(q)) > 2.0 * SPACING),
        key=lambda i: i,
    )
    gamma_boundary = [i for i in boundary if sum(float(x) ** 2 for x in centers[i]) <= 0.16 ** 2]
    outer_boundary = [i for i in boundary if i not in gamma_boundary]
    low_gap_target = (0.12916666666666668, -0.011226255234242668)
    entries: list[dict] = []
    used: set[int] = set()

    def add(label: str, index: int) -> None:
        if index not in used:
            entries.append({"label": label, "index": index, "element_id": sample.element_ids[index]})
            used.add(index)

    add("near_K", nearest_index(centers, (2.0 / 3.0, 0.0)))
    add("ordinary_interior", nearest_available(centers, (0.50, 0.02), used, interior))
    if outer_boundary:
        add("outer_boundary", next(i for i in sorted(outer_boundary, key=lambda i: (-sum(float(x) ** 2 for x in centers[i]), i)) if i not in used))
    if gamma_boundary:
        add("gamma_exclusion_boundary", nearest_available(centers, (0.0, 0.0), used, gamma_boundary))
    add("historical_low_gap_region", nearest_available(centers, low_gap_target, used))
    symmetry_source = next((i for i in entries if abs(float(centers[i["index"]][1])) > 1e-8), None)
    if symmetry_source is not None:
        source_index = symmetry_source["index"]
        reflected = nearest_available(centers, (centers[source_index][0], -centers[source_index][1]), used)
        add("symmetry_pair_reflection", reflected)
    for index in range(len(centers)):
        if len(entries) >= 12:
            break
        add("deterministic_fill", index)
    return entries[:12]


def prepare(root: Path):
    geometry = build_triangular_reference_geometry(FR)
    preflight = build_triangular_coordinate_preflight()
    domain = paper_style_truncated_k_hbz(fr=FR, delta_k=0.10, delta_gamma=0.10)
    sample = sample_domain(domain, SPACING)
    if len(sample.centers) != EXPECTED_ELEMENTS:
        raise RuntimeError(f"unexpected Stage-1 sample size: {len(sample.centers)}")
    return geometry, preflight, domain, sample


def old_vs_new(old_path: Path, payload: dict) -> dict:
    old = None
    if old_path.exists():
        old_payload = json.loads(old_path.read_text(encoding="utf-8"))
        old = {
            str(band): {
                "final_status": old_payload["bands"][str(band)]["final"].get("path_status"),
                "center_profile_status": old_payload["bands"][str(band)]["final"].get("center_profile_passed"),
                "omega": old_payload["bands"][str(band)]["final"].get("omega_trace_q"),
                "primary_delta": old_payload["bands"][str(band)]["final"].get("local_delta_k"),
            }
            for band in TARGET_BANDS
        }
    new = {
        str(band): {
            "final_status": payload["bands"][str(band)]["final"].get("path_status"),
            "center_profile_status": payload["bands"][str(band)]["final"].get("center_profile_passed"),
            "omega": payload["bands"][str(band)]["final"].get("omega_trace_q"),
            "primary_delta": payload["bands"][str(band)]["final"].get("local_delta_k"),
        }
        for band in TARGET_BANDS
    }
    return {"old_194311_checkpoint": old, "new_c1_checkpoint": new}


def certify(root: Path) -> dict:
    geometry, preflight, domain, sample = prepare(root)
    worker = Path(__file__).with_name("run_rank1_stage1_worker.py")
    directory = root / "audit" / "e7i5a" / "checkpoints" / "certification_c1"
    candidates = certification_candidate_pool(sample, domain)
    entries = []
    qualified_counts = {str(band): 0 for band in TARGET_BANDS}
    comparisons = []
    for candidate in candidates:
        contract = build_contract(root, sample, candidate["index"], geometry, preflight, domain, worker)
        entry = run_worker(root, contract, directory, worker)
        entries.append({"candidate": candidate, "contract": {"worker_source_sha256": contract["worker_source_sha256"], "scientific_contract_sha256": contract["scientific_contract_sha256"], "calculation_bundle_sha256": contract["calculation_bundle_sha256"]}, "entry": {key: value for key, value in entry.items() if key != "payload"}})
        if entry["status"] == "FAILED":
            break
        payload = entry["payload"]
        comparisons.append({
            "candidate": candidate,
            "comparison": old_vs_new(
                root / "audit" / "e7i5a" / "checkpoints" / "full" / checkpoint_path(directory, candidate["element_id"]).name,
                payload,
            ),
        })
        for band in TARGET_BANDS:
            if payload["bands"][str(band)]["final"].get("qualified") is True:
                qualified_counts[str(band)] += 1
        if all(qualified_counts[str(band)] >= 1 for band in TARGET_BANDS):
            break
    pass_condition = (
        entries
        and all(item["entry"]["status"] in {"COMPLETED", "REUSE"} for item in entries)
        and all(qualified_counts[str(band)] >= 1 for band in TARGET_BANDS)
    )
    report = {
        "schema": "e7i5a_c1_certification_report_v1",
        "work_order": WORK_ORDER,
        "candidate_pool": candidates,
        "candidates_attempted": len(entries),
        "qualified_counts": qualified_counts,
        "certification_passed": bool(pass_condition),
        "full_stage1_continuation": "AUTHORIZED_AFTER_CERTIFICATION" if pass_condition else "NOT_AUTHORIZED",
        "calculation_bundle_sha256": None if not entries else entries[0]["contract"]["calculation_bundle_sha256"],
        "comparisons": comparisons,
        "execution_architecture": "FRESH_SUBPROCESS_PER_INTEGRATION_ELEMENT",
        "max_concurrent_workers": 1,
        "main_unchanged_required": True,
    }
    atomic_json(root / "audit" / "e7i5a" / "environment_report_c1.json", report)
    print(json.dumps({
        "certification_passed": bool(pass_condition),
        "candidates_attempted": len(entries),
        "qualified_counts": qualified_counts,
    }))
    return report


def run_full(root: Path) -> None:
    report = json.loads((root / "audit" / "e7i5a" / "environment_report_c1.json").read_text(encoding="utf-8"))
    if report.get("full_stage1_continuation") != "AUTHORIZED_AFTER_CERTIFICATION":
        raise RuntimeError("C1 certification has not authorized full Stage-1")
    geometry, preflight, domain, sample = prepare(root)
    worker = Path(__file__).with_name("run_rank1_stage1_worker.py")
    checkpoints = root / "audit" / "e7i5a" / "checkpoints" / "full_c1"
    started = time.monotonic()
    for index in range(len(sample.centers)):
        contract = build_contract(root, sample, index, geometry, preflight, domain, worker)
        entry = run_worker(root, contract, checkpoints, worker)
        if entry["status"] == "FAILED":
            atomic_json(root / "audit" / "e7i5a" / "stage1_failure_report_c1.json", {
                "schema": "e7i5a_c1_failure_v1",
                "element_id": contract["element_id"],
                "completed_elements": index,
                "expected_elements": EXPECTED_ELEMENTS,
                "entry": {key: value for key, value in entry.items() if key != "payload"},
            })
            print(json.dumps({"stage1_status": "STOPPED_FAIL_CLOSED", "completed": index, "total": EXPECTED_ELEMENTS}))
            return
        if index % 10 == 0:
            print(json.dumps({"progress": index, "total": EXPECTED_ELEMENTS, "status": entry["status"]}), flush=True)
    atomic_json(root / "audit" / "e7i5a" / "run_summary_c1.json", {
        "schema": "e7i5a_c1_run_summary_v1",
        "work_order": WORK_ORDER,
        "element_count": EXPECTED_ELEMENTS,
        "execution_architecture": "FRESH_SUBPROCESS_PER_INTEGRATION_ELEMENT",
        "wall_time_seconds": time.monotonic() - started,
        "final_result": "DEFERRED_TO_COMMITTED_REDUCER",
        "main_unchanged": True,
    })
    print(json.dumps({"stage1_status": "CHECKPOINTS_COMPLETE", "elements": EXPECTED_ELEMENTS}))


def self_check(root: Path):
    geometry, preflight, domain, sample = prepare(root)
    pool = certification_candidate_pool(sample, domain)
    assert len(sample.centers) == EXPECTED_ELEMENTS
    assert 1 <= len(pool) <= 12
    assert len({item["index"] for item in pool}) == len(pool)
    assert TARGET_BANDS == (0, 1, 2)
    assert calculation_bundle_sha("worker-a", "contract-a") != calculation_bundle_sha("worker-b", "contract-a")
    contract = {"worker_code_git_sha": "old", "element_id": "x"}
    assert contract_identity({
        "checkpoint_schema_version": CHECKPOINT_SCHEMA_VERSION,
        "worker_source_sha256": "source",
        "scientific_contract_sha256": "contract",
        "calculation_bundle_sha256": "bundle",
        "element_id": "x",
        "evaluation_q": [0.0, 0.0],
        "integration_weight": 1.0,
        "geometry_digest": "g",
        "material_digest": "m",
        "coordinate_mapping_digest": "c",
        "domain_digest": "d",
        "resolution": 48,
        "representation": REPRESENTATION,
        "polarization": POLARIZATION,
        "num_bands": 4,
        "target_bands": [0, 1, 2],
        "solver_tolerance": TOLERANCE,
        "deterministic": True,
        "mesh_size": MESH_SIZE,
        "worker_code_git_sha": "new",
    })["element_id"] == "x"
    print(json.dumps({
        "self_check": "PASSED",
        "sample_count": len(sample.centers),
        "candidate_count": len(pool),
        "candidate_labels": [item["label"] for item in pool],
    }))


def main():
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