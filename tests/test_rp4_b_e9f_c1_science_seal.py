from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[1]
SEAL = ROOT / "audit/e9f/rp4_b_e9f_c1_science_seal.json"
REPORT = ROOT / "audit/e9f/rp4_b_e9f_c1_science_seal_report.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_rp4_b_source_bound_science_seal_is_exact_and_solver_free() -> None:
    seal = json.loads(SEAL.read_text(encoding="utf-8"))
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    assert seal["work_order_id"] == "MEPHC-E9F-C1-RP4-B-20260826-274"
    assert seal["base_sandbox_sha"] == "f4ae9a30d91dc2fa7448180a05558522590ea0be"
    assert seal["expected_main_sha"] == "5a4e9e839eff40f582c2404ff3eadd2bf8b676b5"
    assert seal["bands"]["band0"] == {"status": "reported", "chern": -0.09405797052154485, "qualified": "551/551"}
    assert seal["bands"]["band1"] == {"status": "reported", "chern": 0.5086915675292921, "qualified": "551/551"}
    band2 = seal["bands"]["band2"]
    assert band2["status"] == "incomplete_not_reported"
    assert band2["qualified"] == "534/551" and band2["failed"] == 17
    assert band2["numeric_chern_forbidden"] is True and "chern" not in band2
    assert band2["failure_accounting"]["persistent_centers"] == [[-34,-17],[-34,-16],[-34,16],[-34,17],[-5,0],[-4,0]]
    assert seal["r192"] == {"can_change_current_reducer_admissibility": False, "can_diagnose_curvature_convergence": True, "required_before_current_science_decision": False}
    assert seal["execution"] == {"native_solves": 0, "mpb_execution": False, "reducer_execution": False, "new_chern_execution": False, "production_mephc_change": False, "main_promotion": False}
    assert report["scientific_seal_path"] == "audit/e9f/rp4_b_e9f_c1_science_seal.json"
    assert report["band2_status_and_counts"].startswith("incomplete_not_reported:534/551")
    for name, value in seal["frozen_artifacts"].items():
        if "path" in value:
            assert sha256(ROOT / value["path"]) == value["sha256"], name
    assert subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "origin/main"], text=True).strip() == seal["expected_main_sha"]
