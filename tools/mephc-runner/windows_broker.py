"""Non-blocking Windows supervisor for MePhC source materialization.

The broker never authorizes or replays a change.  It only dispatches an already
validated durable marker, maintains an independent heartbeat, and converts a
lost or timed-out child into recovery_required.
"""
from __future__ import annotations

import hashlib
import json
import ctypes
import msvcrt
import os
import subprocess
import sys
import time
import secrets
from pathlib import Path

CONTROL_ROOT = Path(r"C:\Users\icywo\PycharmProjects\MePhC-Windows")
RUNTIME = Path(os.environ.get("LOCALAPPDATA", "")) / "MePhCRunner"
STATE_ROOT = Path(r"\\wsl.localhost\Ubuntu\home\icy\.local\state\mephc-runner\MEPHC")
JOBS = STATE_ROOT / "runner" / "jobs"
HEARTBEAT = RUNTIME / "broker-heartbeat.json"
WORKER_HEALTH = RUNTIME / "broker-worker-health.json"
LOCK = RUNTIME / "broker.lock"
MATERIALIZER = RUNTIME / "windows_materializer.py"
TIMEOUT_SECONDS = int(os.environ.get("MEPHC_MATERIALIZER_TIMEOUT_SECONDS", "300"))


def atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def now_record(worker_ok: bool) -> dict:
    current = RUNTIME / "current.json"
    try:
        build = json.loads(current.read_text(encoding="utf-8-sig")).get("build_id")
    except (OSError, json.JSONDecodeError):
        build = None
    return {"schema": "mephc-windows-broker-heartbeat-v2", "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "updated_unix": time.time(), "pid": os.getpid(), "worker_ok": worker_ok,
            "distro": "Ubuntu", "broker_build_id": build}


def parent_alive(pid: int) -> bool:
    synchronize = 0x00100000
    still_running = 0x00000102
    handle = ctypes.windll.kernel32.OpenProcess(synchronize, False, pid)
    if not handle:
        return False
    try:
        return ctypes.windll.kernel32.WaitForSingleObject(handle, 0) == still_running
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def heartbeat_process(parent_pid: int) -> int:
    while True:
        if not parent_alive(parent_pid):
            return 0
        try:
            worker = json.loads(WORKER_HEALTH.read_text(encoding="utf-8"))
            worker_ok = worker.get("worker_ok") is True and time.time() - float(worker["checked_unix"]) <= 30
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            worker_ok = False
        record = now_record(worker_ok)
        record["supervisor_pid"] = parent_pid
        atomic_json(HEARTBEAT, record)
        time.sleep(1)


def start_worker_probe() -> subprocess.Popen[bytes]:
    wsl = Path(os.environ["SystemRoot"]) / "System32" / "wsl.exe"
    return subprocess.Popen([str(wsl), "-d", "Ubuntu", "-u", "root", "--",
                             "systemctl", "is-active", "--quiet", "mephc-runner.service"],
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            creationflags=subprocess.CREATE_NO_WINDOW)


def fail(job_dir: Path, mode: str, code: str, detail: str, recovery: bool = True) -> None:
    name = "materializer-recovery-state.json" if mode == "recover" else "materializer-state.json"
    atomic_json(job_dir / name, {"state": "recovery_required" if recovery else "failed",
                                "error_code": code, "detail": detail})


