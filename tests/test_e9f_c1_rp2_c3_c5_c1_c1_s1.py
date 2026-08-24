from __future__ import annotations

import json
from pathlib import Path

from audit.e9f import c3_c5_c1_postprocess as pp

ROOT = Path(__file__).resolve().parents[1]
SEAL = ROOT / "audit/e9f/c3_c5_c1_c1_process_seal.json"
REGISTRY = ROOT / "audit/e9f/c3_c5_c1_c1_process_reliability_registry.json"
SOURCE_RUNTIME = Path("/home/icy/MePhC/.c3-c5-live2/audit/e9f/rp2_c3_c5_runtime_20260825_fix1")


def test_all_closed_canonical_registry_and_seal_bindings():
    seal = json.loads(SEAL.read_text())
    registry = json.loads(REGISTRY.read_text())
    pp.validate_c1_c1_process_registry(registry, closed=True)
    assert seal["base_sandbox_sha"] == "761c8cda69a7d3fc8c663e023f43bc10749852d6"
    assert seal["source_science_execution_sha"] == pp.SOURCE_EXECUTION
    assert seal["source_checkpoint_sha256"] == "871b24983800d178f44d09b2220bcc179804e939f1f4c9163d84917ca5a8ca7d"
    assert seal["source_result_sha256"] == "068cbb6048d5813cbdd5c38efa323e85af3a340d58d7fa69e0e3b5ff1511785a"
    assert seal["source_manifest_sha256"] == "ca9d7fc2184371b1dcf5049a1a8bceaf613372bd69a2cd0449fbf25d4e919d01"
    assert seal["prelive_attestation_sha256"] == "bcb70bc9a8c9b6afc453a5a9dbadeaa2f90eb37edb96bc74a74f6f1c4f0d55b3"
    assert seal["failed_initial_execution_sha"] == pp.FAILED_EXECUTION
    assert registry["p1_items"] == [] and registry["p2_items"] == [] and registry["p0_items"] == []
    assert all(item["status"] == "CLOSED" for item in registry["incidents"])
    assert registry["pipeline_health"] == "PIPELINE_HEALTHY_WITH_TECH_DEBT"


def test_historical_semantics_and_scientific_disposition_are_frozen():
    seal = json.loads(SEAL.read_text())
    failed = seal["failed_initial_attempt"]
    assert failed["sidecar_native_solve_count_raw"] == 0
    assert failed["measured_native_solve_count"] == "UNKNOWN"
    assert failed["control_flow_inferred_completed_solves"] == 5
    assert failed["control_flow_inference_confidence"] == "HIGH"
    assert failed["payload_reused_by_final"] is False
    assert seal["native_solves_performed_by_s1"] == 0
    assert seal["scientific_disposition"] == {
        "rank1_recovered": False,
        "reducer_admissible": False,
        "no_convergence_verdict": True,
        "current_0p02_qualification_unchanged": True,
        "rank2_pair_attribution_to_band2_or_band3": False,
    }


def test_source_hashes_and_payload_bytes_remain_immutable():
    seal = json.loads(SEAL.read_text())
    source = pp.verify_source_matrix(root=ROOT, source_runtime=SOURCE_RUNTIME)
    assert source["checkpoint"]["generation"] == 12
    assert sum(payload["solve_count"] for payload in source["payloads"]) == 108
    assert seal["source_matrix_entry_count"] == 24
    assert seal["source_payloads_immutable"] is True
    assert seal["production_mephc_unchanged"] is True


def test_zero_native_scope_and_accepted_evidence_cardinality():
    seal = json.loads(SEAL.read_text())
    assert seal["native_solves_performed_by_s1"] == 0
    assert seal["mpb_execution_performed"] is False
    assert seal["rp3_started"] is False
    assert seal["reducer_started"] is False
    assert seal["chern_started"] is False
    assert seal["complete_entry_count"] == 24
    assert seal["stencil_delta_count"] == 24
    assert seal["resolution_delta_count"] == 24
    assert seal["raw_replay_record_count"] == 120
    assert seal["unique_replay_key_count"] == 108
