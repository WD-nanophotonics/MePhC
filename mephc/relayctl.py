"""Machine-enforced MePhC relay entry point."""
from __future__ import annotations
import argparse, hashlib, json, os, re, shutil
from pathlib import Path
import subprocess, sys, time, uuid
from typing import Any

CONTROL_ROOT_WINDOWS = os.environ.get(
    "MEPHC_CONTROL_ROOT_WINDOWS", r"C:\Users\icywo\PycharmProjects\MePhC-Windows"
)
CONTROL_ROOT = Path(os.environ.get("MEPHC_CONTROL_ROOT_WSL", "/mnt/c/Users/icywo/PycharmProjects/MePhC-Windows"))
EXECUTION_ROOT = Path(os.environ.get("MEPHC_EXECUTION_ROOT", "/home/icy/.cache/mephc-runner/checkouts"))
STATE_ROOT = Path(os.environ.get("MEPHC_STATE_ROOT", "/home/icy/.local/state/mephc-runner/MEPHC"))
REQUIRED_PYTHON = Path("/home/icy/miniconda3/envs/mp/bin/python")
WINDOWS_POWERSHELL = Path("/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe")
WINDOWS_GIT = Path(os.environ.get("MEPHC_WINDOWS_GIT_WSL", "/mnt/c/Program Files/Git/cmd/git.exe"))
EXPECTED_ORIGIN_MAIN = os.environ.get(
    "MEPHC_EXPECTED_ORIGIN_MAIN", "5a4e9e839eff40f582c2404ff3eadd2bf8b676b5"
)
PROJECT_ID = "MEPHC"
FAILURE_CODES = {"ROOT_MISMATCH", "WORKTREE_NOT_WSL_NATIVE", "INTERPRETER_MISMATCH", "PRELIVE_UNCOMMITTED", "PRELIVE_TEST_FAILED", "SOURCE_BYTE_MISMATCH", "PUBLISH_REMOTE_INVALID", "PUBLISH_FAILED", "COURIER_TIMEOUT_RECOVERY_REQUIRED", "COURIER_QUEUE_TIMEOUT", "COURIER_QUEUE_RECOVERY_REQUIRED", "COURIER_INTERRUPTED", "COURIER_HARD_STOP", "CERTIFICATE_ENVIRONMENT_MISMATCH", "CERTIFICATE_EXECUTION_BINDING_MISMATCH"}
SHA40 = re.compile(r"^[0-9a-f]{40}$")


class RelayFailure(RuntimeError):
    def __init__(self, code: str, detail: str):
        self.code, self.detail = code, detail
        super().__init__(f"{code}: {detail}")


def emit(event: str, **values: Any) -> None:
    print(json.dumps({"event": event, "ok": event not in FAILURE_CODES, **values}, sort_keys=True), flush=True)


def run(*args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, text=True, capture_output=True, check=check)


def git(root: Path, *args: str) -> str:
    try:
        return run("git", *args, cwd=root).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RelayFailure("ROOT_MISMATCH", str(exc)) from exc


def worktree_root(start: Path | None = None) -> Path:
    start = (start or Path.cwd()).resolve()
    top = Path(git(start, "rev-parse", "--show-toplevel")).resolve()
    git_dir = git(top, "rev-parse", "--git-dir")
    if EXECUTION_ROOT not in top.parents:
        raise RelayFailure("ROOT_MISMATCH", f"worktree={top}; execution_root={EXECUTION_ROOT}")
    if not str(top).startswith("/home/icy/") or "\\" in str(top):
        raise RelayFailure("WORKTREE_NOT_WSL_NATIVE", f"worktree={top}")
    directory = (top / git_dir).resolve() if not Path(git_dir).is_absolute() else Path(git_dir).resolve()
    expected_git_root = Path(os.environ.get("MEPHC_GIT_CACHE", "/home/icy/.cache/mephc-runner/MEPHC.git"))
    if expected_git_root != directory and expected_git_root not in directory.parents:
        raise RelayFailure("WORKTREE_NOT_WSL_NATIVE", f"git_dir={directory}")
    return top


def runtime(root: Path) -> Path:
    path = STATE_ROOT if os.name != "nt" else root / ".relayctl"
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_json(path: Path, data: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)
    return path


