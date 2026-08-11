"""Machine-checkable R2 artifact and immutable-subset validator."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
R2 = ROOT / "docs" / "architecture" / "mephc_affine_architecture_r2"
R1 = ROOT / "docs" / "architecture" / "mephc_affine_architecture_r1"
TRILATT = ROOT.parent / "TriLatt"
SQRLATT = ROOT.parent / "SqrLatt"
R1_ARTIFACT_DIGEST = "115bd9ebff1d1ee9bbccfc01a18cd2272d5364733caaa31f16c63294fff33533"
SCIENTIFIC_DIGEST = "c577e8cc64a178bac3426a1e4f3a3f603f3c4b247dcf2ab44bf97cba5d6fc5c1"
SQRLATT_TREE_DIGEST = "92ea850d86ad9189f3c8e2f37446de8edfd052480c28c2722f8c46077e075e00"
R1_FILES = {"README.md", "api_inventory.csv", "artifact_manifest.json", "behavior_baseline.json", "characterization_matrix.md", "completion.json", "current_architecture.md", "dependency_graph.mmd", "lattice_truth_sources.csv", "migration_contract.md", "open_questions.md", "symmetry_assumptions.csv"}
R2_FILES = {"README.md", "r1_1_acceptance_disposition.md", "api_decisions.md", "dependency_after.mmd", "compatibility_matrix.md", "truth_source_closure.csv", "bz_algorithm.md", "validation_report.md", "r3_activation_plan.md", "artifact_manifest.json", "completion.json"}


def digest_files(root: Path, names: list[str] | set[str], prefix: str = "") -> str:
    digest = hashlib.sha256()
    for name in sorted(names):
        digest.update(f"{prefix}{name}".encode()); digest.update(b"\0")
        digest.update((root / name).read_bytes()); digest.update(b"\0")
    return digest.hexdigest()


def tracked_digest(repo: Path, prefixes: tuple[str, ...] | None = None) -> str:
    names = subprocess.check_output(["git", "-C", str(repo), "ls-files"], text=True).splitlines()
    names = [name for name in names if prefixes is None or name.startswith(prefixes)]
    return digest_files(repo, names, f"{repo.name}/")


def cross_scientific_digest() -> str:
    digest = hashlib.sha256()
    for repo in (ROOT, TRILATT, SQRLATT):
        names = subprocess.check_output(["git", "-C", str(repo), "ls-files"], text=True).splitlines()
        for name in sorted(n for n in names if n.startswith(("data/", "image/", "diagnostics/"))):
            digest.update(f"{repo.name}/{name}".encode()); digest.update(b"\0")
            digest.update((repo / name).read_bytes()); digest.update(b"\0")
    return digest.hexdigest()


def main() -> int:
    if {path.name for path in R1.iterdir() if path.is_file()} != R1_FILES:
        raise AssertionError("R1 artifact file set changed")
    if {path.name for path in R2.iterdir() if path.is_file()} != R2_FILES:
        raise AssertionError("R2 artifact file set mismatch")
    with (R2 / "truth_source_closure.csv").open(newline="", encoding="utf-8") as handle:
        if next(csv.reader(handle)) != ["truth_source_id", "concept", "repository", "location_before", "location_after", "status", "canonical_provider", "consumer", "test_node_id", "remaining_reason", "r3_disposition"]:
            raise AssertionError("truth-source CSV header mismatch")
    manifest = json.loads((R2 / "artifact_manifest.json").read_text(encoding="utf-8"))
    completion = json.loads((R2 / "completion.json").read_text(encoding="utf-8"))
    if manifest["self_entry_policy"] != "excluded-recursive-self-hash":
        raise AssertionError("manifest self-entry policy mismatch")
    if manifest["reverse_reference_exclusions"] != ["completion.json"]:
        raise AssertionError("completion reverse-reference exclusion mismatch")
    expected = {f"docs/architecture/mephc_affine_architecture_r2/{name}" for name in R2_FILES if name not in {"artifact_manifest.json", "completion.json"}}
    if {entry["path"] for entry in manifest["artifact_files"]} != expected:
        raise AssertionError("manifest coverage mismatch")
    for entry in manifest["artifact_files"]:
        path = ROOT / entry["path"]
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            raise AssertionError(f"manifest hash mismatch: {entry['path']}")
    required = {"contract_id", "task_id", "status", "repositories", "environment", "implementation_commits", "closure_commit_plan", "workstreams", "api", "truth_sources", "compatibility", "tests", "integrity", "artifacts", "r3_seams", "deviations", "blockers"}
    if not required <= completion.keys() or {item["id"] for item in completion["workstreams"]} != set("ABCDEF"):
        raise AssertionError("completion schema incomplete")
    if digest_files(R1, R1_FILES) != R1_ARTIFACT_DIGEST:
        raise AssertionError("R1 artifact bytes changed")
    if cross_scientific_digest() != SCIENTIFIC_DIGEST:
        raise AssertionError("scientific record bytes changed")
    if tracked_digest(SQRLATT) != SQRLATT_TREE_DIGEST:
        raise AssertionError("SqrLatt tree changed")
    print("R2 artifact validation: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
