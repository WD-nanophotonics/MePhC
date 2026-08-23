"""Crash-safe E7I.4F ENV1 parent orchestrator."""
from __future__ import annotations
import argparse, hashlib, json, os, subprocess, sys, tempfile, time
from pathlib import Path
from shapely.geometry import Point
from mephc.valley_benchmark import (
    build_triangular_coordinate_preflight, paper_style_truncated_k_hbz, sample_domain,
)
from mephc.valley_reference_geometry import build_triangular_reference_geometry

WORK_ORDER = "TRILATT-E7I4F-ENV1-20260823-138"
FR = 0.0
SPACING = 1.0 / 36.0
RES = 48
REPRESENTATION = "mpb_energy_eh_v1"
POLARIZATION = "TE"
TOLERANCE = 1e-7
MESH_SIZE = 3
NUM_BANDS = 4

def sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()

def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()

def git_head(root: Path) -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()

def memory_snapshot() -> dict:
    result = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, raw = line.split(":", 1)
        if key in {"MemTotal", "MemAvailable", "SwapTotal", "SwapFree"}:
            result[key + "_kib"] = int(raw.strip().split()[0])
    return result

def oom_count() -> int:
    result = subprocess.run(["dmesg", "-T"], capture_output=True, text=True, check=False)
    return sum("Out of memory: Killed process" in x or "invoked oom-killer" in x for x in result.stdout.splitlines())

def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    raw = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    with tmp.open("wb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)

def checkpoint_path(directory: Path, element_id: str) -> Path:
    return directory / (sha_bytes(element_id.encode())[:24] + ".json")

def expected_identity(contract: dict) -> dict:
    return {key: contract[key] for key in (
        "runner_code_git_sha", "element_id", "evaluation_q", "integration_weight",
        "geometry_digest", "material_digest", "coordinate_mapping_digest", "domain_digest",
        "resolution", "representation", "polarization", "num_bands",
        "solver_tolerance", "deterministic", "mesh_size",
    )}

def valid_checkpoint(path: Path, contract: dict) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema") != "e7i4f_element_checkpoint_v1" or not payload.get("complete"):
            return False
        if any(payload.get(k) != v for k, v in expected_identity(contract).items()):
            return False
        return isinstance(payload.get("result"), dict) and isinstance(payload["result"].get("qualified"), bool)
    except (OSError, ValueError, KeyError, TypeError):
        return False

def build_contract(root: Path, sample, index: int, geometry, preflight, domain) -> dict:
    return {
        "schema": "e7i4f_element_contract_v1",
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
        "resolution": RES,
        "representation": REPRESENTATION,
        "polarization": POLARIZATION,
        "num_bands": NUM_BANDS,
        "solver_tolerance": TOLERANCE,
        "deterministic": True,
        "mesh_size": MESH_SIZE,
    }

def run_element(root: Path, contract: dict, checkpoints: Path, worker: Path, timeout: int = 1200) -> dict:
    final = checkpoint_path(checkpoints, contract["element_id"])
    if final.exists() and valid_checkpoint(final, contract):
        return {"status": "REUSE", "checkpoint": str(final), "payload": json.loads(final.read_text())}
    checkpoints.mkdir(parents=True, exist_ok=True)
    temp_root = checkpoints / ".worker_tmp"
    temp_root.mkdir(exist_ok=True)
    token = sha_bytes(canonical(contract))[:24]
    contract_path = temp_root / (token + ".contract.json")
    output_path = temp_root / (token + ".json.tmp")
    atomic_json(contract_path, contract)
    output_path.unlink(missing_ok=True)
    before = memory_snapshot()
    started = time.monotonic()
    try:
        proc = subprocess.run(
            [sys.executable, str(worker), "--contract", str(contract_path), "--output", str(output_path)],
            cwd=root, capture_output=True, text=True, timeout=timeout,
            env={**os.environ, "PYTHONPATH": str(root)},
        )
    except subprocess.TimeoutExpired as exc:
        return {"status": "FAILED", "element_id": contract["element_id"], "worker_exit_code": "TIMEOUT", "stderr_tail": str(exc)}
    after = memory_snapshot()
    elapsed = time.monotonic() - started
    if proc.returncode != 0 or not output_path.exists():
        return {"status": "FAILED", "element_id": contract["element_id"], "worker_exit_code": proc.returncode, "wall_time_seconds": elapsed, "stderr_tail": proc.stderr[-2000:], "memory_before": before, "memory_after": after}
    try:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"status": "FAILED", "element_id": contract["element_id"], "error": f"invalid worker JSON: {exc}"}
    if not valid_checkpoint(output_path, contract):
        return {"status": "FAILED", "element_id": contract["element_id"], "error": "checkpoint identity validation failed"}
    os.replace(output_path, final)
    return {"status": "COMPLETED", "checkpoint": str(final), "payload": payload, "worker_exit_code": 0, "wall_time_seconds": elapsed, "memory_before": before, "memory_after": after, "checkpoint_sha256": sha_bytes(final.read_bytes())}