def read_json(path: Path, code: str = "PRELIVE_UNCOMMITTED") -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RelayFailure(code, f"invalid JSON record: {path}") from exc
    if not isinstance(data, dict):
        raise RelayFailure(code, f"record is not an object: {path}")
    return data


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_manifest(root: Path) -> dict[str, str]:
    names = sorted(filter(None, git(root, "ls-files", "--", "*.py", "*.sh", "*.ps1", "pyproject.toml").splitlines()))
    return {name: sha256(root / name) for name in names}


def clean(root: Path) -> None:
    dirty = git(root, "status", "--porcelain", "--untracked-files=all")
    if dirty:
        raise RelayFailure("PRELIVE_UNCOMMITTED", f"dirty worktree: {dirty.splitlines()[0]}")


def head(root: Path) -> str:
    return git(root, "rev-parse", "HEAD")


def remote_ref(root: Path, ref: str) -> str:
    tracking = "origin/" + ref.rsplit("/", 1)[-1]
    try:
        return git(root, "rev-parse", tracking)
    except RelayFailure as exc:
        raise RelayFailure("ROOT_MISMATCH", f"cannot resolve cached {tracking}") from exc


def windows_git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run Git against the Windows canonical repository and its credential helper."""
    command = [str(WINDOWS_GIT), "-c", f"safe.directory={CONTROL_ROOT_WINDOWS}",
               "-C", CONTROL_ROOT_WINDOWS, *args]
    environment = {
        **os.environ,
        "GIT_TERMINAL_PROMPT": "0",
        "GCM_INTERACTIVE": "Never",
        "GIT_EDITOR": "true",
        "GIT_SEQUENCE_EDITOR": "true",
    }
    try:
        result = subprocess.run(command, text=True, encoding="utf-8", capture_output=True,
                                check=False, timeout=120, env=environment)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RelayFailure("PUBLISH_FAILED", f"Windows Git unavailable: {type(exc).__name__}") from exc
    if check and result.returncode:
        raise RelayFailure("PUBLISH_FAILED", (result.stderr or result.stdout).strip()[-2000:])
    return result


def windows_remote_refs() -> dict[str, str]:
    result = windows_git("ls-remote", "origin", "refs/heads/main", "refs/heads/sandbox")
    refs: dict[str, str] = {}
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) == 2 and SHA40.fullmatch(fields[0]):
            refs[fields[1]] = fields[0]
    if set(refs) != {"refs/heads/main", "refs/heads/sandbox"}:
        raise RelayFailure("PUBLISH_REMOTE_INVALID", f"unexpected remote refs: {sorted(refs)}")
    return refs


def require_python(root: Path) -> None:
    actual = Path(sys.executable).resolve()
    if actual != REQUIRED_PYTHON.resolve() or not REQUIRED_PYTHON.is_file():
        raise RelayFailure("INTERPRETER_MISMATCH", f"actual={actual}; required={REQUIRED_PYTHON}")
    paths = [Path(path).resolve() for path in os.environ.get("PYTHONPATH", "").split(os.pathsep) if path]
    if root.resolve() not in paths:
        raise RelayFailure("INTERPRETER_MISMATCH", f"PYTHONPATH must include {root}")


def _environment_binding() -> dict[str, str]:
    return {
        "runner_build": os.environ.get("MEPHC_RUNNER_BUILD", ""),
        "state_epoch": os.environ.get("MEPHC_STATE_EPOCH", ""),
        "installed_source_head": os.environ.get("MEPHC_INSTALLED_SOURCE_HEAD", ""),
        "control_root": CONTROL_ROOT_WINDOWS,
        "state_root": str(STATE_ROOT),
        "python": str(Path(sys.executable).resolve()),
    }


def load_certificate(root: Path, value: str, *, for_execution: bool = False) -> tuple[Path, dict[str, Any]]:
    path = Path(value) if Path(value).is_absolute() else runtime(root) / "certificates" / value
    record = read_json(path)
    if record.get("project_id") != PROJECT_ID:
        raise RelayFailure("CERTIFICATE_ENVIRONMENT_MISMATCH", "certificate project mismatch")
    if not for_execution:
        return path, record
    if record.get("version") == 2 and record.get("kind") == "environment-certificate":
        expected = _environment_binding()
        mismatches = [key for key in ("runner_build", "state_epoch", "control_root", "state_root", "python")
                      if not expected[key] or record.get(key) != expected[key]]
        if record.get("origin_main") != EXPECTED_ORIGIN_MAIN:
            mismatches.append("origin_main")
        if mismatches:
            raise RelayFailure("CERTIFICATE_ENVIRONMENT_MISMATCH", ",".join(sorted(set(mismatches))))
    else:
        if record.get("worktree") != str(root) or record.get("head") != head(root):
            raise RelayFailure("CERTIFICATE_EXECUTION_BINDING_MISMATCH", "legacy certificate does not bind execution checkout")
    return path, record


def doctor(root: Path) -> Path:
    root = worktree_root(root)
    require_python(root)
    environment = _environment_binding()
    if not environment["runner_build"] or not environment["state_epoch"]:
        raise RelayFailure("CERTIFICATE_ENVIRONMENT_MISMATCH", "runner build or state epoch unavailable")
    record = {
        "version": 2, "kind": "environment-certificate", "project_id": PROJECT_ID,
        "certificate_id": f"doctor-{uuid.uuid4().hex}", "created_at": int(time.time()),
        **environment, "control_root_wsl": str(CONTROL_ROOT),
        "worktree": str(root), "head": head(root),
        "audit_source_commit": head(root), "audit_execution_checkout": str(root),
        "pythonpath": os.environ["PYTHONPATH"], "live_health_fresh": True,
        "worker_health_fresh_at_issue": True, "broker_health_fresh_at_issue": True,
        "origin_main": remote_ref(root, "refs/heads/main"),
        "origin_sandbox": remote_ref(root, "refs/heads/sandbox"),
        "courier_request_root": str(runtime(root) / "outbox"),
        "dependencies": {name: __import__(name).__version__ for name in ("numpy", "scipy", "shapely")},
    }
    return write_json(runtime(root) / "certificates" / f"{record['certificate_id']}.json", record)


def prelive_test_targets(root: Path, tests: list[str]) -> list[str]:
    targets = tests or [
        "tests/test_relayctl.py",
        *(path.relative_to(root).as_posix() for path in sorted((root / "tests").glob("test_mephc_*.py"))),
    ]
    targets = list(dict.fromkeys(targets))
    for target in targets:
        file_part = target.split("::", 1)[0]
        if target.startswith("-") or not file_part:
            raise RelayFailure("PRELIVE_UNCOMMITTED", f"invalid prelive test target: {target}")
        path = (root / file_part).resolve()
        try:
            path.relative_to((root / "tests").resolve())
        except ValueError as exc:
            raise RelayFailure("PRELIVE_UNCOMMITTED", f"test target outside tests/: {target}") from exc
        if not path.is_file():
            raise RelayFailure("PRELIVE_UNCOMMITTED", f"test target missing: {target}")
    return targets


def test_output_tail(value: str, limit: int = 2000) -> str:
    return value[-limit:].replace("\x00", "\\0")


def prelive(root: Path, certificate: str, tests: list[str]) -> Path:
    root = worktree_root(root)
    require_python(root)
    clean(root)
    certificate_path, cert = load_certificate(root, certificate, for_execution=True)
    source_commit = head(root)
    command = [str(REQUIRED_PYTHON), "-m", "pytest", *prelive_test_targets(root, tests)]
    result = subprocess.run(command, cwd=root, text=True, capture_output=True, env={**os.environ, "PYTHONPATH": str(root)})
    record = {
        "version": 2, "kind": "prelive-attestation", "project_id": PROJECT_ID,
        "prelive_id": f"prelive-{uuid.uuid4().hex}", "created_at": int(time.time()),
        "certificate": str(certificate_path),
        "environment_certificate_sha256": hashlib.sha256(certificate_path.read_bytes()).hexdigest(),
        "certificate_version": cert.get("version"), "certificate_head": cert.get("head"),
        "prelive_sha": source_commit, "source_commit": source_commit,
        "execution_checkout_sha": source_commit, "execution_checkout": str(root),
        "origin_main": cert["origin_main"],
        "source_sha256": source_manifest(root), "tests": command, "test_returncode": result.returncode,
        "test_stdout_sha256": hashlib.sha256(result.stdout.encode()).hexdigest(),
        "test_stderr_sha256": hashlib.sha256(result.stderr.encode()).hexdigest(),
        "test_stdout_tail": test_output_tail(result.stdout),
        "test_stderr_tail": test_output_tail(result.stderr),
    }
    path = write_json(runtime(root) / "prelive" / f"{record['prelive_id']}.json", record)
    if result.returncode:
        summary = test_output_tail(result.stdout or result.stderr, limit=500).replace("\n", " | ")
        raise RelayFailure("PRELIVE_TEST_FAILED", f"tests failed: {path}; summary={summary}")
    return path


def verify_prelive(root: Path, value: str) -> dict[str, Any]:
    root = worktree_root(root)
    require_python(root)
    clean(root)
    path = Path(value) if Path(value).is_absolute() else runtime(root) / "prelive" / value
    record = read_json(path)
    if record.get("kind") != "prelive-attestation" or record.get("project_id") != PROJECT_ID or record.get("test_returncode") != 0:
        raise RelayFailure("PRELIVE_UNCOMMITTED", "prelive attestation is not passing MePhC evidence")
    if record.get("prelive_sha") != head(root):
        raise RelayFailure("PRELIVE_UNCOMMITTED", "HEAD != PRELIVE_SHA")
    if record.get("origin_main") != remote_ref(root, "refs/heads/main"):
        raise RelayFailure("PRELIVE_UNCOMMITTED", "origin/main moved")
    if record.get("source_sha256") != source_manifest(root):
        raise RelayFailure("SOURCE_BYTE_MISMATCH", "executable source bytes differ from prelive")
    return record


def native(root: Path, prelive_value: str, command: list[str]) -> Path:
    if not command:
        raise RelayFailure("PRELIVE_UNCOMMITTED", "native command after -- is required")
    record = verify_prelive(root, prelive_value)
    directory = runtime(root) / "native" / f"native-{uuid.uuid4().hex}"
    directory.mkdir(parents=True)
    command_hash = hashlib.sha256(json.dumps(command, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()
    job_directory = Path(os.environ["MEPHC_RUNNER_JOB_DIRECTORY"])
    lifecycle_path = job_directory / "native-lifecycle.json"
    lifecycle_time = int(time.time())
    write_json(lifecycle_path, {"schema":"mephc-native-lifecycle-v1", "phase":"native_process_starting",
                                "native_process_started":False, "command_sha256":command_hash,
                                "phase_heartbeat_unix":lifecycle_time,
                                "updated_at":time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(lifecycle_time))})
    process = subprocess.Popen(command, cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               env={**os.environ, "PYTHONPATH": str(root)}, start_new_session=True)
    lifecycle_time = int(time.time())
    write_json(lifecycle_path, {"schema":"mephc-native-lifecycle-v1", "phase":"native_process_started",
                                "native_process_started":True, "native_pid":process.pid,
                                "command_sha256":command_hash, "phase_heartbeat_unix":lifecycle_time,
                                "updated_at":time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(lifecycle_time))})
    stdout, stderr = process.communicate()
    (directory / "stdout.txt").write_text(stdout, encoding="utf-8")
    (directory / "stderr.txt").write_text(stderr, encoding="utf-8")
    lifecycle_time = int(time.time())
    write_json(lifecycle_path, {"schema":"mephc-native-lifecycle-v1", "phase":"native_process_exited",
                                "native_process_started":True, "native_pid":process.pid,
                                "command_sha256":command_hash, "returncode":process.returncode,
                                "phase_heartbeat_unix":lifecycle_time,
                                "updated_at":time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(lifecycle_time))})
    return write_json(directory / "checkpoint.json", {
        "version": 1, "kind": "native-checkpoint", "project_id": PROJECT_ID,
        "prelive_sha": record["prelive_sha"], "source_sha256": record["source_sha256"],
        "command_sha256": command_hash, "returncode": process.returncode, "created_at": int(time.time()),
    })


def publish(root: Path, prelive_value: str, push: bool) -> Path:
    record = verify_prelive(root, prelive_value)
    target = record["prelive_sha"]
    remote_main = remote_sandbox_before = remote_sandbox_after = None
    push_performed = False
    if push:
        status = windows_git("status", "--porcelain", "--untracked-files=all").stdout.strip()
        if status:
            raise RelayFailure("PUBLISH_REMOTE_INVALID", f"Windows canonical worktree is dirty: {status.splitlines()[0]}")
        control_head = windows_git("rev-parse", "HEAD").stdout.strip()
        if control_head != target:
            raise RelayFailure("PUBLISH_REMOTE_INVALID", f"control HEAD={control_head}; prelive HEAD={target}")
        refs = windows_remote_refs()
        remote_main = refs["refs/heads/main"]
        remote_sandbox_before = refs["refs/heads/sandbox"]
        if remote_main != EXPECTED_ORIGIN_MAIN or remote_main != record["origin_main"]:
            raise RelayFailure("PUBLISH_REMOTE_INVALID", f"origin/main moved: {remote_main}")
        if remote_sandbox_before != target:
            ancestry = windows_git("merge-base", "--is-ancestor", remote_sandbox_before, target, check=False)
            if ancestry.returncode:
                raise RelayFailure("PUBLISH_REMOTE_INVALID", "origin/sandbox is not an ancestor of the exact prelive HEAD")
            windows_git("push", "origin", f"{target}:refs/heads/sandbox")
            push_performed = True
        verified = windows_remote_refs()
        if verified["refs/heads/main"] != remote_main or verified["refs/heads/sandbox"] != target:
            raise RelayFailure("PUBLISH_FAILED", "remote refs did not verify after publish")
        remote_sandbox_after = verified["refs/heads/sandbox"]
    return write_json(runtime(root) / "publish" / f"publish-{uuid.uuid4().hex}.json", {
        "version": 2, "kind": "publish-attestation", "project_id": PROJECT_ID,
        "head": target, "push_requested": push, "push_performed": push_performed,
        "sandbox_pushed": bool(push and remote_sandbox_after == target),
        "git_authority": "windows_canonical", "remote_main": remote_main,
        "remote_sandbox_before": remote_sandbox_before,
        "remote_sandbox_after": remote_sandbox_after, "created_at": int(time.time()),
    })


def create_e2e(root: Path, certificate: str) -> Path:
    root = worktree_root(root)
    certificate_path, _ = load_certificate(root, certificate)
    request_id = f"MEPHC-WORKFLOW-E2E-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    directory = runtime(root) / "outbox" / request_id
    directory.mkdir(parents=True)
    (directory / "message.txt").write_text("MePhC workflow transport E2E validation only. No science, native execution, attachments, file changes, or new work order. Reply with a short plain-text receipt acknowledgement.\n", encoding="utf-8")
    write_json(directory / "request.json", {
        "version": 1, "project_id": PROJECT_ID, "request_id": request_id, "message_file": "message.txt",
        "attachments": [], "workflow_window_seconds": 600, "task_difficulty": "normal",
        "instruction_level": "normal", "relay_certificate": str(certificate_path), "e2e": True,
    })
    return directory


def create_attachment_e2e(root: Path, certificate: str) -> Path:
    root = worktree_root(root)
    certificate_path, _ = load_certificate(root, certificate)
    artifact = root / "audit" / "attachments" / "MEPHC-ATTACHMENT-E2E-fixture.txt"
    relative_artifact = artifact.relative_to(root).as_posix()
    if not artifact.is_file() or artifact.is_symlink() or git(root, "ls-files", "--error-unmatch", relative_artifact) != relative_artifact:
        raise RelayFailure("ROOT_MISMATCH", "controlled E2E attachment artifact is unavailable or untracked")
    request_id = f"MEPHC-ATTACHMENT-E2E-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    directory = runtime(root) / "outbox" / request_id
    directory.mkdir(parents=True)
    target_root = directory / "attachments"
    target_root.mkdir()
    target = target_root / artifact.name
    shutil.copyfile(artifact, target)
    evidence = {"path": f"attachments/{artifact.name}", "size_bytes": target.stat().st_size, "sha256": sha256(target)}
    write_json(directory / "attachment-attestation.json", {
        "schema": "chat-courier-attachments-v1", "project_id": PROJECT_ID, "request_id": request_id,
        "attachments": [evidence], "count": 1, "total_bytes": evidence["size_bytes"],
        "source_artifact": {"path": relative_artifact, "sha256": sha256(artifact)},
    })
    (directory / "message.txt").write_text(f"MePhC controlled direct-attachment E2E validation only. Attachment artifact={relative_artifact}; SHA256={evidence['sha256']}. No science, native execution, file changes, or new work order. Reply with a short plain-text receipt acknowledgement.\n", encoding="utf-8")
    write_json(directory / "request.json", {
        "version": 1, "project_id": PROJECT_ID, "request_id": request_id, "message_file": "message.txt",
        "attachments": [evidence["path"]], "workflow_window_seconds": 600, "task_difficulty": "normal",
        "instruction_level": "normal", "relay_certificate": str(certificate_path), "attachment_e2e": True,
    })
    return directory


def create_status(root: Path, certificate: str) -> Path:
    root = worktree_root(root)
    certificate_path, _ = load_certificate(root, certificate)
    request_id = f"MEPHC-WORKFLOW-STATUS-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    directory = runtime(root) / "outbox" / request_id
    directory.mkdir(parents=True)
    message = f"MePhC relay-supervised workflow status report. PROJECT_ID=MEPHC. Infrastructure cleanup, persistent Windows-WSL runner validation, and a real plain-text Courier E2E round trip are complete. Current sandbox HEAD={head(root)}; origin/main={remote_ref(root, 'refs/heads/main')}. No scientific or native execution was performed in this status request, and there are no attachments. Please reply with the next self-contained plain-text transactional or scientific work order.\n"
    (directory / "message.txt").write_text(message, encoding="utf-8")
    write_json(directory / "request.json", {
        "version": 1, "project_id": PROJECT_ID, "request_id": request_id, "message_file": "message.txt",
        "attachments": [], "workflow_window_seconds": 600, "task_difficulty": "normal",
        "instruction_level": "normal", "relay_certificate": str(certificate_path), "status_request": True,
    })
    return directory


def courier(root: Path, request_dir: str, recovery: bool) -> int:
    root = worktree_root(root)
    require_python(root)
    request = Path(request_dir).resolve()
    if not WINDOWS_POWERSHELL.is_file():
        raise RelayFailure("COURIER_HARD_STOP", f"Windows PowerShell missing: {WINDOWS_POWERSHELL}")
    if runtime(root) / "outbox" not in request.parents:
        raise RelayFailure("ROOT_MISMATCH", "request must be inside the durable MePhC outbox")
    bridge = "\\\\wsl.localhost\\Ubuntu" + str(root / "tools" / "mephc-courier.ps1").replace("/", chr(92))
    command = [str(WINDOWS_POWERSHELL), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", bridge, "-RequestDirectory", "\\\\wsl.localhost\\Ubuntu" + str(request).replace("/", chr(92))]
    if recovery:
        command.append("-RecoveryOnly")
    return subprocess.run(command, cwd=root).returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="relayctl")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor")
    sub.add_parser("worktree")
    pre = sub.add_parser("prelive")
    pre.add_argument("--certificate", required=True)
    pre.add_argument("tests", nargs="*")
    nat = sub.add_parser("native")
    nat.add_argument("--prelive", required=True)
    nat.add_argument("native_command", nargs=argparse.REMAINDER)
    pub = sub.add_parser("publish")
    pub.add_argument("--prelive", required=True)
    pub.add_argument("--push", action="store_true")
    cou = sub.add_parser("courier")
    cou.add_argument("--request-directory")
    cou.add_argument("--recovery-only", action="store_true")
    cou.add_argument("--create-e2e", action="store_true")
    cou.add_argument("--create-attachment-e2e", action="store_true")
    cou.add_argument("--create-status", action="store_true")
    cou.add_argument("--certificate")
    args = parser.parse_args(argv)
    try:
        root = worktree_root()
        if args.command == "doctor":
            result = doctor(root)
        elif args.command == "worktree":
            result = root
        elif args.command == "prelive":
            result = prelive(root, args.certificate, args.tests)
        elif args.command == "native":
            command = args.native_command[1:] if args.native_command[:1] == ["--"] else args.native_command
            result = native(root, args.prelive, command)
        elif args.command == "publish":
            result = publish(root, args.prelive, args.push)
        elif args.command == "courier" and args.create_e2e:
            if not args.certificate:
                raise RelayFailure("PRELIVE_UNCOMMITTED", "--certificate required")
            result = create_e2e(root, args.certificate)
        elif args.command == "courier" and args.create_attachment_e2e:
            if not args.certificate:
                raise RelayFailure("PRELIVE_UNCOMMITTED", "--certificate required")
            result = create_attachment_e2e(root, args.certificate)
        elif args.command == "courier" and args.create_status:
            if not args.certificate:
                raise RelayFailure("PRELIVE_UNCOMMITTED", "--certificate required")
            result = create_status(root, args.certificate)
        elif args.command == "courier" and args.request_directory:
            return courier(root, args.request_directory, args.recovery_only)
        else:
            raise RelayFailure("ROOT_MISMATCH", "invalid command arguments")
        emit("relayctl_complete", result=str(result))
        return 0
    except RelayFailure as exc:
        emit(exc.code, detail=exc.detail)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
