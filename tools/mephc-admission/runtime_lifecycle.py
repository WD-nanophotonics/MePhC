"""Fixed-scope Windows lifecycle controller for the MePhC installed runtime."""
from __future__ import annotations

import hashlib
import json
try:
    import msvcrt
except ModuleNotFoundError:  # Import-only support for WSL infrastructure tests.
    class _Msvcrt:
        LK_NBLCK = 0

        @staticmethod
        def locking(*_args) -> None:
            return None

    msvcrt = _Msvcrt()
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import time
from typing import Any

CONTROL_ROOT = Path(r"C:\Users\icywo\PycharmProjects\MePhC-Windows")
RUNTIME = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "MePhCRunner"
POWERSHELL = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
RUNNER = RUNTIME / "mephc-runner.cmd"
EXPECTED_MAIN = "5a4e9e839eff40f582c2404ff3eadd2bf8b676b5"
LOCK = RUNTIME / "lifecycle.lock"
RECEIPTS = RUNTIME / "lifecycle-receipts"
WINDOWS_RUNTIME_FILES = (
    "mephc-runner.ps1", "mephc-runner.cmd", "mephc-connector.cmd", "mephc-connector.ps1",
    "windows_materializer.py", "windows_broker.py", "README.md", "install-manifest.json",
)
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class LifecycleError(RuntimeError):
    def __init__(self, code: str, detail: str = "") -> None:
        self.code, self.detail = code, detail
        super().__init__(f"{code}:{detail}")


