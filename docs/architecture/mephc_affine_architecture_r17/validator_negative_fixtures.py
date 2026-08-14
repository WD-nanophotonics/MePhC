#!/usr/bin/env python3
import json, shutil, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).parent
VALIDATOR = ROOT / "validate_r17.py"

def run(case, mutate):
    with tempfile.TemporaryDirectory(prefix="r17-negative-") as td:
        target = Path(td) / "bundle"
        shutil.copytree(ROOT, target, ignore=shutil.ignore_patterns("*.pyc", "__pycache__", "logs"))
        mutate(target)
        p = subprocess.run([sys.executable, str(target / "validate_r17.py"), "--root", str(target)], text=True, capture_output=True)
        if p.returncode == 0:
            raise SystemExit(f"negative fixture unexpectedly passed: {case}")
        print(json.dumps({"case":case,"status":"REJECTED"}, sort_keys=True))

def main():
    run("phase mutation", lambda p: p.joinpath("ensemble_definition.json").write_text(json.dumps({**json.loads(p.joinpath("ensemble_definition.json").read_text()), "grid_cell_fractions":[0.125,0.25,0.625,0.875]}, indent=2), encoding="utf-8"))
    run("R16 raw-max threshold mutation", lambda p: p.joinpath("r16_uniform_max_corrective.json").write_text(json.dumps({**json.loads(p.joinpath("r16_uniform_max_corrective.json").read_text()), "literal_max_abs":0.1}, indent=2), encoding="utf-8"))
    print(json.dumps({"status":"PASS","fixtures":2}, sort_keys=True))

if __name__ == "__main__": main()
