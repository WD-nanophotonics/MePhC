"""Machine-enforced MePhC relay entry point."""
from __future__ import annotations
import argparse, hashlib, json, os
from pathlib import Path
import subprocess, sys, time, uuid
from typing import Any

CANONICAL_ROOT = Path("/home/icy/MePhC")
REQUIRED_PYTHON = Path("/home/icy/miniconda3/envs/mp/bin/python")
PROJECT_ID = "MEPHC"
FAILURE_CODES = {"ROOT_MISMATCH", "WORKTREE_NOT_WSL_NATIVE", "INTERPRETER_MISMATCH", "PRELIVE_UNCOMMITTED", "SOURCE_BYTE_MISMATCH", "COURIER_TIMEOUT_RECOVERY_REQUIRED", "COURIER_QUEUE_TIMEOUT", "COURIER_QUEUE_RECOVERY_REQUIRED", "COURIER_INTERRUPTED", "COURIER_HARD_STOP"}
class RelayFailure(RuntimeError):
    def __init__(self, code: str, detail: str): self.code, self.detail = code, detail; super().__init__(f"{code}: {detail}")
def emit(event: str, **values: Any) -> None: print(json.dumps({"event": event, "ok": event not in FAILURE_CODES, **values}, sort_keys=True), flush=True)
def run(*args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]: return subprocess.run(args, cwd=cwd, text=True, capture_output=True, check=check)
def git(root: Path, *args: str) -> str:
    try: return run("git", *args, cwd=root).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc: raise RelayFailure("ROOT_MISMATCH", str(exc)) from exc
def worktree_root(start: Path | None = None) -> Path:
    start = (start or Path.cwd()).resolve(); top = Path(git(start, "rev-parse", "--show-toplevel")).resolve(); git_dir = git(top, "rev-parse", "--git-dir")
    if top != CANONICAL_ROOT and CANONICAL_ROOT not in top.parents: raise RelayFailure("ROOT_MISMATCH", f"worktree={top}; root={CANONICAL_ROOT}")
    if not str(top).startswith("/home/icy/") or "\\" in str(top): raise RelayFailure("WORKTREE_NOT_WSL_NATIVE", f"worktree={top}")
    directory = (top / git_dir).resolve() if not Path(git_dir).is_absolute() else Path(git_dir).resolve()
    if not str(directory).startswith(str(CANONICAL_ROOT / ".git")): raise RelayFailure("WORKTREE_NOT_WSL_NATIVE", f"git_dir={directory}")
    return top
def runtime(root: Path) -> Path: path = root / ".relayctl"; path.mkdir(exist_ok=True); return path
def write_json(path: Path, data: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True); temporary = path.with_suffix(path.suffix + ".tmp"); temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8"); temporary.replace(path); return path
def read_json(path: Path, code: str = "PRELIVE_UNCOMMITTED") -> dict[str, Any]:
    try: data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc: raise RelayFailure(code, f"invalid JSON record: {path}") from exc
    if not isinstance(data, dict): raise RelayFailure(code, f"record is not an object: {path}")
    return data
def sha256(path: Path) -> str: return hashlib.sha256(path.read_bytes()).hexdigest()
def source_manifest(root: Path) -> dict[str, str]: return {name: sha256(root / name) for name in sorted(filter(None, git(root, "ls-files", "--", "*.py", "*.sh", "*.ps1", "pyproject.toml").splitlines()))}
def clean(root: Path) -> None:
    dirty = git(root, "status", "--porcelain", "--untracked-files=all")
    if dirty: raise RelayFailure("PRELIVE_UNCOMMITTED", f"dirty worktree: {dirty.splitlines()[0]}")
def head(root: Path) -> str: return git(root, "rev-parse", "HEAD")
def remote_ref(root: Path, ref: str) -> str:
    result = run("git", "ls-remote", "origin", ref, cwd=root, check=False); lines = result.stdout.strip().splitlines()
    if result.returncode or not lines: raise RelayFailure("ROOT_MISMATCH", f"cannot resolve origin {ref}: {result.stderr.strip()}")
    return lines[0].split()[0]
def require_python(root: Path) -> None:
    actual = Path(sys.executable).resolve()
    if actual != REQUIRED_PYTHON.resolve() or not REQUIRED_PYTHON.is_file(): raise RelayFailure("INTERPRETER_MISMATCH", f"actual={actual}; required={REQUIRED_PYTHON}")
    if root.resolve() not in [Path(p).resolve() for p in os.environ.get("PYTHONPATH", "").split(os.pathsep) if p]: raise RelayFailure("INTERPRETER_MISMATCH", f"PYTHONPATH must include {root}")