def _run(argv: list[str], *, cwd: Path = CONTROL_ROOT, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    environment = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_EDITOR": "true",
                   "GIT_CONFIG_NOSYSTEM": "1"}
    if argv and Path(argv[0]).name.lower() == "powershell.exe":
        environment["PSModulePath"] = str(Path(os.environ.get("SystemRoot", r"C:\Windows")) /
                                           "System32/WindowsPowerShell/v1.0/Modules")
    try:
        return subprocess.run(argv, cwd=cwd, text=True, encoding="utf-8", errors="replace",
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=timeout,
                              env=environment, creationflags=NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise LifecycleError("RUNTIME_LIFECYCLE_PROCESS_FAILED", type(exc).__name__) from exc


def _git(*args: str, timeout: int = 30) -> str:
    result = _run(["git", "-c", f"safe.directory={CONTROL_ROOT.as_posix()}", "-C", str(CONTROL_ROOT), *args], timeout=timeout)
    if result.returncode:
        raise LifecycleError("RUNTIME_GIT_CHECK_FAILED", result.stderr[-1000:])
    return result.stdout.strip()


def _current() -> dict[str, Any]:
    try:
        value = json.loads((RUNTIME / "current.json").read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LifecycleError("RUNTIME_CURRENT_INVALID") from exc
    return value if isinstance(value, dict) else {}


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _active_jobs() -> list[dict[str, Any]]:
    result = _run([str(RUNNER), "Capabilities"], cwd=RUNTIME, timeout=30)
    if result.returncode:
        raise LifecycleError("RUNTIME_CAPABILITIES_UNAVAILABLE", result.stderr[-1000:])
    try:
        value = json.loads(result.stdout.splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        raise LifecycleError("RUNTIME_CAPABILITIES_INVALID") from exc
    return value.get("active_jobs", []) if isinstance(value, dict) else []


def _reload_recovery_barrier(jobs: list[dict[str, Any]]) -> tuple[list[str], list[dict[str, Any]]]:
    """Separate inert recovery evidence from jobs a reload could interrupt.

    A change in ``recovery_required`` is already terminal and cannot execute
    until an explicit typed recovery call.  Keeping it in the active index is
    intentional, but treating it like a running job creates a deadlock when
    that recovery requires newly loaded admission code.  Unknown or malformed
    records continue to fail closed.
    """
    preserved: list[str] = []
    blocking: list[dict[str, Any]] = []
    for job in jobs:
        if (isinstance(job, dict) and job.get("state") == "recovery_required"
                and isinstance(job.get("job_id"), str) and job["job_id"]):
            preserved.append(job["job_id"])
        else:
            blocking.append(job)
    return preserved, blocking


def _gate() -> dict[str, str]:
    if _git("status", "--porcelain", "--untracked-files=all"):
        raise LifecycleError("RUNTIME_ACTIVATION_DIRTY_SOURCE")
    if _git("branch", "--show-current") != "sandbox":
        raise LifecycleError("RUNTIME_ACTIVATION_BRANCH_INVALID")
    head = _git("rev-parse", "HEAD")
    if _git("rev-parse", "origin/main") != EXPECTED_MAIN:
        raise LifecycleError("RUNTIME_ACTIVATION_MAIN_MOVED")
    remote = _git("ls-remote", "origin", "refs/heads/main", "refs/heads/sandbox", timeout=60)
    refs = {line.split()[1]: line.split()[0] for line in remote.splitlines() if len(line.split()) == 2}
    if refs.get("refs/heads/main") != EXPECTED_MAIN:
        raise LifecycleError("RUNTIME_ACTIVATION_MAIN_MOVED")
    if refs.get("refs/heads/sandbox") != head:
        raise LifecycleError("RUNTIME_ACTIVATION_SANDBOX_NOT_PUBLISHED")
    current = _current()
    installed = current.get("source_commit")
    if not isinstance(installed, str) or len(installed) != 40:
        raise LifecycleError("RUNTIME_INSTALLED_SOURCE_UNKNOWN")
    changed = _git("diff", "--name-only", f"{installed}..{head}").splitlines()
    allowed = lambda name: (name in {"AGENTS.md", ".codex/config.toml", "mephc/relayctl.py"} or name.startswith("tools/mephc-runner/")
                            or name.startswith("tools/mephc-admission/")
                            or name.startswith("tests/test_mephc") or name == "tests/test_relayctl.py")
    # The exact tip must be a deliberate infrastructure capstone. Historical
    # scientific commits may exist between installed and HEAD, but bootstrap
    # never copies them into either runtime; retain only a digest/count here.
    tip_changed = _git("diff", "--name-only", f"{head}^..{head}").splitlines()
    tip_forbidden = sorted(name for name in tip_changed if not allowed(name))
    if tip_forbidden or not tip_changed:
        raise LifecycleError("RUNTIME_ACTIVATION_NON_INFRASTRUCTURE_TIP", ",".join(tip_forbidden[:20]))
    ignored = sorted(name for name in changed if not allowed(name))
    ignored_digest = hashlib.sha256("\n".join(ignored).encode("utf-8")).hexdigest()
    if _active_jobs():
        raise LifecycleError("RUNTIME_ACTIVATION_ACTIVE_JOB")
    return {"source_head": head, "installed_source_head": installed,
            "ignored_nonruntime_change_count": len(ignored),
            "ignored_nonruntime_change_list_sha256": ignored_digest}


def _tests() -> None:
    tests = sorted(str(path) for path in (CONTROL_ROOT / "tests").glob("test_mephc*.py"))
    tests.append(str(CONTROL_ROOT / "tests/test_relayctl.py"))
    result = _run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *tests], timeout=600)
    if result.returncode:
        raise LifecycleError("RUNTIME_ACTIVATION_TESTS_FAILED", (result.stdout + result.stderr)[-2000:])


def _stage(head: str) -> Path:
    root = RUNTIME / "activation-staging" / head
    if root.exists(): shutil.rmtree(root)
    root.mkdir(parents=True, mode=0o700)
    archive = root.with_suffix(".tar")
    result = _run(["git", "-c", f"safe.directory={CONTROL_ROOT.as_posix()}", "-C", str(CONTROL_ROOT),
                   "archive", "--format=tar", "-o", str(archive), head], timeout=120)
    if result.returncode: raise LifecycleError("RUNTIME_ACTIVATION_STAGE_FAILED", result.stderr[-1000:])
    with tarfile.open(archive, "r:") as handle:
        for member in handle.getmembers():
            if member.issym() or member.islnk():
                raise LifecycleError("RUNTIME_ACTIVATION_STAGE_LINK_FORBIDDEN", member.name)
            target = (root / member.name).resolve()
            try: target.relative_to(root.resolve())
            except ValueError as exc: raise LifecycleError("RUNTIME_ACTIVATION_STAGE_ESCAPE") from exc
        handle.extractall(root)
    archive.unlink(missing_ok=True)
    return root


def _receipt(action: str, value: dict[str, Any]) -> dict[str, Any]:
    RECEIPTS.mkdir(parents=True, exist_ok=True)
    value = {"schema":"mephc-runtime-lifecycle-receipt-v1","action":action,
             "created_at":time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **value}
    digest = hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    path = RECEIPTS / f"{int(time.time())}-{action}-{digest[:16]}.json"
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)
    return {**value, "receipt_id": path.stem, "receipt_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _redact_detail(value: str) -> str:
    text = value.replace(str(CONTROL_ROOT), "<CONTROL_ROOT>").replace(str(RUNTIME), "<RUNTIME>")
    return text[-1200:]


def _restart_broker() -> None:
    script = ("Stop-ScheduledTask -TaskName MePhCRunnerBroker -ErrorAction SilentlyContinue;"
              "for($i=0;$i -lt 20;$i++){if((Get-ScheduledTask -TaskName MePhCRunnerBroker).State "
              "-notin @('Running','Queued')){break};Start-Sleep -Milliseconds 250};"
              "Start-ScheduledTask -TaskName MePhCRunnerBroker")
    result = _run([str(POWERSHELL), "-NoProfile", "-Command", script], timeout=60)
    if result.returncode: raise LifecycleError("RUNTIME_RELOAD_BROKER_FAILED", result.stderr[-1000:])


def _runner_health() -> dict[str, Any]:
    result = _run([str(RUNNER), "Health"], cwd=RUNTIME, timeout=30)
    try:
        value = json.loads(result.stdout.splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        raise LifecycleError("RETENTION_WORKER_ATTESTATION_FAILED", "HEALTH_RESPONSE_INVALID") from exc
    if not isinstance(value, dict) or not isinstance(value.get("worker"), dict) or not isinstance(value.get("broker"), dict):
        raise LifecycleError("RETENTION_WORKER_ATTESTATION_FAILED", "HEALTH_RESPONSE_INCOMPLETE")
    return value


def retention_worker_reload() -> dict[str, Any]:
    if _active_jobs():
        raise LifecycleError("RETENTION_WORKER_RELOAD_FAILED", "ACTIVE_JOB")
    before_health = _runner_health()
    if before_health.get("ok") is not True:
        raise LifecycleError("RETENTION_WORKER_ATTESTATION_FAILED", "LIVE_HEALTH_NOT_READY")
    before = before_health["worker"]
    current = _current()
    source_commit = current.get("source_commit")
    if not isinstance(source_commit, str) or len(source_commit) != 40:
        raise LifecycleError("RETENTION_WORKER_ATTESTATION_FAILED", "SOURCE_COMMIT_MISSING")
    old_build = before.get("worker_build_id")
    old_start_id = before.get("worker_start_id")
    old_pid = before.get("pid")
    if not isinstance(old_start_id, str) or not old_start_id or not isinstance(old_pid, int):
        raise LifecycleError("RETENTION_WORKER_ATTESTATION_FAILED", "WORKER_START_IDENTITY_MISSING")
    accepted = {
        "state": "RETENTION_WORKER_RELOAD_ACCEPTED",
        "worker_role": "shared_durable_worker",
        "retention_capable": True,
        "service_name": "mephc-runner.service",
        "raw_expected_head_indexing_active": False,
        "v3_canonical_head_field": "source_commit",
        "source_commit_validation_active": True,
    }
    result = _run(["wsl.exe", "-d", "Ubuntu", "-u", "root", "--", "systemctl", "restart",
                   "mephc-runner.service"], timeout=60)
    if result.returncode:
        raise LifecycleError("RETENTION_WORKER_RELOAD_FAILED", "FIXED_WORKER_SERVICE_RESTART_FAILED")
    deadline = time.monotonic() + 30.0
    after_health: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        try:
            candidate = _runner_health()
            worker = candidate["worker"]
            if candidate.get("ok") is True and worker.get("worker_start_id") != old_start_id:
                after_health = candidate
                break
        except LifecycleError:
            pass
        time.sleep(0.5)
    if after_health is None:
        raise LifecycleError("RETENTION_WORKER_ATTESTATION_FAILED", "SERVICE_RESTART_TIMEOUT")
    after = after_health["worker"]
    new_build = after.get("worker_build_id")
    module_sha = after.get("loaded_worker_module_hash")
    if not isinstance(new_build, str) or not new_build:
        raise LifecycleError("RETENTION_WORKER_ATTESTATION_FAILED", "WORKER_BUILD_ID_MISSING")
    if not isinstance(module_sha, str) or len(module_sha) != 64:
        raise LifecycleError("RETENTION_WORKER_ATTESTATION_FAILED", "WORKER_MODULE_HASH_MISSING")
    if after.get("source_commit") != source_commit:
        raise LifecycleError("RETENTION_WORKER_ATTESTATION_FAILED", "SOURCE_COMMIT_MISMATCH")
    if after.get("installed_source_head") != source_commit:
        raise LifecycleError("RETENTION_WORKER_ATTESTATION_FAILED", "INSTALLED_SOURCE_COMMIT_MISMATCH")
    if (after.get("worker_start_id") == old_start_id or after.get("pid") == old_pid
            or after.get("worker_started_at") == before.get("worker_started_at")):
        raise LifecycleError("RETENTION_WORKER_ATTESTATION_FAILED", "RESTART_NOT_OBSERVED")
    for key in ("worker_build_id", "loaded_worker_module_hash", "installed_source_head", "state_epoch"):
        if after.get(key) != before.get(key):
            raise LifecycleError("RETENTION_WORKER_ATTESTATION_FAILED", f"{key.upper()}_CHANGED")
    broker = after_health["broker"]
    broker_pid = broker.get("supervisor_pid") or broker.get("pid")
    separation = (after.get("platform") == "wsl" and broker.get("platform") == "windows"
                  and isinstance(after.get("pid"), int) and isinstance(broker_pid, int)
                  and after.get("worker_role") == "shared_durable_worker"
                  and broker.get("process_role") == "transport_broker")
    if not separation:
        raise LifecycleError("RETENTION_WORKER_ATTESTATION_FAILED", "TRANSPORT_PROCESS_SEPARATION_UNPROVED")
    return _receipt("retention-worker-reload", {
        **accepted,
        "state": "RETENTION_WORKER_RELOAD_COMPLETED",
        "old_worker_build_id_or_UNKNOWN": old_build if isinstance(old_build, str) else "UNKNOWN",
        "new_worker_build_id": new_build,
        "worker_module_sha256": module_sha,
        "worker_restart_observed": True,
        "before_worker_start_id": old_start_id,
        "after_worker_start_id": after.get("worker_start_id"),
        "before_worker_pid": old_pid,
        "after_worker_pid": after.get("pid"),
        "worker_started_at": after.get("worker_started_at"),
        "broker_fresh": True,
        "transport_process_separation_proved": separation,
        "source_commit": source_commit,
        "expected_head_keyerror": False,
    })


def _snapshot() -> dict[str, Any]:
    current = _current()
    token = f"{int(time.time())}-{current.get('build_id', 'unknown')}"
    root = RUNTIME / "activation-backups" / token
    root.mkdir(parents=True, mode=0o700)
    admission = RUNTIME / "admission"
    if admission.is_dir():
        shutil.copytree(admission, root / "admission")
    codex_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    config = codex_home / "config.toml"
    if config.is_file(): shutil.copy2(config, root / "config.toml")
    project_config = CONTROL_ROOT / ".codex" / "config.toml"
    if project_config.is_file(): shutil.copy2(project_config, root / "project-config.toml")
    _atomic_json(root / "snapshot.json", {"schema":"mephc-runtime-activation-snapshot-v1",
                                           "current":current, "created_at":time.time()})
    return {"root":root, "current":current, "config":config, "project_config":project_config}


def _restore(snapshot: dict[str, Any]) -> None:
    current, root = snapshot["current"], snapshot["root"]
    build = current.get("build_id")
    version = Path(current.get("version_path", ""))
    if not isinstance(build, str) or not build or not version.is_dir():
        raise LifecycleError("RUNTIME_ACTIVATION_ROLLBACK_UNAVAILABLE")
    wsl_version = f"/opt/mephc-runner/versions/{build}"
    result = _run(["wsl.exe", "-d", "Ubuntu", "-u", "root", "--", "ln", "-sfn",
                   wsl_version, "/opt/mephc-runner/current"], timeout=30)
    if result.returncode: raise LifecycleError("RUNTIME_ACTIVATION_ROLLBACK_WSL_FAILED", result.stderr[-1000:])
    for name in WINDOWS_RUNTIME_FILES:
        source = version / name
        if source.is_file(): shutil.copy2(source, RUNTIME / name)
    _atomic_json(RUNTIME / "current.json", {**current, "restored_at":time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    admission_backup = root / "admission"
    if admission_backup.is_dir():
        admission = RUNTIME / "admission"
        for source in admission_backup.iterdir():
            if source.is_file(): shutil.copy2(source, admission / source.name)
    config_backup = root / "config.toml"
    if config_backup.is_file(): shutil.copy2(config_backup, snapshot["config"])
    project_config_backup = root / "project-config.toml"
    if project_config_backup.is_file():
        snapshot["project_config"].parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(project_config_backup, snapshot["project_config"])
    worker = _run(["wsl.exe", "-d", "Ubuntu", "-u", "root", "--", "systemctl", "restart",
                   "mephc-runner.service"], timeout=60)
    try: _restart_broker()
    except LifecycleError as exc:
        raise LifecycleError("RUNTIME_ACTIVATION_ROLLBACK_RESTART_FAILED", exc.detail) from exc
    if worker.returncode:
        raise LifecycleError("RUNTIME_ACTIVATION_ROLLBACK_RESTART_FAILED")


def reload_installed() -> dict[str, Any]:
    preserved, blocking = _reload_recovery_barrier(_active_jobs())
    if blocking: raise LifecycleError("RUNTIME_RELOAD_ACTIVE_JOB")
    first = _run(["wsl.exe", "-d", "Ubuntu", "-u", "root", "--", "systemctl", "restart", "mephc-runner.service"], timeout=60)
    if first.returncode: raise LifecycleError("RUNTIME_RELOAD_WORKER_FAILED", first.stderr[-1000:])
    _restart_broker()
    preserved_digest = hashlib.sha256("\n".join(sorted(preserved)).encode("utf-8")).hexdigest()
    return _receipt("reload", {"build_id":_current().get("build_id"),
                                "client_backend_rotation_required":True,
                                "preserved_recovery_required_count":len(preserved),
                                "preserved_recovery_required_ids_sha256":preserved_digest})


def activate() -> dict[str, Any]:
    gate = _gate(); _tests(); stage = _stage(gate["source_head"]); snapshot = _snapshot()
    runner = stage / "tools/mephc-runner/bootstrap.ps1"
    admission = stage / "tools/mephc-admission/bootstrap.ps1"
    try:
        for arguments in ((str(runner), "-Install", "-SourceCommit", gate["source_head"]),
                          (str(runner), "-Verify", "-SourceCommit", gate["source_head"]),
                          (str(admission), "-Mode", "Install")):
            result = _run([str(POWERSHELL), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", *arguments], cwd=stage, timeout=600)
            if result.returncode:
                raise LifecycleError("RUNTIME_ACTIVATION_INSTALL_FAILED", (result.stdout + result.stderr)[-2000:])
        attest = _run([str(RUNNER), "Attest"], cwd=RUNTIME, timeout=60)
        if attest.returncode:
            raise LifecycleError("RUNTIME_ACTIVATION_ATTEST_FAILED", (attest.stdout + attest.stderr)[-2000:])
        try: attestation = json.loads(attest.stdout.splitlines()[-1])
        except (IndexError, json.JSONDecodeError) as exc:
            raise LifecycleError("RUNTIME_ACTIVATION_ATTEST_INVALID") from exc
        if attestation.get("coherent") is not True:
            raise LifecycleError("RUNTIME_ACTIVATION_ATTEST_INCOHERENT",
                                 ",".join(attestation.get("mismatches", [])))
    except LifecycleError as exc:
        _restore(snapshot)
        detail = _redact_detail(exc.detail)
        _receipt("rollback", {**gate, "failed_code":exc.code, "failed_detail":detail,
                               "restored_build_id":snapshot["current"].get("build_id")})
        raise LifecycleError("RUNTIME_ACTIVATION_ROLLED_BACK", f"{exc.code}:{detail}") from exc
    return _receipt("activate", {**gate,"build_id":_current().get("build_id"),
                                  "client_backend_rotation_required":True,
                                  "desktop_restart_required_if_tool_schema_changed":True})


def main(argv: list[str]) -> int:
    if argv not in (["reload"], ["activate"], ["retention-worker-reload"]):
        print(json.dumps({"state":"rejected","error_code":"RUNTIME_LIFECYCLE_ARGUMENTS_FORBIDDEN"})); return 2
    RUNTIME.mkdir(parents=True, exist_ok=True)
    with LOCK.open("a+") as handle:
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            print(json.dumps({"state":"rejected","error_code":"RUNTIME_LIFECYCLE_BUSY","retry_allowed":False})); return 2
        try:
            value = (reload_installed() if argv == ["reload"] else
                     retention_worker_reload() if argv == ["retention-worker-reload"] else activate())
            print(json.dumps({"state":"succeeded",**value}, sort_keys=True)); return 0
        except LifecycleError as exc:
            print(json.dumps({"state":"rejected","error_code":exc.code,"detail":exc.detail,
                              "retry_allowed":False,"safe_next_tool":"mephc_runtime_attest"}, sort_keys=True)); return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
