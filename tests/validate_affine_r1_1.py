"""Deterministic validator for the MePhC R1.1 delivery artifacts."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import subprocess

from audit.infrastructure.campaign_runtime import resolve_sibling_repo


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = ROOT / "docs" / "architecture" / "mephc_affine_architecture_r1"
TRILATT = resolve_sibling_repo(ROOT, "TriLatt")
SQRLATT = resolve_sibling_repo(ROOT, "SqrLatt")
BASE_COMMIT = "ec8a4ec8ec1ffd5db01e60c5e008a2af67c50ffb"
REQUIRED = {
    "README.md",
    "current_architecture.md",
    "dependency_graph.mmd",
    "api_inventory.csv",
    "lattice_truth_sources.csv",
    "symmetry_assumptions.csv",
    "behavior_baseline.json",
    "characterization_matrix.md",
    "migration_contract.md",
    "open_questions.md",
    "artifact_manifest.json",
    "completion.json",
}
CSV_HEADERS = {
    "api_inventory.csv": ["repository", "module", "symbol", "classification", "defined_at", "consumers", "behavior_notes", "migration_risk"],
    "lattice_truth_sources.csv": ["concept", "repository", "defined_at", "representation", "consumers", "duplicates", "consistency_risk", "evidence"],
    "symmetry_assumptions.csv": ["location", "decision", "input_checked", "assumption", "downstream_effect", "validity_boundary", "test_coverage"],
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_files(repo: Path) -> list[str]:
    output = subprocess.check_output(["git", "-C", str(repo), "ls-files"], text=True)
    return [line for line in output.splitlines() if line]


def tree_digest(repo: Path, excluded_prefixes: tuple[str, ...]) -> str:
    digest = hashlib.sha256()
    for relative in sorted(git_files(repo)):
        if any(relative == prefix or relative.startswith(prefix) for prefix in excluded_prefixes):
            continue
        path = repo / relative
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def evidence_digest(repositories: list[Path]) -> str:
    digest = hashlib.sha256()
    for repo in repositories:
        for relative in sorted(git_files(repo)):
            if not relative.startswith(("data/", "image/", "diagnostics/")):
                continue
            digest.update(f"{repo.name}/{relative}".encode("utf-8"))
            digest.update(b"\0")
            digest.update((repo / relative).read_bytes())
            digest.update(b"\0")
    return digest.hexdigest()


def assert_git_unchanged(repo: Path, base: str, paths: list[str]) -> None:
    result = subprocess.run(["git", "-C", str(repo), "diff", "--quiet", base, "--", *paths])
    if result.returncode != 0:
        raise AssertionError(f"tracked bytes changed in {repo}: {paths}")


def main() -> int:
    files = {path.name for path in ARTIFACT_ROOT.iterdir() if path.is_file()}
    if files != REQUIRED:
        raise AssertionError(f"unexpected artifact files: {sorted(files ^ REQUIRED)}")

    baseline = json.loads((ARTIFACT_ROOT / "behavior_baseline.json").read_text(encoding="utf-8"))
    manifest = json.loads((ARTIFACT_ROOT / "artifact_manifest.json").read_text(encoding="utf-8"))
    completion = json.loads((ARTIFACT_ROOT / "completion.json").read_text(encoding="utf-8"))
    if manifest["self_entry_policy"] != "excluded-recursive-self-hash":
        raise AssertionError("manifest self-entry policy is not explicit")
    if manifest["reverse_reference_exclusions"] != ["completion.json"]:
        raise AssertionError("completion reverse-reference exclusion is not explicit")
    for name, header in CSV_HEADERS.items():
        with (ARTIFACT_ROOT / name).open(newline="", encoding="utf-8") as handle:
            if next(csv.reader(handle)) != header:
                raise AssertionError(f"CSV header mismatch: {name}")

    expected_entries = {
        f"docs/architecture/mephc_affine_architecture_r1/{name}"
        for name in REQUIRED
        if name not in {"artifact_manifest.json", "completion.json"}
    }
    expected_entries |= {
        "tests/test_affine_characterization.py",
        "tests/validate_affine_r1_1.py",
    }
    entries = {entry["path"] for entry in manifest["artifact_files"]}
    if entries != expected_entries:
        raise AssertionError(f"manifest coverage mismatch: {sorted(entries ^ expected_entries)}")
    for entry in manifest["artifact_files"]:
        path = ROOT / entry["path"]
        if not path.is_file() or sha256(path) != entry["sha256"]:
            raise AssertionError(f"manifest hash mismatch: {entry['path']}")

    if completion["contract_id"] != "mephc-affine-architecture-r1.1-delivery-v1":
        raise AssertionError("completion contract id mismatch")
    if completion["task_id"] != "mephc-affine-architecture-r1.1-corrective":
        raise AssertionError("completion task id mismatch")
    if {item["lock_id"] for item in completion["characterization"]} != {f"LOCK-{i:02d}" for i in range(1, 11)}:
        raise AssertionError("completion lock coverage mismatch")

    runtime_after = tree_digest(ROOT, ("tests/", "docs/architecture/mephc_affine_architecture_r1/"))
    if runtime_after != baseline["r1_1_integrity"]["runtime_tree_digest_before"]:
        raise AssertionError("runtime tree digest changed from R1.1 preflight")
    evidence_after = evidence_digest([ROOT, TRILATT, SQRLATT])
    if evidence_after != baseline["r1_1_integrity"]["existing_evidence_digest_before"]:
        raise AssertionError("existing scientific evidence digest changed from R1.1 preflight")
    if completion["integrity"]["runtime_tree_digest_after"] != runtime_after:
        raise AssertionError("completion runtime digest mismatch")
    if completion["integrity"]["existing_evidence_digest_after"] != evidence_after:
        raise AssertionError("completion evidence digest mismatch")

    assert_git_unchanged(ROOT, BASE_COMMIT, ["mephc", "examples", "legacy", "README.md", "pyproject.toml", ".vscode"])
    assert_git_unchanged(TRILATT, baseline["preflight"]["MePhC-TriLatt"]["head_before"], ["."])
    assert_git_unchanged(SQRLATT, baseline["preflight"]["MePhC-SqrLatt"]["head_before"], ["."])

    if sha256(ARTIFACT_ROOT / "artifact_manifest.json") != completion["integrity"]["artifact_manifest_sha256"]:
        raise AssertionError("artifact manifest SHA-256 mismatch")
    print("R1.1 artifact validation: ok")
    print(f"runtime_tree_digest={runtime_after}")
    print(f"artifact_manifest_sha256={sha256(ARTIFACT_ROOT / 'artifact_manifest.json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
