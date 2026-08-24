"""Audited public entry point for the E9F.C1.RP2 implementation."""
from __future__ import annotations
import json, os, subprocess, sys
from pathlib import Path
from typing import Any, Mapping, Sequence
from audit.e9f import run_e9f_c1_rp2_impl as _impl

WORK_ORDER, PHASE, STOP_AFTER = _impl.WORK_ORDER, _impl.PHASE, _impl.STOP_AFTER
CONTRACT_REL, POLICY_REL = _impl.CONTRACT_REL, _impl.POLICY_REL
STENCILS, RESOLUTIONS = _impl.STENCILS, _impl.RESOLUTIONS
CampaignRuntimeError, sha256_file = _impl.CampaignRuntimeError, _impl.sha256_file
_ORIGINAL_LOAD_EXECUTION_CONTRACT = _impl.load_execution_contract
_ORIGINAL_PATH_DIAGNOSTIC = _impl._path_diagnostic

def load_execution_contract(root: Path) -> dict[str, Any]: return _ORIGINAL_LOAD_EXECUTION_CONTRACT(root)
def build_plan(root: Path) -> list[dict[str, Any]]: return _impl.build_plan(root)
def matrix_entry_keys() -> set[tuple[str, str]]: return {(row["sample_id"], stencil) for row in build_plan(Path(__file__).resolve().parents[2]) for stencil in STENCILS}
def validate_worker_identity(row: Mapping[str, Any], *, worker_id: str, resolution: int, coordinate: Sequence[float]) -> None: return _impl.validate_worker_identity(row, worker_id=worker_id, resolution=resolution, coordinate=coordinate)
def validate_worker_payload(payload: Mapping[str, Any], row: Mapping[str, Any]) -> None: return _impl.validate_worker_payload(payload, row)
def _unavailable(reason: str) -> dict[str, Any]: return _impl._unavailable(reason)
def _l3(rank1: Mapping[str, Any], rank3: Mapping[str, Any], rank2: Mapping[str, Any]) -> dict[str, Any]: return _impl._l3(rank1, rank3, rank2)

def run_reaped_child(command, worker_id: str, *, timeout_seconds: float = 720.0):
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try: stdout, stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        process.kill(); process.communicate(); raise CampaignRuntimeError(f"RP2_NATIVE_CHILD_TIMEOUT:{worker_id}") from exc
    direct_pid_gone = not (Path("/proc") / str(process.pid)).exists(); orphan_pids = [pid for pid in _impl.scan_worker_processes(worker_id) if pid != process.pid]
    measurement = {"worker_id": worker_id, "launched_pid": int(process.pid), "returncode": int(process.returncode), "direct_pid_gone": bool(direct_pid_gone), "orphan_pids": orphan_pids, "orphan_count": len(orphan_pids)}
    if not direct_pid_gone or orphan_pids: raise CampaignRuntimeError(f"RP2_NATIVE_ORPHAN_DETECTED:{measurement}")
    if process.returncode != 0: raise CampaignRuntimeError(f"RP2_NATIVE_CHILD_FAILED:{worker_id}:{process.returncode}:{stderr[-600:]}")
    for line in reversed([line.strip() for line in stdout.splitlines() if line.strip()]):
        try: value = json.loads(line)
        except json.JSONDecodeError: continue
        if isinstance(value, dict): return value, measurement
    raise CampaignRuntimeError(f"RP2_NATIVE_CHILD_JSON_INVALID:{worker_id}:{stderr[-600:]}")

def _clean_execution_contract(root: Path) -> dict[str, Any]:
    value = json.loads(json.dumps(_ORIGINAL_LOAD_EXECUTION_CONTRACT(root)))
    value["raw_association"] = {key: value["raw_association"][key] for key in ("probability_threshold", "margin_threshold", "assignment_margin_threshold")}
    return value

def _fixed_rank1_level(*args, **kwargs):
    result = _impl._rank1_level(*args, **kwargs)
    if result.get("status") == "DIAGNOSTIC_REPORTED":
        stencil = kwargs.get("stencil") or args[-1]; h = 1.0 / float(str(stencil).split("/")[1]); phase = result.get("wilson_phase_wrapped")
        result["PLAQUETTE_AREA_Q"] = h * h; result["OMEGA_RANK1_SHADOW"] = None if phase is None else float(phase / (h * h))
    return result

def _path_probe(*args, **kwargs):
    label = args[4] if len(args) > 4 else kwargs.get("label")
    if label == "L2_RANK2_PAIR": return None, None, {}
    return _ORIGINAL_PATH_DIAGNOSTIC(*args, **kwargs)

def worker_command(root: Path, row: Mapping[str, Any]) -> list[str]:
    return [_impl.sys.executable, str(Path(__file__).resolve()), "--worker", "--root", str(root), "--worker-id", str(row["sample_id"]), "--resolution", str(row["resolution"]), "--coordinate-json", json.dumps(row["authoritative_coordinate"], separators=(",", ":"))]

def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv); root = Path(args[args.index("--root") + 1]).resolve() if "--root" in args else Path(__file__).resolve().parents[2]
    os.environ["PYTHONPATH"] = str(root) + os.pathsep + os.environ.get("PYTHONPATH", "")
    _impl.CampaignRuntime.ARTIFACT_SCHEMA = "trilatt_e9f_c1_rp2_worker_v1"
    _impl.load_execution_contract = _clean_execution_contract; _impl._rank1_level = _fixed_rank1_level; _impl._path_diagnostic = _path_probe; _impl.worker_command = worker_command; _impl.run_reaped_child = run_reaped_child
    return _impl.main(args)

if __name__ == "__main__": raise SystemExit(main())