def load_certificate(root: Path, value: str) -> tuple[Path, dict[str, Any]]:
    path = Path(value) if Path(value).is_absolute() else runtime(root) / "certificates" / value; record = read_json(path)
    if record.get("project_id") != PROJECT_ID or record.get("worktree") != str(root): raise RelayFailure("ROOT_MISMATCH", "certificate does not bind this worktree")
    return path, record
def doctor(root: Path) -> Path:
    root = worktree_root(root); require_python(root)
    record = {"version": 1, "kind": "runtime-certificate", "project_id": PROJECT_ID, "certificate_id": f"doctor-{uuid.uuid4().hex}", "created_at": int(time.time()), "canonical_root": str(CANONICAL_ROOT), "worktree": str(root), "head": head(root), "python": str(Path(sys.executable).resolve()), "pythonpath": os.environ["PYTHONPATH"], "origin_main": remote_ref(root, "refs/heads/main"), "origin_sandbox": remote_ref(root, "refs/heads/sandbox"), "courier_request_root": str(runtime(root) / "outbox"), "dependencies": {n: __import__(n).__version__ for n in ("numpy", "scipy", "shapely")}}
    return write_json(runtime(root) / "certificates" / f"{record['certificate_id']}.json", record)
def prelive(root: Path, certificate: str, tests: list[str]) -> Path:
    root = worktree_root(root); require_python(root); clean(root); certificate_path, cert = load_certificate(root, certificate)
    if cert.get("head") != head(root): raise RelayFailure("PRELIVE_UNCOMMITTED", "doctor certificate HEAD differs")
    command = [str(REQUIRED_PYTHON), "-m", "pytest", *(tests or ["tests/test_relayctl.py"])]; result = subprocess.run(command, cwd=root, text=True, capture_output=True, env={**os.environ, "PYTHONPATH": str(root)})
    record = {"version": 1, "kind": "prelive-attestation", "project_id": PROJECT_ID, "prelive_id": f"prelive-{uuid.uuid4().hex}", "created_at": int(time.time()), "certificate": str(certificate_path), "prelive_sha": head(root), "origin_main": cert["origin_main"], "source_sha256": source_manifest(root), "tests": command, "test_returncode": result.returncode, "test_stdout_sha256": hashlib.sha256(result.stdout.encode()).hexdigest(), "test_stderr_sha256": hashlib.sha256(result.stderr.encode()).hexdigest()}
    path = write_json(runtime(root) / "prelive" / f"{record['prelive_id']}.json", record)
    if result.returncode: raise RelayFailure("PRELIVE_UNCOMMITTED", f"tests failed: {path}")
    return path
def verify_prelive(root: Path, value: str) -> dict[str, Any]:
    root = worktree_root(root); require_python(root); clean(root); path = Path(value) if Path(value).is_absolute() else runtime(root) / "prelive" / value; record = read_json(path)
    if record.get("kind") != "prelive-attestation" or record.get("project_id") != PROJECT_ID or record.get("test_returncode") != 0: raise RelayFailure("PRELIVE_UNCOMMITTED", "prelive attestation is not passing MePhC evidence")
    if record.get("prelive_sha") != head(root): raise RelayFailure("PRELIVE_UNCOMMITTED", "HEAD != PRELIVE_SHA")
    if record.get("origin_main") != remote_ref(root, "refs/heads/main"): raise RelayFailure("PRELIVE_UNCOMMITTED", "origin/main moved")
    if record.get("source_sha256") != source_manifest(root): raise RelayFailure("SOURCE_BYTE_MISMATCH", "executable source bytes differ from prelive")
    return record
def native(root: Path, prelive_value: str, command: list[str]) -> Path:
    if not command: raise RelayFailure("PRELIVE_UNCOMMITTED", "native command after -- is required")
    record = verify_prelive(root, prelive_value); directory = runtime(root) / "native" / f"native-{uuid.uuid4().hex}"; directory.mkdir(parents=True); result = subprocess.run(command, cwd=root, text=True, capture_output=True, env={**os.environ, "PYTHONPATH": str(root)})
    (directory / "stdout.txt").write_text(result.stdout, encoding="utf-8"); (directory / "stderr.txt").write_text(result.stderr, encoding="utf-8")
    return write_json(directory / "checkpoint.json", {"version": 1, "kind": "native-checkpoint", "project_id": PROJECT_ID, "prelive_sha": record["prelive_sha"], "source_sha256": record["source_sha256"], "command": command, "returncode": result.returncode, "created_at": int(time.time())})
