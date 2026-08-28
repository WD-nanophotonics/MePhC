#!/home/icy/miniconda3/envs/mp/bin/python
"""Fixed WSL-side foreground process recorder used by mephc-flow."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path


def atomic(path: Path, value: dict) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True)
    parser.add_argument("--checkout", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("argv", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    argv = args.argv[1:] if args.argv and args.argv[0] == "--" else args.argv
    state_path = Path(args.state)
    value = json.loads(state_path.read_text(encoding="utf-8"))
    environment = os.environ.copy()
    environment["PATH"] = "/home/icy/miniconda3/envs/mp/bin:" + environment.get("PATH", "")
    environment["PYTHONPATH"] = args.checkout
    environment["MEPHC_SOURCE_COMMIT"] = Path(args.checkout).name
    process = subprocess.Popen(argv, cwd=args.project, env=environment, shell=False)
    stat = Path(f"/proc/{process.pid}/stat").read_text(encoding="ascii").split()
    value.update({"state": "running", "process_started": True, "pid": process.pid,
                  "linux_start_ticks": stat[21], "started_at": time.time()})
    atomic(state_path, value)
    return_code = process.wait()
    value.update({"state": "succeeded" if return_code == 0 else "failed",
                  "return_code": return_code, "completed_at": time.time()})
    atomic(state_path, value)
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
