from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[1]
FINAL = ROOT / "audit/e9f/rp4_b_c1_science_seal_finalization.json"
CORRECTION = ROOT / "audit/e9f/rp4_b_c1_provenance_correction.json"
REGISTRY = ROOT / "audit/e9f/rp4_b_c1_process_reliability_registry.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def find_value(value: object, target: str) -> bool:
    if value == target:
        return True
    if isinstance(value, dict):
        return any(find_value(item, target) for item in value.values())
    if isinstance(value, list):
        return any(find_value(item, target) for item in value)
    return False


def test_rp4_b_c1_finalization_cross_artifact_hashes_and_endpoint_are_solver_free() -> None:
    final = json.loads(FINAL.read_text(encoding="utf-8"))
    correction = json.loads(CORRECTION.read_text(encoding="utf-8"))
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    assert final["base_sandbox_sha"] == "56a55c8a814131a1bbd05f9fc5aefcf3afd74982"
    assert subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "origin/main"], text=True).strip() == "5a4e9e839eff40f582c2404ff3eadd2bf8b676b5"
    for name, artifact in final["path_bound_artifacts"].items():
        assert digest(ROOT / artifact["path"]) == artifact["sha256"], name
    historical = json.loads((ROOT / "audit/e9f/rp3_b_c1_c1_process_science_seal.json").read_text(encoding="utf-8"))
    actual = final["path_bound_artifacts"]["actual_reliability_registry"]["sha256"]
    embedded = "9f1dcfce4e4fdf35967317f952177d3aaa3d3931e6c8237b443ad450b1d2d22e"
    assert actual == "9f1dcf010e4fdf35967317f952177d3aaa3d3931e6c8237b443ad450b1d2d22e"
    assert embedded != actual and find_value(historical, embedded)
    assert correction["mismatch"] is True and correction["actual_registry_sha256"] == actual
    rel058 = next(item for item in registry["incidents"] if item["incident_id"] == "REL-058")
    assert rel058 == {"incident_id": "REL-058", "priority": "P1", "status": "CLOSED"}
    assert registry["p2_items"] == ["REL-022", "REL-025", "REL-034", "REL-035"]
    assert final["endpoint"]["band0"] == "REPORTED:-0.09405797052154485:551/551"
    assert final["endpoint"]["band1"] == "REPORTED:+0.5086915675292921:551/551"
    assert final["endpoint"]["band2"] == "INCOMPLETE_NOT_REPORTED:534/551:17_FAILED:NO_NUMERIC_CHERN"
    assert final["band2_numeric_chern_forbidden"] is True
    assert final["execution"] == {"native_solves": 0, "mpb_execution": False}