def publish(root: Path, prelive_value: str, push: bool) -> Path:
    record = verify_prelive(root, prelive_value)
    if push:
        result = run("git", "push", "origin", "HEAD:refs/heads/sandbox", cwd=root, check=False)
        if result.returncode: raise RelayFailure("PRELIVE_UNCOMMITTED", f"sandbox push failed: {result.stderr.strip()}")
    return write_json(runtime(root) / "publish" / f"publish-{uuid.uuid4().hex}.json", {"version": 1, "kind": "publish-attestation", "project_id": PROJECT_ID, "head": record["prelive_sha"], "sandbox_pushed": push, "created_at": int(time.time())})
def create_e2e(root: Path, certificate: str) -> Path:
    root = worktree_root(root); certificate_path, _ = load_certificate(root, certificate); request_id = f"MEPHC-WORKFLOW-E2E-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"; directory = runtime(root) / "outbox" / request_id; directory.mkdir(parents=True)
    (directory / "message.txt").write_text("MePhC workflow transport E2E validation only. No science, native execution, attachments, file changes, or new work order. Reply with a short plain-text receipt acknowledgement.\n", encoding="utf-8")
    write_json(directory / "request.json", {"version": 1, "project_id": PROJECT_ID, "request_id": request_id, "message_file": "message.txt", "attachments": [], "workflow_window_seconds": 600, "task_difficulty": "normal", "instruction_level": "normal", "relay_certificate": str(certificate_path), "e2e": True}); return directory
def courier(root: Path, request_dir: str, recovery: bool) -> int:
    root = worktree_root(root); require_python(root); request = Path(request_dir).resolve()
    if runtime(root) / "outbox" not in request.parents: raise RelayFailure("ROOT_MISMATCH", "request must be inside .relayctl/outbox")
    bridge = "\\\\wsl.localhost\\Ubuntu" + str(root / "tools" / "mephc-courier.ps1").replace("/", chr(92))
    command = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", bridge, "-RequestDirectory", "\\\\wsl.localhost\\Ubuntu" + str(request).replace("/", chr(92))]
    if recovery: command.append("-RecoveryOnly")
    return subprocess.run(command, cwd=root).returncode
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="relayctl"); sub = parser.add_subparsers(dest="command", required=True); sub.add_parser("doctor"); sub.add_parser("worktree")
    pre = sub.add_parser("prelive"); pre.add_argument("--certificate", required=True); pre.add_argument("tests", nargs="*")
    nat = sub.add_parser("native"); nat.add_argument("--prelive", required=True); nat.add_argument("native_command", nargs=argparse.REMAINDER)
    pub = sub.add_parser("publish"); pub.add_argument("--prelive", required=True); pub.add_argument("--push", action="store_true")
    cou = sub.add_parser("courier"); cou.add_argument("--request-directory"); cou.add_argument("--recovery-only", action="store_true"); cou.add_argument("--create-e2e", action="store_true"); cou.add_argument("--certificate")
    args = parser.parse_args(argv)
    try:
        root = worktree_root()
        if args.command == "doctor": result = doctor(root)
        elif args.command == "worktree": result = root
        elif args.command == "prelive": result = prelive(root, args.certificate, args.tests)
        elif args.command == "native": result = native(root, args.prelive, args.native_command[1:] if args.native_command[:1] == ["--"] else args.native_command)
        elif args.command == "publish": result = publish(root, args.prelive, args.push)
        elif args.command == "courier" and args.create_e2e:
            if not args.certificate: raise RelayFailure("PRELIVE_UNCOMMITTED", "--certificate required")
            result = create_e2e(root, args.certificate)
        elif args.command == "courier" and args.request_directory: return courier(root, args.request_directory, args.recovery_only)
        else: raise RelayFailure("ROOT_MISMATCH", "invalid command arguments")
        emit("relayctl_complete", result=str(result)); return 0
    except RelayFailure as exc: emit(exc.code, detail=exc.detail); return 2
if __name__ == "__main__": raise SystemExit(main())
