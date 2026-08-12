from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path


ARTIFACT = Path(__file__).resolve().parent
ENTRY_MEPHC = "24e29d9c9c6ceae979e1a81953c4f54853f98808"
ENTRY_TRILATT = "df2cdf4fd70e741e1a8901a9274a0b0e42b1e737"
ENTRY_SQRLATT = "8a1e4534a48e01a83996fb199ccd55e0983e72b2"


def load(name: str):
    return json.loads((ARTIFACT / name).read_text(encoding="utf-8"))


def git(repo: str, *args: str) -> str:
    return subprocess.check_output(["git", "-C", repo, *args], text=True).strip()


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def fail(message: str) -> None:
    print(f"R3.1 VALIDATION FAIL: {message}", file=sys.stderr)
    raise SystemExit(1)


def main() -> None:
    required = [
        "README.md", "baseline.json", "change_scope.json", "geometry_validation.json",
        "k_landmark_validation.json", "entrypoint_smoke.json", "test_runs.json",
        "integrity_digests.json", "validation_report.md", "artifact_manifest.json",
        "completion.json", "validate_r3_1.py",
    ]
    for name in required:
        if not (ARTIFACT / name).is_file():
            fail(f"missing artifact {name}")
    if not (ARTIFACT / "logs").is_dir() or not list((ARTIFACT / "logs").glob("*.log")):
        fail("logs directory is empty")

    baseline = load("baseline.json")
    entry_refs = {
        "MePhC": baseline["repositories"]["MePhC"]["head_before"],
        "TriLatt": baseline["repositories"]["MePhC-TriLatt"]["head_before"],
        "SqrLatt": baseline["repositories"]["MePhC-SqrLatt"]["head_before"],
    }
    if entry_refs["MePhC"] != ENTRY_MEPHC or entry_refs["TriLatt"] != ENTRY_TRILATT:
        fail("entry refs do not match contract")
    if entry_refs["SqrLatt"] != ENTRY_SQRLATT:
        fail("SqrLatt entry ref changed")

    geometry = load("geometry_validation.json")
    if not geometry.get("all_passed") or not all(item["passed"] for item in geometry["cases"]):
        fail("geometry validation is not PASS")
    landmark = load("k_landmark_validation.json")
    if not landmark.get("all_passed") or not all(item["passed"] for item in landmark["cases"]):
        fail("landmark validation is not PASS")
    smoke = load("entrypoint_smoke.json")
    if smoke.get("status") != "PASS" or any(item.get("status") != "PASS" for item in smoke["entries"].values()):
        fail("entrypoint smoke is not PASS")
    tests = load("test_runs.json")
    if not tests.get("all_exit_codes_zero"):
        fail("a test command failed")
    if any(item["exit_code"] != 0 for item in tests["commands"]):
        fail("test command exit code is nonzero")

    scope = load("change_scope.json")
    if any(not repo.get("allowlist_passed") for repo in scope.values()):
        fail("change scope is not PASS")
    completion = load("completion.json")
    if completion.get("status") != "PASS" or completion.get("r4_authorized") is not False:
        fail("completion status or R4 authorization is invalid")
    if completion.get("independent_review_required") is not True:
        fail("independent review flag missing")
    gates = completion.get("defect_gates", {})
    if set(gates) != {"A", "B", "C", "D"} or any(value != "PASS" for value in gates.values()):
        fail("defect gates are not all PASS")

    digests = load("integrity_digests.json")
    if digests.get("protected_changed", False):
        fail("protected artifacts changed")

    manifest = load("artifact_manifest.json")
    if manifest.get("status") != "PASS":
        fail("artifact manifest is not PASS")
    for item in manifest.get("artifacts", []):
        path = ARTIFACT / item["path"]
        if not path.is_file() or sha256(path) != item["sha256"]:
            fail(f"artifact digest mismatch: {item['path']}")

    print("R3.1 VALIDATION PASS")
    print(json.dumps({
        "mephc_head": git("/home/icy/MePhC", "rev-parse", "HEAD"),
        "trilatt_head": git("/home/icy/TriLatt", "rev-parse", "HEAD"),
        "sqrlatt_head": git("/home/icy/SqrLatt", "rev-parse", "HEAD"),
        "test_counts": tests["test_counts"],
        "artifact_count": len(manifest["artifacts"]),
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
