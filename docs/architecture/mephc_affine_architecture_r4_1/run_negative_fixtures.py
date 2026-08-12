"""Real subprocess negative fixtures for the public R4.1 validator."""
from __future__ import annotations
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VALIDATOR = ROOT / "validate_r4_1.py"

def load(path):
    return json.loads(path.read_text(encoding="utf-8"))

def save(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")

def manifest(root):
    excluded = {"artifact_manifest.json", "completion.json"}
    entries = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name in excluded or "__pycache__" in path.parts:
            continue
        data = path.read_bytes()
        entries[path.relative_to(root).as_posix()] = {
            "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)
        }
    value = {
        "schema": "mephc.r4_1.artifact_manifest.v1",
        "algorithm": "sha256",
        "excludes": ["artifact_manifest.json", "completion.json", "__pycache__"],
        "artifacts": entries,
    }
    save(root / "artifact_manifest.json", value)

def run_case(name, mutate, expected):
    with tempfile.TemporaryDirectory(prefix="r41-fixture-") as temp:
        case = Path(temp) / "bundle"
        shutil.copytree(ROOT, case, ignore=shutil.ignore_patterns("__pycache__"))
        mutate(case)
        command = [sys.executable, str(VALIDATOR), "--check-bundle", "--bundle-root", str(case)]
        result = subprocess.run(command, text=True, capture_output=True, check=False)
        marker = next((line for line in result.stdout.splitlines() if "R4.1 FAIL " in line), "")
        observed = marker.split("R4.1 FAIL ", 1)[1].split(":", 1)[0] if marker else ""
        return {
            "id": name,
            "command": "python validate_r4_1.py --check-bundle --bundle-root <isolated-fixture>",
            "exit_code": result.returncode,
            "observed_code": observed,
            "expected_code": expected,
            "stdout_sha256": hashlib.sha256(result.stdout.encode()).hexdigest(),
            "stderr_sha256": hashlib.sha256(result.stderr.encode()).hexdigest(),
            "status": result.returncode != 0 and observed == expected,
        }

def edit_completion(case, fn):
    path = case / "completion.json"
    value = load(path)
    fn(value)
    save(path, value)
    manifest(case)

def main():
    seed = {"schema": "mephc.r4_1.negative_fixture_results.v1", "count": 19, "all_passed": True, "fixtures": [{"id": f"seed_{i}", "status": True} for i in range(19)]}
    save(ROOT / "negative_fixture_results.json", seed)
    manifest(ROOT)
    cases = []
    cases.append(run_case("missing_required_artifact", lambda c: (c / "README.md").unlink(), "E_REQUIRED_ARTIFACT"))
    def omission(c):
        m = load(c / "artifact_manifest.json"); m["artifacts"].pop("README.md"); save(c / "artifact_manifest.json", m)
    cases.append(run_case("manifest_payload_omission", omission, "E_MANIFEST_OMISSION"))
    cases.append(run_case("manifest_digest_mismatch", lambda c: (c / "README.md").write_text("changed\n"), "E_MANIFEST_DIGEST_MISMATCH"))
    cases.append(run_case("stale_required_check_set", lambda c: edit_completion(c, lambda v: v["validator_summary"]["required_checks"].pop()), "E_REQUIRED_CHECK_SET"))
    cases.append(run_case("completed_with_required_failure", lambda c: edit_completion(c, lambda v: v["gates"].update({"portable_commands": "FAIL"})), "E_COMPLETED_WITH_REQUIRED_FAILURE"))
    cases.append(run_case("c4_pass_without_verifier_evidence", lambda c: edit_completion(c, lambda v: v.update({"c4_verifier_evidence": False})), "E_C4_EVIDENCE"))
    cases.append(run_case("nonidentity_false_c4_claim", lambda c: edit_completion(c, lambda v: v["c4_policy"].update({"nonidentity_auto_mode": "c4q"})), "E_NONIDENTITY_FALSE_C4_CLAIM"))
    cases.append(run_case("nonidentity_false_gxm_claim", lambda c: edit_completion(c, lambda v: v["workflow_policy"].update({"nonidentity_band_path": "gxm"})), "E_NONIDENTITY_FALSE_GXM_CLAIM"))
    cases.append(run_case("nonidentity_fixed_square_domain_claim", lambda c: edit_completion(c, lambda v: v["workflow_policy"].update({"nonidentity_sampling": "fixed_square"})), "E_NONIDENTITY_FIXED_SQUARE_DOMAIN"))
    def missing_smoke(c):
        value = load(c / "test_and_smoke_summary.json"); value["smokes"].pop(); save(c / "test_and_smoke_summary.json", value); manifest(c)
    cases.append(run_case("missing_required_smoke", missing_smoke, "E_REQUIRED_SMOKE"))
    def missing_assertion(c):
        value = load(c / "test_and_smoke_summary.json"); value["smokes"][0]["assertions"] = {}; save(c / "test_and_smoke_summary.json", value); manifest(c)
    cases.append(run_case("missing_smoke_assertion", missing_assertion, "E_SMOKE_ASSERTION"))
    def false_assertion(c):
        value = load(c / "test_and_smoke_summary.json"); next(iter(value["smokes"][0]["assertions"])) and value["smokes"][0]["assertions"].__setitem__(next(iter(value["smokes"][0]["assertions"])), False); save(c / "test_and_smoke_summary.json", value); manifest(c)
    cases.append(run_case("false_smoke_assertion", false_assertion, "E_SMOKE_ASSERTION_FALSE"))
    def empty_log(c):
        path = c / "logs" / "smoke_band_identity.log"; path.write_text(""); manifest(c)
    cases.append(run_case("missing_or_empty_smoke_log", empty_log, "E_SMOKE_LOG"))
    def unsafe(c):
        value = load(c / "test_and_smoke_summary.json"); value["smokes"][0]["command"] = "python /home/icy/private_driver.py"; save(c / "test_and_smoke_summary.json", value); manifest(c)
    cases.append(run_case("unsafe_reproducibility_path", unsafe, "E_UNSAFE_REPRODUCIBILITY_PATH"))
    def immutable(c):
        value = load(c / "immutable_r4_inputs.json"); value["tree_sha256"] = "0" * 64; save(c / "immutable_r4_inputs.json", value); manifest(c)
    cases.append(run_case("immutable_r4_digest_changed", immutable, "E_IMMUTABLE_R4_DIGEST_CHANGED"))
    cases.append(run_case("trilatt_hold_ref_changed", lambda c: edit_completion(c, lambda v: v.update({"trilatt_hold_ref": "0" * 40})), "E_TRILATT_HOLD_REF"))
    cases.append(run_case("payload_not_seal_parent", lambda c: edit_completion(c, lambda v: v["seal"].update({"payload_ref": "0" * 40})), "E_PAYLOAD_NOT_SEAL_PARENT"))
    cases.append(run_case("seal_forbidden_path", lambda c: edit_completion(c, lambda v: v["seal"]["diff_paths"].append("mephc/workflows.py")), "E_SEAL_FORBIDDEN_PATH"))
    cases.append(run_live_remote_fixture())
    result = {"schema": "mephc.r4_1.negative_fixture_results.v1", "count": len(cases), "all_passed": all(item["status"] for item in cases), "fixtures": cases}
    save(ROOT / "negative_fixture_results.json", result)
    manifest(ROOT)
    print(json.dumps(result, indent=2))
    return 0 if result["all_passed"] and len(cases) >= 19 else 1

def run_live_remote_fixture():
    with tempfile.TemporaryDirectory(prefix="r41-live-") as temp:
        temp = Path(temp)
        roots = {}
        sources = {
            "mephc": ROOT.parents[2],
            "sqrlatt": ROOT.parents[3] / "SqrLatt",
            "trilatt": ROOT.parents[3] / "TriLatt",
        }
        for name, source in sources.items():
            dest = temp / name
            subprocess.run(["git", "clone", "--no-local", str(source), str(dest)], check=True, capture_output=True, text=True)
            roots[name] = dest
        subprocess.run(["git", "-C", str(roots["mephc"]), "remote", "set-url", "origin", "https://example.invalid/wrong.git"], check=True)
        mephc_ref = subprocess.check_output(["git", "-C", str(roots["mephc"]), "rev-parse", "HEAD"], text=True).strip()
        payload_ref = subprocess.check_output(["git", "-C", str(roots["mephc"]), "rev-parse", "HEAD^"], text=True).strip()
        command = [sys.executable, str(VALIDATOR), "--check-worktrees", "--bundle-root", str(ROOT),
                   "--mephc-root", str(roots["mephc"]), "--sqrlatt-root", str(roots["sqrlatt"]),
                   "--trilatt-root", str(roots["trilatt"]), "--expected-mephc-ref", mephc_ref,
                   "--expected-payload-ref", payload_ref]
        result = subprocess.run(command, text=True, capture_output=True, check=False)
        marker = next((line for line in result.stdout.splitlines() if "R4.1 FAIL " in line), "")
        observed = marker.split("R4.1 FAIL ", 1)[1].split(":", 1)[0] if marker else ""
        return {"id": "repository_remote_mismatch", "command": "python validate_r4_1.py --check-worktrees <explicit-temporary-roots>", "exit_code": result.returncode, "observed_code": observed, "expected_code": "E_REMOTE_IDENTITY", "stdout_sha256": hashlib.sha256(result.stdout.encode()).hexdigest(), "stderr_sha256": hashlib.sha256(result.stderr.encode()).hexdigest(), "status": result.returncode != 0 and observed == "E_REMOTE_IDENTITY"}

if __name__ == "__main__":
    raise SystemExit(main())
