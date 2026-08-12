"""Deterministic R5.1 evidence and final-ref validator."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parent
HEX40 = re.compile(r"^[0-9a-f]{40}$")
STARTING_REFS = {
    "MePhC": "d6d3934399d9473a6ded043f0032646804751d6a",
    "MePhC-SqrLatt": "e2b417ac9065b1d627b68731163861d7d38da546",
    "MePhC-TriLatt": "0f0d1dfc3129da22b25229ecd9eee136e13a1dfb",
}
REQUIRED = {
    "README.md", "preflight.json", "runtime_probe.json", "solver_smokes.json",
    "validation_report.md", "change_scope.json", "validate_r5_1.py",
    "artifact_manifest.json", "completion.json",
}


def fail(message: str) -> None:
    raise RuntimeError("R5.1 VALIDATION FAIL: " + message)


def load(name: str):
    path = ROOT / name
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        fail(f"invalid {name}: {exc}")


def digest(path: Path) -> tuple[str, int]:
    data = path.read_bytes()
    return hashlib.sha256(data).hexdigest(), len(data)


def payload_files() -> list[Path]:
    return sorted(
        path for path in ROOT.rglob("*")
        if path.is_file()
        and path.name not in {"artifact_manifest.json", "completion.json"}
        and "__pycache__" not in path.parts
    )


def check_logs(smokes: dict) -> None:
    control = smokes.get("r4_control", {})
    if control.get("status") != "PASS" or control.get("exit_code") != 0:
        fail("R4 control is not PASS")
    control_log = ROOT / control.get("log_path", "")
    if not control_log.is_file() or control_log.stat().st_size == 0:
        fail("R4 control has no log")
    for item in smokes.get("smokes", []):
        log = ROOT / item.get("log_path", "")
        if not log.is_file() or log.stat().st_size == 0:
            fail(f"missing smoke log: {item.get('id')}")
        text = log.read_text(encoding="utf-8", errors="replace").lower()
        if "mock" in text or "fake" in text:
            fail(f"mock/fake solver evidence: {item.get('id')}")


def check_smokes() -> None:
    data = load("solver_smokes.json")
    if data.get("status") != "PASS":
        fail("solver_smokes status")
    runtime = data.get("runtime", {})
    if runtime.get("interpreter") != "/home/icy/miniconda3/envs/mp/bin/python":
        fail("wrong selected interpreter")
    if not runtime.get("modesolver_available"):
        fail("ModeSolver is unavailable")
    for origin_key in ("meep_origin", "mpb_origin"):
        if "/site-packages/meep" not in str(runtime.get(origin_key, "")):
            fail(f"missing real import origin: {origin_key}")
    smokes = data.get("smokes", [])
    if {item.get("case") for item in smokes} != {"SqrLatt", "TriLatt"}:
        fail("required downstream smoke cases")
    for item in smokes:
        if item.get("status") != "PASS" or item.get("exit_code") != 0:
            fail(f"non-PASS smoke: {item.get('id')}")
        if item.get("solver") != "meep.mpb.ModeSolver":
            fail(f"not a real MPB solver: {item.get('id')}")
        if item.get("frequencies_shape") != [1] or item.get("finite_output") is not True:
            fail(f"invalid numerical output: {item.get('id')}")
        parameters = item.get("parameters", {})
        if parameters.get("semantic_label") != "supercell_gamma_only":
            fail(f"missing supercell semantics: {item.get('id')}")
        if parameters.get("primitive_labels_allowed") is not False:
            fail(f"primitive labels enabled: {item.get('id')}")
        if parameters.get("primitive_symmetry_reduction") is not False:
            fail(f"primitive symmetry enabled: {item.get('id')}")
        if parameters.get("unfolding") is not False or parameters.get("berry_or_efs_interpretation") is not False:
            fail(f"forbidden interpretation enabled: {item.get('id')}")
        field = item.get("field", {})
        if field.get("capability") != "SUPERCELL_PERIODIC" or field.get("verified") is not True:
            fail(f"unverified supercell field: {item.get('id')}")
        if not field.get("stable_id") or not item.get("pattern_polygon_count", 0):
            fail(f"missing stable field/pattern: {item.get('id')}")
    check_logs(data)


def check_manifest() -> None:
    manifest = load("artifact_manifest.json")
    if manifest.get("status") != "SEALED":
        fail("manifest is not sealed")
    actual = {path.relative_to(ROOT).as_posix() for path in payload_files()}
    listed = set(manifest.get("artifacts", {}))
    if actual != listed:
        fail(f"manifest file set mismatch missing={sorted(actual-listed)} extra={sorted(listed-actual)}")
    for path in payload_files():
        rel = path.relative_to(ROOT).as_posix()
        sha, size = digest(path)
        entry = manifest["artifacts"].get(rel, {})
        if entry.get("sha256") != sha or entry.get("size") != size:
            fail(f"manifest digest mismatch: {rel}")


def git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *args], text=True, capture_output=True, check=False)
    if result.returncode:
        fail(f"git command failed: {' '.join(args)}")
    return result.stdout.strip()


def check_final_refs(roots: dict[str, Path]) -> None:
    completion = load("completion.json")
    final = completion.get("final_refs", {})
    if set(final) != set(STARTING_REFS) or not all(HEX40.fullmatch(value) for value in final.values()):
        fail("final refs are missing or malformed")
    for name, root in roots.items():
        head = git(root, "rev-parse", "HEAD")
        remote = git(root, "rev-parse", "origin/main")
        payload_parent = completion.get("seal", {}).get("payload_parent") if name == "MePhC" else final[name]
        if head != remote or (name != "MePhC" and head != payload_parent):
            fail(f"remote equality mismatch: {name}")
        if name == "MePhC" and git(root, "merge-base", payload_parent, head) != payload_parent:
            fail("MePhC payload parent is not an ancestor of final seal")
        if git(root, "status", "--short", "--untracked-files=all"):
            fail(f"dirty final worktree: {name}")
    allowed = {
        "MePhC": {"docs/architecture/mephc_affine_architecture_r5_1"},
        "MePhC-SqrLatt": set(),
        "MePhC-TriLatt": {"r5_deformation.py", "README.md", ".vscode/launch.json", ".vscode/settings.json"},
    }
    for name, root in roots.items():
        changed = set(git(root, "diff", "--name-only", STARTING_REFS[name], final[name]).splitlines())
        if name == "MePhC":
            bad = [path for path in changed if not path.startswith("docs/architecture/mephc_affine_architecture_r5_1/")]
        else:
            bad = sorted(changed - allowed[name])
        if bad:
            fail(f"production path outside R5.1 scope: {name} {bad}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-bundle", action="store_true")
    parser.add_argument("--mephc-root", type=Path)
    parser.add_argument("--sqrlatt-root", type=Path)
    parser.add_argument("--trilatt-root", type=Path)
    args = parser.parse_args()
    if not args.check_bundle:
        fail("use --check-bundle")
    if not REQUIRED.issubset({path.name for path in ROOT.iterdir()}):
        fail("required top-level artifacts missing")
    preflight = load("preflight.json")
    if preflight.get("starting_refs") != STARTING_REFS:
        fail("starting refs")
    probe = load("runtime_probe.json")
    if probe.get("selected_runtime") != "/home/icy/miniconda3/envs/mp/bin/python":
        fail("runtime probe selection")
    check_smokes()
    completion = load("completion.json")
    if completion.get("status") == "PASS_RUNTIME_CLOSED":
        check_manifest()
        if args.mephc_root and args.sqrlatt_root and args.trilatt_root:
            check_final_refs({
                "MePhC": args.mephc_root,
                "MePhC-SqrLatt": args.sqrlatt_root,
                "MePhC-TriLatt": args.trilatt_root,
            })
    print("R5.1 BUNDLE PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