def select_certification(sample, domain) -> list[int]:
    centers = list(sample.centers)
    boundary = [i for i, q in enumerate(centers) if domain.polygon.boundary.distance(Point(q)) <= 2.0 * SPACING]
    interior = [i for i in range(len(centers)) if i not in boundary]
    selected = interior[:4] + boundary[:4]
    for target in ((0.11, -0.028), (0.139, -0.0003)):
        candidate = min(range(len(centers)), key=lambda i: (sum((centers[i][j] - target[j]) ** 2 for j in range(2)), i))
        if candidate not in selected:
            selected.append(candidate)
    for index in range(len(centers)):
        if len(selected) >= 12:
            break
        if index not in selected:
            selected.append(index)
    return selected[:12]

def aggregate(contracts: list[dict], checkpoints: Path) -> dict | None:
    payloads = []
    for contract in contracts:
        path = checkpoint_path(checkpoints, contract["element_id"])
        if not valid_checkpoint(path, contract):
            return None
        payloads.append(json.loads(path.read_text(encoding="utf-8")))
    if not payloads or not all(x["result"]["qualified"] for x in payloads):
        return None
    integral = sum(float(c["integration_weight"]) * float(p["result"]["omega_trace_q"]) for c, p in zip(contracts, payloads))
    return {"schema": "e7i4f_stage2_result_v1", "element_count": len(contracts), "qualified_element_count": len(payloads), "qualified_area_fraction": sum(float(c["integration_weight"]) for c in contracts), "curvature_integral": integral, "composite_valley_chern": integral / (2.0 * 3.141592653589793)}

def self_test(root: Path) -> dict:
    with tempfile.TemporaryDirectory(prefix="e7i4f-env1-selftest-") as raw:
        directory = Path(raw)
        contract = {"runner_code_git_sha": "x", "element_id": "self", "evaluation_q": [0.0, 0.0], "integration_weight": 1.0, "geometry_digest": "g", "material_digest": "m", "coordinate_mapping_digest": "c", "domain_digest": "d", "resolution": 48, "representation": REPRESENTATION, "polarization": POLARIZATION, "num_bands": 4, "solver_tolerance": TOLERANCE, "deterministic": True, "mesh_size": 3}
        payload = {"schema": "e7i4f_element_checkpoint_v1", "complete": True, "result": {"qualified": True, "omega_trace_q": 1.0}, **expected_identity(contract)}
        final = checkpoint_path(directory, "self")
        atomic_json(final, payload)
        assert valid_checkpoint(final, contract)
        assert not valid_checkpoint(directory / "missing.json", contract)
        final.write_text("{truncated", encoding="utf-8")
        assert not valid_checkpoint(final, contract)
        atomic_json(final, payload)
        assert aggregate([contract], directory) is not None
        final.unlink()
        assert aggregate([contract], directory) is None
    return {"self_test": "PASSED", "checkpoint_resume_self_test": "PASSED"}

def certify(root: Path) -> dict:
    geometry = build_triangular_reference_geometry(FR)
    preflight = build_triangular_coordinate_preflight()
    domain = paper_style_truncated_k_hbz(fr=FR, delta_k=0.10, delta_gamma=0.10)
    sample = sample_domain(domain, SPACING)
    indices = select_certification(sample, domain)
    checkpoint_dir = root / "audit" / "e7i4f" / "checkpoints" / "certification"
    worker = Path(__file__).with_name("run_stage2_element_worker.py")
    before = memory_snapshot()
    oom_before = oom_count()
    entries, contracts = [], []
    for index in indices:
        contract = build_contract(root, sample, index, geometry, preflight, domain)
        contracts.append(contract)
        entries.append(run_element(root, contract, checkpoint_dir, worker))
    after = memory_snapshot()
    oom_after = oom_count()
    passed = all(x["status"] in {"COMPLETED", "REUSE"} for x in entries) and aggregate(contracts, checkpoint_dir) is not None and oom_after == oom_before and after.get("MemAvailable_kib", 0) >= before.get("MemAvailable_kib", 0) - 2_000_000
    report = {
        "schema": "e7i4f_environment_report_v1", "work_order": WORK_ORDER,
        "environment_root_cause": "WSL_OOM_CONFIRMED", "execution_architecture": "FRESH_SUBPROCESS_PER_ELEMENT",
        "certification_elements": len(indices), "certification_element_ids": [x["element_id"] for x in contracts],
        "certification_passed": passed, "max_worker_peak_rss_kib": max((x.get("payload", {}).get("telemetry", {}).get("worker_peak_rss_kib", 0) for x in entries), default=0),
        "wsl_meminfo_before": before, "wsl_meminfo_after": after, "oom_events_before": oom_before, "oom_events_after": oom_after,
        "worker_entries": [{k: v for k, v in x.items() if k != "payload"} for x in entries],
        "full_stage2_continuation": "AUTHORIZED_AFTER_CERTIFICATION" if passed else "NOT_AUTHORIZED",
        "stage2_composite_valley_chern": "NOT_REPORTED", "main_push_authorized": False, "main_unchanged_required": True,
    }
    atomic_json(root / "audit" / "e7i4f" / "environment_report.json", report)
    print(json.dumps({"certification_passed": passed, "elements": len(indices), "max_worker_peak_rss_kib": report["max_worker_peak_rss_kib"]}))
    return report