def terminate_tree(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    subprocess.run([str(Path(os.environ["SystemRoot"]) / "System32" / "taskkill.exe"),
                    "/PID", str(process.pid), "/T", "/F"], capture_output=True, check=False, timeout=20)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()


def request_for(job_dir: Path) -> tuple[str, Path] | None:
    try:
        state = json.loads((job_dir / "state.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if state.get("state") != "running" or state.get("operation") != "change":
        return None
    recovery = state.get("recovery") is True
    for mode, marker in (("recover", "MATERIALIZE_RECOVER_READY"), ("transact", "MATERIALIZE_READY")):
        if (mode == "recover") != recovery:
            continue
        state_name = "materializer-recovery-state.json" if mode == "recover" else "materializer-state.json"
        if (job_dir / marker).is_file() and not (job_dir / state_name).is_file():
            return mode, job_dir / marker
    return None


def validate(job_dir: Path, marker: Path, mode: str) -> dict:
    job_raw = (job_dir / "job.json").read_bytes()
    request = json.loads(marker.read_text(encoding="utf-8"))
    job = json.loads(job_raw)
    if (job.get("schema") != "mephc-runner-job-v2" or job.get("operation") != "change"
            or job.get("project_id") != "MEPHC" or job.get("job_id") != job_dir.name
            or str(job.get("expected_control_root", "")).casefold() != str(CONTROL_ROOT).casefold()
            or request.get("mode") != mode
            or request.get("job_sha256") != hashlib.sha256(job_raw).hexdigest()):
        raise RuntimeError("CHANGE_BROKER_VALIDATION_FAILED")
    return job


def command_line_for(pid: int) -> str | None:
    powershell = Path(os.environ["SystemRoot"]) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    script = f"(Get-CimInstance Win32_Process -Filter \"ProcessId={pid}\").CommandLine"
    result = subprocess.run([str(powershell), "-NoProfile", "-Command", script], text=True,
                            encoding="utf-8", capture_output=True, check=False, timeout=15)
    value = result.stdout.strip()
    return value if result.returncode == 0 and value else None


def reconcile_abandoned_dispatch(job_dir: Path, mode: str) -> bool:
    dispatch_path = job_dir / ("broker-recovery-dispatch.json" if mode == "recover" else "broker-dispatch.json")
    if not dispatch_path.is_file():
        return False
    try:
        dispatch = json.loads(dispatch_path.read_text(encoding="utf-8"))
        pid = int(dispatch["pid"]); token = str(dispatch["run_token"])
        command_line = command_line_for(pid)
        if command_line and token in command_line and job_dir.name in command_line:
            subprocess.run([str(Path(os.environ["SystemRoot"]) / "System32" / "taskkill.exe"),
                            "/PID", str(pid), "/T", "/F"], capture_output=True, check=False, timeout=20)
        fail(job_dir, mode, "BROKER_RESTART_DURING_MATERIALIZATION",
             f"previous_pid={pid};process_identity_verified={bool(command_line and token in command_line)}")
    except Exception as exc:
        fail(job_dir, mode, "BROKER_RESTART_RECONCILIATION_FAILED", repr(exc))
    return True


def poll_active(active: dict[str, dict], current: float | None = None) -> None:
    current = time.monotonic() if current is None else current
    for job_id, record in list(active.items()):
        process: subprocess.Popen[bytes] = record["process"]
        job_dir: Path = record["job_dir"]
        mode: str = record["mode"]
        if process.poll() is not None:
            state_name = "materializer-recovery-state.json" if mode == "recover" else "materializer-state.json"
            if not (job_dir / state_name).is_file():
                fail(job_dir, mode, "MATERIALIZER_EXITED_WITHOUT_STATE", f"return_code={process.returncode}")
            del active[job_id]
        elif current >= record["deadline"]:
            terminate_tree(process)
            fail(job_dir, mode, "CHANGE_MATERIALIZER_TIMEOUT", f"pid={process.pid};timeout={TIMEOUT_SECONDS}")
            del active[job_id]


def dispatch_next(active: dict[str, dict]) -> None:
    if active or not JOBS.is_dir():
        return
    for job_dir in sorted(path for path in JOBS.iterdir() if path.is_dir()):
        requested = request_for(job_dir)
        if not requested:
            continue
        mode, marker = requested
        try:
            validate(job_dir, marker, mode)
            if reconcile_abandoned_dispatch(job_dir, mode):
                break
            environment = dict(os.environ)
            environment.update({"GIT_TERMINAL_PROMPT": "0", "GIT_EDITOR": "true", "GIT_MERGE_AUTOEDIT": "no"})
            flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
            run_token = secrets.token_hex(16)
            process = subprocess.Popen([sys.executable, str(MATERIALIZER), mode, str(job_dir),
                                        "--run-token", run_token],
                                       cwd=CONTROL_ROOT, env=environment,
                                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL, creationflags=flags)
            dispatch = {"schema": "mephc-materializer-dispatch-v1", "job_id": job_dir.name,
                        "mode": mode, "pid": process.pid, "started_unix": time.time(),
                        "deadline_unix": time.time() + TIMEOUT_SECONDS, "run_token": run_token}
            dispatch_name = "broker-recovery-dispatch.json" if mode == "recover" else "broker-dispatch.json"
            atomic_json(job_dir / dispatch_name, dispatch)
            active[job_dir.name] = {"process": process, "job_dir": job_dir, "mode": mode,
                                    "deadline": time.monotonic() + TIMEOUT_SECONDS}
        except Exception as exc:
            fail(job_dir, mode, "CHANGE_BROKER_DISPATCH_FAILED", repr(exc))
        break


def main() -> int:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    lock = LOCK.open("a+b")
    try:
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        return 3
    active: dict[str, dict] = {}
    atomic_json(WORKER_HEALTH, {"worker_ok": False, "checked_unix": time.time()})
    heartbeat = subprocess.Popen([sys.executable, str(Path(__file__)), "--heartbeat", str(os.getpid())],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
    next_worker_check = 0.0
    worker_probe: tuple[subprocess.Popen[bytes], float] | None = None
    while True:
        current = time.monotonic()
        if worker_probe is not None:
            probe, deadline = worker_probe
            if probe.poll() is not None:
                atomic_json(WORKER_HEALTH, {"worker_ok": probe.returncode == 0, "checked_unix": time.time()})
                worker_probe = None
                next_worker_check = current + 10
            elif current >= deadline:
                probe.kill()
                atomic_json(WORKER_HEALTH, {"worker_ok": False, "checked_unix": time.time()})
                worker_probe = None
                next_worker_check = current + 10
        if worker_probe is None and current >= next_worker_check:
            try:
                worker_probe = (start_worker_probe(), current + 10)
            except OSError:
                atomic_json(WORKER_HEALTH, {"worker_ok": False, "checked_unix": time.time()})
                next_worker_check = current + 10
        try:
            poll_active(active)
            dispatch_next(active)
        except Exception as exc:
            atomic_json(WORKER_HEALTH, {"worker_ok": False, "checked_unix": time.time()})
            atomic_json(RUNTIME / "broker-error.json", {"schema": "mephc-windows-broker-error-v1",
                                                         "updated_unix": time.time(), "detail": repr(exc)})
        time.sleep(1)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--heartbeat":
        raise SystemExit(heartbeat_process(int(sys.argv[2])))
    raise SystemExit(main())
