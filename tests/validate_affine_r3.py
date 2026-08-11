"""Read-only validator for the MePhC affine architecture R3 delivery."""

import csv
import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = ROOT / "docs/architecture/mephc_affine_architecture_r3"
EXPECTED_ARTIFACTS = {
    "README.md",
    "r2_review_disposition.md",
    "semantic_model.md",
    "deformation_contract.md",
    "bz_invariants.md",
    "workflow_matrix.md",
    "compatibility_matrix.md",
    "validation_report.md",
    "known_limits_and_r4.md",
    "truth_source_closure.csv",
    "test_coverage_matrix.csv",
    "artifact_manifest.json",
    "completion.json",
}
BASELINES = {
    "/home/icy/MePhC": "690a543e33967fc449fd7d3b28d9c30a07b1a848",
    "/home/icy/TriLatt": "5d84f992310fbe0141df811704a9ffb3811807cb",
    "/home/icy/SqrLatt": "8a1e4534a48e01a83996fb199ccd55e0983e72b2",
}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_tree(repo, prefixes=None):
    root = Path(repo)
    files = subprocess.check_output(
        ["git", "-C", str(root), "ls-files"], text=True
    ).splitlines()
    if prefixes:
        files = [
            f for f in files if any(f == p or f.startswith(p) for p in prefixes)
        ]
    digest = hashlib.sha256()
    for relative in sorted(files):
        path = root / relative
        digest.update(f"{root.name}/{relative}".encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def scientific_digest():
    digest = hashlib.sha256()
    for repo in ("/home/icy/MePhC", "/home/icy/TriLatt", "/home/icy/SqrLatt"):
        digest.update(
            f"{Path(repo).name}:{git_tree(repo, ('data/', 'image/', 'diagnostics/'))}".encode()
        )
    return digest.hexdigest()


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    actual = {path.name for path in ARTIFACT_ROOT.iterdir() if path.is_file()}
    require(actual == EXPECTED_ARTIFACTS, f"unexpected artifact files: {sorted(actual)}")

    manifest = json.loads((ARTIFACT_ROOT / "artifact_manifest.json").read_text())
    completion = json.loads((ARTIFACT_ROOT / "completion.json").read_text())
    require(manifest["self_entry_policy"] == "excluded-recursive-self-hash", "bad manifest self policy")
    require(manifest["reverse_reference_exclusions"] == ["completion.json"], "bad reverse exclusion")
    listed = {entry["path"] for entry in manifest["artifact_files"]}
    require(listed == EXPECTED_ARTIFACTS - {"artifact_manifest.json", "completion.json"}, "manifest coverage mismatch")
    for entry in manifest["artifact_files"]:
        require(sha256(ARTIFACT_ROOT / entry["path"]) == entry["sha256"], f"hash mismatch: {entry['path']}")

    require(completion["status"] == "completed", "completion is not completed")
    require(completion["blockers"] == [], "completion has blockers")
    require({item["id"] for item in completion["workstreams"]} == set("ABCDEFG"), "workstream set mismatch")
    require(all(item["status"] in {"completed", "limited-pass"} for item in completion["workstreams"]), "unfinished workstream")
    require({item["id"] for item in completion["workflows"]} == {"real-space", "band", "berry", "efs", "plotting", "metadata", "records"}, "workflow set mismatch")

    with (ARTIFACT_ROOT / "truth_source_closure.csv").open(newline="") as handle:
        require({"source", "consumer", "identity_behavior", "nonidentity_behavior", "status"} <= set(next(csv.reader(handle))), "truth CSV header")
    with (ARTIFACT_ROOT / "test_coverage_matrix.csv").open(newline="") as handle:
        require({"test_id", "scope", "command_or_test", "expected", "status"} <= set(next(csv.reader(handle))), "coverage CSV header")

    for repo, baseline in BASELINES.items():
        head = subprocess.check_output(["git", "-C", repo, "rev-parse", "HEAD"], text=True).strip()
        require(subprocess.run(["git", "-C", repo, "merge-base", "--is-ancestor", baseline, head]).returncode == 0, f"baseline not ancestor: {repo}")

    integrity = completion["integrity"]
    require(integrity["r1_r2_artifacts_digest_before"] == integrity["r1_r2_artifacts_digest_after"], "R1/R2 digest changed")
    require(integrity["scientific_records_digest_before"] == integrity["scientific_records_digest_after"], "scientific digest changed")
    require(integrity["sqrlatt_tree_digest_before"] == integrity["sqrlatt_tree_digest_after"], "SqrLatt digest changed")
    require(git_tree("/home/icy/MePhC", ("docs/architecture/mephc_affine_architecture_r1/", "docs/architecture/mephc_affine_architecture_r2/")) == integrity["r1_r2_artifacts_digest_before"], "R1/R2 current digest mismatch")
    require(scientific_digest() == integrity["scientific_records_digest_before"], "scientific current digest mismatch")
    require(git_tree("/home/icy/SqrLatt") == integrity["sqrlatt_tree_digest_before"], "SqrLatt current digest mismatch")
    require(sha256(ARTIFACT_ROOT / "artifact_manifest.json") == integrity["artifact_manifest_sha256"], "manifest digest mismatch")
    print("R3 affine architecture validation passed")


if __name__ == "__main__":
    main()