def run_full(root: Path) -> None:
    report_path = root / "audit" / "e7i4f" / "environment_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("full_stage2_continuation") != "AUTHORIZED_AFTER_CERTIFICATION":
        raise RuntimeError("12-element certification has not authorized full Stage 2")
    geometry = build_triangular_reference_geometry(FR)
    preflight = build_triangular_coordinate_preflight()
    domain = paper_style_truncated_k_hbz(fr=FR, delta_k=0.10, delta_gamma=0.10)
    sample = sample_domain(domain, SPACING)
    checkpoints = root / "audit" / "e7i4f" / "checkpoints" / "full"
    worker = Path(__file__).with_name("run_stage2_element_worker.py")
    contracts = []
    started = time.monotonic()
    for index in range(len(sample.centers)):
        contract = build_contract(root, sample, index, geometry, preflight, domain)
        contracts.append(contract)
        entry = run_element(root, contract, checkpoints, worker)
        if entry["status"] == "FAILED":
            atomic_json(root / "audit" / "e7i4f" / "stage2_failure_report.json", {"schema": "e7i4f_stage2_failure_v1", "element_id": contract["element_id"], "completed_elements": index, "expected_elements": len(sample.centers), "entry": entry, "stage2_composite_valley_chern": "NOT_REPORTED"})
            print(json.dumps({"stage2_status": "STOPPED_FAIL_CLOSED", "completed": index, "total": len(sample.centers)}))
            return
        if index % 10 == 0:
            print(json.dumps({"progress": index, "total": len(sample.centers), "status": entry["status"]}), flush=True)
    result = aggregate(contracts, checkpoints)
    qualified_area = None if result is None else float(result["qualified_area_fraction"])
    if result is None or abs(qualified_area - float(sample.retained_area_q)) > 1e-10:
        atomic_json(root / "audit" / "e7i4f" / "stage2_failure_report.json", {"schema": "e7i4f_stage2_failure_v1", "completed_elements": len(contracts), "expected_elements": len(sample.centers), "qualified_area_fraction": qualified_area, "required_area_fraction": float(sample.retained_area_q), "stage2_composite_valley_chern": "NOT_REPORTED"})
        print(json.dumps({"stage2_status": "NOT_FULLY_QUALIFIED", "elements": len(contracts)}))
        return
    manifest = [{"element_id": c["element_id"], "checkpoint_sha256": sha_bytes(checkpoint_path(checkpoints, c["element_id"]).read_bytes()), "weight": c["integration_weight"]} for c in contracts]
    result.update({"work_order": WORK_ORDER, "runner_code_git_sha": git_head(root), "stage2_status": "FULLY_QUALIFIED", "checkpoint_count": len(manifest), "checkpoint_manifest_sha256": sha_bytes(canonical(manifest)), "wall_time_seconds": time.monotonic() - started, "stage2_composite_valley_chern": result["composite_valley_chern"], "main_unchanged": True, "main_push_authorized": False})
    atomic_json(root / "audit" / "e7i4f" / "result.json", result)
    print(json.dumps({"stage2_status": "FULLY_QUALIFIED", "elements": len(contracts), "chern": result["composite_valley_chern"]}))

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--certify", action="store_true")
    parser.add_argument("--run-full", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    if args.self_test:
        print(json.dumps(self_test(root)))
    elif args.certify:
        certify(root)
    elif args.run_full:
        run_full(root)
    else:
        parser.error("choose --self-test, --certify, or --run-full")

if __name__ == "__main__":
    main()
